import os
import time
import json
import logging
import re
import math
from datetime import datetime
from collections import Counter

import requests
from bs4 import BeautifulSoup, NavigableString
from dotenv import load_dotenv

# Konfiguration aus .env laden

env_path = ".env"

# .env-Datei einlesen. Bereits gesetzte Umgebungsvariablen behalten Vorrang,
# damit Tests und externe Deployments lokale Defaults gezielt ueberschreiben
# koennen. Nicht gesetzte Werte werden aus der Datei ergaenzt.
load_dotenv(env_path, override=False)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
INTERVAL_MINUTES = int(os.getenv("INTERVAL_MINUTES", "5"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
SHOW_RES = os.getenv("SHOW_RES", "false").lower() == "true"
SHOW_HTTPS = os.getenv("SHOW_HTTPS", "false").lower() == "true"
DEBUG_LOCAL = os.getenv("DEBUG_LOCAL", "false").lower() == "true"
SHOW_YEAR_AVERAGE = os.getenv("SHOW_YEAR_AVERAGE", "true").lower() == "true"

# Mehrere Benutzer aus der .env-Datei laden
# Die Indizes müssen nicht lückenlos sein; vorhandene Paare werden gesammelt
USERS = []
user_indexes = set()
for key in os.environ:
    m = re.match(r"USER(\d+)$", key)
    if m:
        user_indexes.add(int(m.group(1)))

for i in sorted(user_indexes):
    name = os.getenv(f"USER{i}")
    username = os.getenv(f"USERNAME{i}")
    password = os.getenv(f"PASSWORD{i}")
    if not name:
        continue
    if not DEBUG_LOCAL and not (username and password):
        continue
    USERS.append({"name": name, "username": username, "password": password})


def check_env():
    """Ensure all required environment variables are present."""
    missing = []
    if not USERS:
        missing.append("USERn" if DEBUG_LOCAL else "USERn/USERNAMEn/PASSWORDn")
    if not DISCORD_TOKEN:
        missing.append("DISCORD_TOKEN")
    if not DISCORD_CHANNEL_ID:
        missing.append("DISCORD_CHANNEL_ID")
    if missing:
        logging.error("Fehlende Umgebungsvariablen: " + ", ".join(missing))
        raise SystemExit(1)


# Logging einstellen (Schreiben in noten_checker.log mit Zeitstempel und Level)
logging.basicConfig(
    filename="noten_checker.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


check_env()


def _iter_cells(row):
    """Yield td elements, also converting stray text nodes to td-like objects."""
    cells = []
    for child in row.children:
        if isinstance(child, NavigableString):
            text = child.strip()
            if text:
                dummy = BeautifulSoup(f"<td>{text}</td>", "html.parser").td
                cells.append(dummy)
        elif getattr(child, "name", None) == "td":
            cells.append(child)
    return cells


def _parse_non_negative_float(text: str) -> float | None:
    """Parse float values from the portal, ignoring empty and placeholder negatives."""
    normalized = text.strip().replace(",", ".")
    if not normalized:
        return None
    try:
        value = float(normalized)
    except ValueError:
        return None
    return value if value >= 0 else None


def _parse_non_negative_int(text: str) -> int | None:
    """Parse integer values from the portal, ignoring empty and placeholder negatives."""
    normalized = text.strip()
    if not normalized:
        return None
    try:
        value = int(normalized)
    except ValueError:
        return None
    return value if value >= 0 else None


def _parse_semester_table(table):
    """Parse a semester table and return structured grade information."""
    result = {}
    if not table or not table.tbody:
        return result

    for row in table.tbody.find_all("tr"):
        cells = _iter_cells(row)
        if not cells:
            continue

        subject = cells[0].get_text(strip=True)
        # Separate final_average cells from regular grade cells
        finals = []
        values = []
        for td in cells[1:]:
            text = td.get_text(strip=True)
            if "final_average" in td.get("class", []):
                finals.append(_parse_non_negative_float(text))
            else:
                values.append(text)

        # Expect: first two entries -> class tests, last entry -> average of
        # regular grades. Everything in between are regular grades themselves.
        tests = []
        for v in values[:2]:
            if not v:
                continue
            if "," in v:
                v = v.split(",", 1)[0]
            if not tests or tests[-1] != v:
                tests.append(v)
        grades = [v for v in values[2:-1] if v]
        grades_avg = None
        if values:
            last = values[-1]
            if last:
                grades_avg = _parse_non_negative_float(last)

        # In H2-H4 the portal renders one final-average column per Halbjahr.
        # The last one belongs to the currently shown period.
        avg = finals[-1] if finals else None

        result[subject] = {
            "tests": tests,
            "grades": grades,
            "grades_average": grades_avg,
            "average": avg,
        }

    return result


def _extract_period_numbers(period_tables, all_table, final_container) -> list[int]:
    """Detect available Halbjahre from the rendered portal sections."""
    if period_tables:
        return sorted(period_tables.keys())

    period_count = 0
    if all_table and all_table.thead:
        first_header_row = all_table.thead.find("tr")
        if first_header_row:
            period_count = max(period_count, len(first_header_row.find_all("th", class_="text-center")))

    if final_container:
        final_table = final_container.find("table")
        if final_table and final_table.thead:
            header_row = final_table.thead.find("tr")
            if header_row:
                count = 0
                for th in header_row.find_all("th"):
                    classes = th.get("class", [])
                    if "display_final_grade" in classes or "display_avg" in classes:
                        count += 1
                if count:
                    period_count = max(period_count, count // 2)

    return list(range(1, period_count + 1))


def _parse_overview_period_averages(all_table, period_count: int) -> tuple[dict[str, list[float | None]], list[float | None]]:
    """Parse the grouped all-period table and return per-subject and top-level averages."""
    per_subject: dict[str, list[float | None]] = {}
    top_level: list[float | None] = []
    if not all_table:
        return per_subject, top_level

    group_sizes: list[int] = []
    if all_table.thead:
        first_header_row = all_table.thead.find("tr")
        if first_header_row:
            for th in first_header_row.find_all("th", class_="text-center"):
                text = th.get_text(" ", strip=True)
                matches = re.findall(r"-?[0-9]+,[0-9]+", text)
                top_level.append(
                    next(
                        (
                            parsed
                            for parsed in (_parse_non_negative_float(match) for match in matches)
                            if parsed is not None
                        ),
                        None,
                    )
                )
                try:
                    colspan = int(th.get("colspan") or 0)
                except ValueError:
                    colspan = 0
                if colspan > 0:
                    group_sizes.append(colspan)

    if not all_table.tbody:
        return per_subject, top_level

    for row in all_table.tbody.find_all("tr"):
        cells = _iter_cells(row)
        if not cells:
            continue
        subject = cells[0].get_text(strip=True)
        row_cells = cells[1:]
        period_averages: list[float | None] = []

        if group_sizes and sum(group_sizes) <= len(row_cells):
            offset = 0
            for size in group_sizes:
                segment = row_cells[offset : offset + size]
                offset += size
                finals = [
                    _parse_non_negative_float(td.get_text(strip=True))
                    for td in segment
                    if "final_average" in td.get("class", [])
                ]
                period_averages.append(finals[-1] if finals else None)
        else:
            finals = [
                _parse_non_negative_float(td.get_text(strip=True))
                for td in row.find_all("td", class_="final_average")
            ]
            if period_count:
                period_averages = finals[:period_count]
            else:
                period_averages = finals

        per_subject[subject] = period_averages

    return per_subject, top_level


def _subject_has_period_data(subject_info: dict[str, object], label: str) -> bool:
    return (
        bool(subject_info.get(f"{label}Exams"))
        or bool(subject_info.get(f"{label}Grades"))
        or subject_info.get(f"{label}GradesAverage") is not None
        or subject_info.get(f"{label}Average") is not None
        or subject_info.get(f"{label}FinalGrade") is not None
    )


def _derive_year_average(subject_info: dict[str, object], period_labels: list[str]) -> float | None:
    """Use the current active Halbjahr average, but never fall back across periods."""
    latest_active_label = None
    for label in period_labels:
        if _subject_has_period_data(subject_info, label):
            latest_active_label = label
    if not latest_active_label:
        return None
    value = subject_info.get(f"{latest_active_label}Average")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _has_grade_markup(soup: BeautifulSoup) -> bool:
    """Return True when the response contains the expected grade UI."""
    return bool(
        soup.find("table", id=re.compile(r"^student_main_grades_table_(all|\d+)$"))
        or soup.find("div", id=re.compile("student_final_grades_container"))
    )


def parse_grades(html):
    """Parse grades tables from HTML and return structured data."""
    soup = BeautifulSoup(html, "html.parser")

    period_tables: dict[int, dict[str, dict[str, object]]] = {}
    for table in soup.find_all("table", id=re.compile(r"^student_main_grades_table_(\d+)$")):
        match = re.match(r"^student_main_grades_table_(\d+)$", table.get("id", ""))
        if not match:
            continue
        idx = int(match.group(1))
        period_tables[idx] = _parse_semester_table(table)

    all_table = soup.find("table", id="student_main_grades_table_all")
    final_container = soup.find("div", id=re.compile("student_final_grades_container"))
    period_numbers = _extract_period_numbers(period_tables, all_table, final_container)
    period_labels = [f"H{num}" for num in period_numbers]
    label_map = {num: f"H{num}" for num in period_numbers}

    finals_by_subject, num_values = _parse_overview_period_averages(all_table, len(period_numbers))

    all_subjects: set[str] = set(finals_by_subject)
    for pdata in period_tables.values():
        all_subjects.update(pdata.keys())

    subjects: dict[str, dict[str, object]] = {}
    for subject in sorted(all_subjects):
        subject_info: dict[str, object] = {}
        for idx, period_num in enumerate(period_numbers):
            label = label_map[period_num]
            sem_data = period_tables.get(period_num, {}).get(subject, {})
            subject_info[f"{label}Exams"] = sem_data.get("tests", [])
            subject_info[f"{label}Grades"] = sem_data.get("grades", [])
            subject_info[f"{label}GradesAverage"] = sem_data.get("grades_average")
            subject_info[f"{label}Average"] = sem_data.get("average")

        finals = finals_by_subject.get(subject, [])
        if finals and period_numbers:
            for idx, label in enumerate(period_labels):
                avg_key = f"{label}Average"
                if subject_info.get(avg_key) is None and idx < len(finals):
                    value = finals[idx]
                    if value is not None:
                        subject_info[avg_key] = value
        subject_info["YearAverage"] = None
        subjects[subject] = subject_info

    if final_container:
        ftbl = final_container.find("table")
        if ftbl and ftbl.tbody:
            for row in ftbl.tbody.find_all("tr"):
                cells = _iter_cells(row)
                if not cells:
                    continue
                subject = cells[0].get_text(strip=True)
                score_cells = []
                for td in cells[1:]:
                    classes = td.get("class", [])
                    if (
                        "score_display" in classes
                        or "display_avg" in classes
                        or "display_final_grade" in classes
                    ):
                        score_cells.append(td)

                def parse_int_cell(td):
                    return _parse_non_negative_int(td.get_text(strip=True))

                def parse_float_cell(td):
                    return _parse_non_negative_float(td.get_text(strip=True))

                avg_values: list[float | None] = []
                final_values: list[int | None] = []
                for td in score_cells:
                    classes = td.get("class", [])
                    if "display_avg" in classes:
                        avg_values.append(parse_float_cell(td))
                    if "display_final_grade" in classes:
                        final_values.append(parse_int_cell(td))
                if subject not in subjects:
                    subjects[subject] = {}
                subject_info = subjects[subject]
                last_final = None
                for idx, value in enumerate(avg_values):
                    label = period_labels[idx] if idx < len(period_labels) else f"H{idx + 1}"
                    key = f"{label}Average"
                    if value is not None:
                        subject_info[key] = value
                for idx, value in enumerate(final_values):
                    label = period_labels[idx] if idx < len(period_labels) else f"H{idx + 1}"
                    subject_info[f"{label}FinalGrade"] = value
                    if value is not None:
                        last_final = value
                subject_info["FinalGrade"] = last_final

    for subject_info in subjects.values():
        for idx, label in enumerate(period_labels, start=1):
            subject_info.setdefault(f"{label}Exams", [])
            subject_info.setdefault(f"{label}Grades", [])
            subject_info.setdefault(f"{label}GradesAverage", None)
            subject_info.setdefault(f"{label}Average", None)
            subject_info.setdefault(f"{label}FinalGrade", None)
        current_period_average = _derive_year_average(subject_info, period_labels)
        subject_info["CurrentPeriodAverage"] = current_period_average
        # Backwards-compatible key for existing status files and tests.
        subject_info["YearAverage"] = current_period_average
        subject_info.setdefault("FinalGrade", None)

    result: dict[str, object] = {
        "subjects": subjects,
        "FinalAverage": next((value for value in reversed(num_values) if value is not None), None),
        "PeriodLabels": period_labels,
    }
    for idx, value in enumerate(num_values, start=1):
        if value is not None:
            result[f"N{idx}"] = value

    return result


def _list_diff(old_list, new_list):
    """Return items that are new or changed compared to the previous list."""
    diff = []
    counter = Counter(old_list or [])
    for item in new_list or []:
        if counter.get(item, 0):
            counter[item] -= 1
        else:
            diff.append(item)
    return diff


def _format_average(value: object) -> str | None:
    """Format numeric averages with German decimal styling."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if float(value) < 0:
            return None
        return f"{float(value):.2f}".replace(".", ",")
    return str(value)


def _value_changed(old: object, new: object, *, abs_tol: float = 1e-4) -> bool:
    """Return True if two values differ, considering floats with tolerance."""
    if old is None and new is None:
        return False
    if old is None or new is None:
        return True
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return not math.isclose(float(old), float(new), rel_tol=0.0, abs_tol=abs_tol)
    return old != new


def _collect_subject_messages(user_name, new_data, old_data, show_year_average=True):
    """Create Discord messages and keep the owning subject for state updates."""
    period_labels = new_data.get("PeriodLabels") or []
    subjects = new_data.get("subjects", {})
    old_subjects = (old_data or {}).get("subjects", {}) if isinstance(old_data, dict) else {}

    if not period_labels and subjects:
        detected = set()
        for info in subjects.values():
            for key in info.keys():
                match = re.match(r"^(H\d+)Grades$", key)
                if match:
                    detected.add(match.group(1))
        period_labels = sorted(
            detected,
            key=lambda label: int(re.search(r"\d+", label).group(0)) if re.search(r"\d+", label) else label,
        )

    messages = []
    for subject, info in subjects.items():
        parts = []
        old_info = old_subjects.get(subject, {})
        current_average_formatted = _format_average(
            info.get("CurrentPeriodAverage", info.get("YearAverage"))
        )
        grade_related_change = False
        for label in period_labels:
            grade_key = f"{label}Grades"
            exam_key = f"{label}Exams"
            for grade in _list_diff(old_info.get(grade_key, []), info.get(grade_key, [])):
                msg = f"[{user_name}] Neue Note in {subject} ({label}): {grade}"
                if show_year_average:
                    if current_average_formatted:
                        msg += f" Damit stehst du aktuell bei {current_average_formatted}"
                parts.append(msg)
                grade_related_change = True
            for grade in _list_diff(old_info.get(exam_key, []), info.get(exam_key, [])):
                msg = f"[{user_name}] Neue Klassenarbeitsnote in {subject} ({label}): {grade}"
                if show_year_average:
                    if current_average_formatted:
                        msg += f" Damit stehst du aktuell bei {current_average_formatted}"
                parts.append(msg)
                grade_related_change = True

        for label in period_labels:
            key = f"{label}FinalGrade"
            new_final = info.get(key)
            if new_final is not None and new_final != old_info.get(key):
                match = re.search(r"\d+", label)
                period_number = match.group(0) if match else label
                parts.append(
                    f"[{user_name}] Zeugnisnote (HJ{period_number}) in {subject} steht fest: {new_final}"
                )

        if (
            show_year_average
            and _value_changed(
                old_info.get("CurrentPeriodAverage", old_info.get("YearAverage")),
                info.get("CurrentPeriodAverage", info.get("YearAverage")),
            )
            and not grade_related_change
        ):
            new_avg = _format_average(info.get("CurrentPeriodAverage", info.get("YearAverage")))
            if new_avg:
                prev_avg = _format_average(
                    old_info.get("CurrentPeriodAverage", old_info.get("YearAverage"))
                )
                message = f"[{user_name}] Aktueller Halbjahresschnitt in {subject} ist jetzt {new_avg}"
                if prev_avg:
                    message += f" (vorher {prev_avg})"
                parts.append(message)

        if parts:
            messages.append((subject, "\n".join(parts)))

    return messages


def collect_messages(user_name, new_data, old_data, show_year_average=True):
    """Create Discord messages for all new grades of a user."""
    return [
        message
        for _, message in _collect_subject_messages(
            user_name, new_data, old_data, show_year_average=show_year_average
        )
    ]


def _load_json_file(path: str) -> dict:
    """Load stored grades defensively so a truncated file does not crash the bot."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logging.warning("Ungültige Statusdatei %s wird ignoriert: %s", path, e)
        return {}
    except OSError as e:
        logging.error("Statusdatei %s konnte nicht gelesen werden: %s", path, e)
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_file(path: str, data: dict) -> None:
    """Write status files atomically to avoid partial JSON after a crash."""
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _single_line_log_text(text: object) -> str:
    """Keep log messages on one line even if Discord payloads contain newlines."""
    return str(text).replace("\r", "\\r").replace("\n", " | ")


def _send_discord_message(content: str) -> bool:
    """Send one Discord message and report whether it was accepted."""
    url = f"https://discord.com/api/channels/{DISCORD_CHANNEL_ID}/messages"
    headers = {
        "Authorization": f"Bot {DISCORD_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"content": content}
    for attempt in range(2):
        try:
            res = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except Exception as e:
            logging.error(f"Fehler beim Senden an Discord: {e}")
            return False

        if 200 <= res.status_code < 300:
            logging.info(
                "Nachricht an Discord gesendet: %s",
                _single_line_log_text(payload["content"]),
            )
            return True

        if res.status_code == 429 and attempt == 0:
            retry_after = 1.0
            try:
                retry_after = float(res.json().get("retry_after", retry_after))
            except Exception:
                pass
            logging.warning("Discord Rate Limit, retry in %.2fs", retry_after)
            time.sleep(max(0.0, min(retry_after, 30.0)))
            continue

        logging.error("Discord-API-Fehler (%s): %s", res.status_code, res.text)
        return False

    return False


def _send_startup_message(now: datetime | None = None) -> bool:
    """Announce a fresh bot process start in Discord."""
    if now is None:
        now = datetime.now()
    return _send_discord_message(
        f"[System] Fux Noten-Checker gestartet ({now:%d.%m.%Y %H:%M})."
    )


def _advance_stored_subjects(old_info_all: dict, new_data: dict, successful_subjects: set[str]) -> dict:
    """Advance stored state only for subjects whose notifications were delivered."""
    updated = json.loads(json.dumps(old_info_all or {}, ensure_ascii=False))
    new_subjects = new_data.get("subjects", {}) if isinstance(new_data, dict) else {}
    old_subjects = updated.setdefault("subjects", {})
    for subject in successful_subjects:
        if subject in new_subjects:
            old_subjects[subject] = new_subjects[subject]
    for key, value in new_data.items():
        if key != "subjects":
            updated[key] = value
    return updated


def _seconds_until_next_interval(
    now: datetime | None = None,
    interval_minutes: int | None = None,
) -> float:
    """Return seconds until the next wall-clock interval boundary."""
    if now is None:
        now = datetime.now()
    if interval_minutes is None:
        interval_minutes = INTERVAL_MINUTES
    if interval_minutes <= 0:
        return 0.0

    interval_seconds = interval_minutes * 60
    seconds_since_midnight = (
        now.hour * 3600
        + now.minute * 60
        + now.second
        + now.microsecond / 1_000_000
    )
    remainder = seconds_since_midnight % interval_seconds
    if math.isclose(remainder, 0.0, rel_tol=0.0, abs_tol=1e-9):
        return 0.0
    return interval_seconds - remainder


def _should_run_now_on_startup(
    now: datetime | None = None,
    interval_minutes: int | None = None,
    startup_grace_seconds: float = 5.0,
) -> bool:
    """Allow an immediate startup run when the process starts just after a slot."""
    if now is None:
        now = datetime.now()
    if interval_minutes is None:
        interval_minutes = INTERVAL_MINUTES
    if interval_minutes <= 0:
        return True

    interval_seconds = interval_minutes * 60
    seconds_since_midnight = (
        now.hour * 3600
        + now.minute * 60
        + now.second
        + now.microsecond / 1_000_000
    )
    remainder = seconds_since_midnight % interval_seconds
    return remainder <= startup_grace_seconds or math.isclose(
        remainder, 0.0, rel_tol=0.0, abs_tol=1e-9
    )


def _sleep_until_next_interval(interval_minutes: int | None = None) -> None:
    """Sleep until the next aligned run slot."""
    seconds = _seconds_until_next_interval(interval_minutes=interval_minutes)
    if seconds > 0:
        time.sleep(seconds)


def run_once():
    """Run one complete grade polling cycle for all configured users."""
    global old_data
    for user in USERS:
        # Neue Session pro Benutzer, um unabhängige Logins zu gewährleisten
        with requests.Session() as session:
            data = fetch_html(user["username"], user["password"], session=session)
        if data is None:
            continue

        old_info_all = old_data.get(user["name"], {})
        subject_messages = _collect_subject_messages(
            user["name"], data, old_info_all, show_year_average=SHOW_YEAR_AVERAGE
        )

        safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", user["name"])
        if subject_messages:
            successful_subjects = set()
            failed_subjects = set()
            for subject, msg in subject_messages:
                if _send_discord_message(msg):
                    successful_subjects.add(subject)
                else:
                    failed_subjects.add(subject)
                time.sleep(1)

            if failed_subjects:
                advanced = _advance_stored_subjects(
                    old_info_all,
                    data,
                    successful_subjects,
                )
                old_data[user["name"]] = advanced
                _write_json_file(f"old_grades_{safe_name}.json", advanced)
                _write_json_file(f"grades_{safe_name}.json", data)
                logging.error(
                    "Notenstand für %s nur teilweise fortgeschrieben; fehlgeschlagene Fächer: %s",
                    user["name"],
                    ", ".join(sorted(failed_subjects)),
                )
                continue
        else:
            logging.info(f"Keine neuen Noten gefunden für {user['name']}.")

        _write_json_file(f"grades_{safe_name}.json", data)
        old_data[user["name"]] = data
        _write_json_file(f"old_grades_{safe_name}.json", data)



# Dateien für gespeicherte Notenstände pro Benutzer
old_data = {}
for u in USERS:
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", u["name"])
    file = f"old_grades_{safe_name}.json"
    old_data[u["name"]] = _load_json_file(file)


def fetch_html(username: str, password: str, session: requests.Session | None = None):
    """Meldet sich im Elternportal an oder liest lokale Daten im Debug-Modus."""
    if session is None:
        session = requests.Session()

    if DEBUG_LOCAL:
        url = "http://localhost:8000/index.html"
        try:
            if SHOW_HTTPS:
                logging.info("HTTP GET %s (debug local)", url)
            resp = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        except Exception as e:
            logging.error(f"Lokaler Abruf fehlgeschlagen: {e}")
            return None
        if resp.status_code != 200:
            logging.error("Lokaler Abruf fehlgeschlagen – Status %s", resp.status_code)
            return None
        if SHOW_RES:
            logging.info("Lokale Response (%s): %s", resp.status_code, resp.text)
        else:
            logging.info("Lokale Response (%s)", resp.status_code)
        soup = BeautifulSoup(resp.text, "html.parser")
        if not _has_grade_markup(soup):
            logging.error("Lokale Response enthält keine erwartete Notenansicht")
            return None
        return parse_grades(resp.text)

    # Schritt 1: Login-Seite abrufen, um Nonce und versteckte Felder zu erhalten
    login_url = "https://100308.fuxnoten.online/webinfo"
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "Referer": login_url,
        }
    )
    try:
        if SHOW_HTTPS:
            logging.info("HTTP GET %s (username=%s)", login_url, username)
        login_page = session.get(login_url, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception as e:
        logging.error(f"Login-Seite nicht erreichbar: {e}")
        return None
    if SHOW_RES:
        logging.info(
            "Login-Seite Response (%s): %s",
            login_page.status_code,
            login_page.text,
        )
        
    else:
        logging.info("Login-Seite Response (%s)", login_page.status_code)

    soup = BeautifulSoup(login_page.text, "html.parser")
    nonce_field = soup.find("input", {"name": "_nonce"})
    f_secure_field = soup.find("input", {"name": "_f_secure"})
    nonce = nonce_field["value"] if nonce_field else ""
    f_secure = f_secure_field["value"] if f_secure_field else ""

    payload = {
        "user": username,
        "password": password,
        "fuxnoten_post_controller": "\\Objects\\Webinfo_Object",
        "acount_action": "login",
        "_referrer": "https://100308.fuxnoten.online/webinfo/",
        "_nonce": nonce,
        "_f_secure": f_secure,
    }

    # Schritt 2: Login-POST mit allen erforderlichen Feldern
    try:
        if SHOW_HTTPS:
            logging.info(
                "HTTP POST %s (username=%s)",
                login_url,
                username,
            )
        resp = session.post(
            login_url,
            data=payload,
            allow_redirects=True,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as e:
        logging.error(f"Login-Request fehlgeschlagen: {e}")
        return None
    if SHOW_RES:
        logging.info(
            "Login-POST Response (%s): %s",
            resp.status_code,
            resp.text,
        )
    else:
        logging.info("Login-POST Response (%s)", resp.status_code)

    # Prüfen, ob Login erfolgreich war. Nach einem erfolgreichen Login wird
    # auf "/account" weitergeleitet. Ein einfacher Textcheck funktioniert
    # nicht zuverlässig, da die Zielseite ebenfalls Felder mit dem Namen
    # "user" enthalten kann.
    if resp.status_code != 200 or "/account" not in resp.url:
        logging.error(
            "Login fehlgeschlagen – Status %s, URL %s", resp.status_code, resp.url
        )
        return None

    # Notenübersicht abrufen (nach erfolgreichem Login)
    try:
        grades_url = "https://100308.fuxnoten.online/webinfo/account/"
        if SHOW_HTTPS:
            logging.info(
                "HTTP GET %s (username=%s)",
                grades_url,
                username,
            )
        grades_page = session.get(grades_url, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception as e:
        logging.error(f"Fehler beim Abrufen der Notenübersicht: {e}")
        return None
    if SHOW_RES:
        logging.info(
            "Notenübersicht Response (%s): %s",
            grades_page.status_code,
            grades_page.text,
        )
    else:
        logging.info("Notenübersicht Response (%s)", grades_page.status_code)

    if grades_page.status_code != 200:
        logging.error("Notenübersicht fehlgeschlagen – Status %s", grades_page.status_code)
        return None

    grades_soup = BeautifulSoup(grades_page.text, "html.parser")
    if not _has_grade_markup(grades_soup):
        logging.error(
            "Notenübersicht enthält keine erwartete Notenansicht – URL %s",
            grades_page.url,
        )
        return None

    return parse_grades(grades_page.text)


if __name__ == "__main__":
    # Hauptschleife: regelmäßige Prüfung zu festen Uhrzeit-Slots
    logging.info("Noten-Checker gestartet. Erster Abruf läuft sofort.")
    if not _send_startup_message():
        logging.error("Startmeldung konnte nicht an Discord gesendet werden.")
    while True:
        run_once()
        _sleep_until_next_interval()
