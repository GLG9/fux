import os
import time
import json
import logging
import re
import math
from collections import Counter

import requests
from bs4 import BeautifulSoup, NavigableString
from dotenv import load_dotenv

# Konfiguration aus .env laden

env_path = ".env"

# .env-Datei einlesen. Existierende Umgebungsvariablen bleiben erhalten und
# Werte aus der Datei überschreiben diese, wenn vorhanden. Es werden jedoch
# keine Variablen gel\xC3\xB6scht, damit Testumgebungen oder externe Settings nicht
# unbeabsichtigt entfernt werden.
load_dotenv(env_path, override=True)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
INTERVAL_MINUTES = int(os.getenv("INTERVAL_MINUTES", "5"))
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


def _parse_semester_table(table):
    """Parse a semester table and return structured grade information."""
    result = {}
    if not table:
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
                if text:
                    try:
                        finals.append(float(text.replace(",", ".")))
                    except ValueError:
                        pass
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
                try:
                    grades_avg = float(last.replace(",", "."))
                except ValueError:
                    pass

        avg = finals[0] if finals else None

        result[subject] = {
            "tests": tests,
            "grades": grades,
            "grades_average": grades_avg,
            "average": avg,
        }

    return result


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

    period_numbers = sorted(period_tables.keys())
    period_labels = [f"H{pos}" for pos in range(1, len(period_numbers) + 1)]
    label_map = {num: period_labels[i] for i, num in enumerate(period_numbers)}

    all_table = soup.find("table", id="student_main_grades_table_all")
    header_text = " "
    finals_by_subject: dict[str, list[float]] = {}
    if all_table:
        header_text = " ".join(
            th.get_text(" ", strip=True) for th in all_table.find_all("th", class_="text-center")
        )
        if all_table.tbody:
            for row in all_table.tbody.find_all("tr"):
                tds = _iter_cells(row)
                if not tds:
                    continue
                subject = tds[0].get_text(strip=True)
                finals = []
                for td in row.find_all("td", class_="final_average"):
                    text = td.get_text(strip=True).replace(",", ".")
                    if not text:
                        continue
                    try:
                        finals.append(float(text))
                    except ValueError:
                        continue
                finals_by_subject[subject] = finals

    nums = re.findall(r"[0-9]+,[0-9]+", header_text)
    num_values = [float(n.replace(",", ".")) for n in nums]

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
                    subject_info[avg_key] = finals[idx]
        subject_info["YearAverage"] = finals[-1] if len(finals) > len(period_numbers) else None
        subjects[subject] = subject_info

    final_container = soup.find("div", id=re.compile("student_final_grades_container"))
    if final_container:
        ftbl = final_container.find("table")
        if ftbl and ftbl.tbody:
            for row in ftbl.tbody.find_all("tr"):
                cells = _iter_cells(row)
                if not cells:
                    continue
                subject = cells[0].get_text(strip=True)
                score_cells = [
                    td for td in cells[1:] if "score_display" in td.get("class", [])
                ]

                def parse_int_cell(td):
                    text = td.get_text(strip=True)
                    return int(text) if text.isdigit() else None

                def parse_float_cell(td):
                    text = td.get_text(strip=True).replace(",", ".")
                    if not text:
                        return None
                    try:
                        return float(text)
                    except ValueError:
                        return None

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
                for idx, value in enumerate(avg_values, start=1):
                    label = f"H{idx}"
                    key = f"{label}Average"
                    if value is not None:
                        subject_info[key] = value
                if avg_values:
                    for value in reversed(avg_values):
                        if value is not None:
                            subject_info["YearAverage"] = value
                            break
                for idx, value in enumerate(final_values, start=1):
                    label = f"H{idx}"
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
        subject_info.setdefault("YearAverage", None)
        subject_info.setdefault("FinalGrade", None)

    result: dict[str, object] = {
        "subjects": subjects,
        "FinalAverage": num_values[-1] if num_values else None,
        "PeriodLabels": period_labels,
    }
    for idx, value in enumerate(num_values[:-1], start=1):
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


def collect_messages(user_name, new_data, old_data, show_year_average=True):
    """Create Discord messages for all new grades of a user."""

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
        year_average_formatted = _format_average(info.get("YearAverage"))
        grade_related_change = False
        for label in period_labels:
            grade_key = f"{label}Grades"
            exam_key = f"{label}Exams"
            for grade in _list_diff(old_info.get(grade_key, []), info.get(grade_key, [])):
                msg = f"[{user_name}] Neue Note in {subject} ({label}): {grade}"
                if show_year_average:
                    if year_average_formatted:
                        msg += f" Damit stehst du jetzt {year_average_formatted}"
                parts.append(msg)
                grade_related_change = True
            for grade in _list_diff(old_info.get(exam_key, []), info.get(exam_key, [])):
                msg = f"[{user_name}] Neue Klassenarbeitsnote in {subject} ({label}): {grade}"
                if show_year_average:
                    if year_average_formatted:
                        msg += f" Damit stehst du jetzt {year_average_formatted}"
                parts.append(msg)
                grade_related_change = True

        for idx, label in enumerate(period_labels, start=1):
            key = f"{label}FinalGrade"
            new_final = info.get(key)
            if new_final is not None and new_final != old_info.get(key):
                parts.append(
                    f"[{user_name}] Zeugnisnote (HJ{idx}) in {subject} steht fest: {new_final}"
                )

        if (
            show_year_average
            and _value_changed(old_info.get("YearAverage"), info.get("YearAverage"))
            and not grade_related_change
        ):
            new_avg = _format_average(info.get("YearAverage"))
            if new_avg:
                prev_avg = _format_average(old_info.get("YearAverage"))
                message = f"[{user_name}] Jahresdurchschnitt in {subject} ist jetzt {new_avg}"
                if prev_avg:
                    message += f" (vorher {prev_avg})"
                parts.append(message)

        if parts:
            messages.append("\n".join(parts))

    return messages



# Dateien für gespeicherte Notenstände pro Benutzer
old_data = {}
for u in USERS:
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", u["name"])
    file = f"old_grades_{safe_name}.json"
    if os.path.exists(file):
        with open(file, "r", encoding="utf-8") as f:
            old_data[u["name"]] = json.load(f)
    else:
        old_data[u["name"]] = {}


def fetch_html(username: str, password: str, session: requests.Session | None = None):
    """Meldet sich im Elternportal an oder liest lokale Daten im Debug-Modus."""
    if session is None:
        session = requests.Session()

    if DEBUG_LOCAL:
        url = "http://localhost:8000/index.html"
        try:
            if SHOW_HTTPS:
                logging.info("HTTP GET %s (debug local)", url)
            resp = session.get(url)
        except Exception as e:
            logging.error(f"Lokaler Abruf fehlgeschlagen: {e}")
            return None
        if SHOW_RES:
            logging.info("Lokale Response (%s): %s", resp.status_code, resp.text)
        else:
            logging.info("Lokale Response (%s)", resp.status_code)
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
        login_page = session.get(login_url)
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
                "HTTP POST %s (username=%s, password=%s)",
                login_url,
                username,
                password,
            )
        resp = session.post(login_url, data=payload, allow_redirects=True)
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
        grades_page = session.get(grades_url)
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

    return parse_grades(grades_page.text)


if __name__ == "__main__":
    # Hauptschleife: regelmäßige Prüfung im konfigurierten Intervall
    logging.info("Noten-Checker gestartet. Warte auf neue Noten...")
    while True:
        for user in USERS:
            # Neue Session pro Benutzer, um unabhängige Logins zu gewährleisten
            with requests.Session() as session:
                data = fetch_html(user["username"], user["password"], session=session)
            if data is None:
                continue

            old_info_all = old_data.get(user["name"], {})
            subject_messages = collect_messages(
                user["name"], data, old_info_all, show_year_average=SHOW_YEAR_AVERAGE
            )

            if subject_messages:
                url = f"https://discord.com/api/channels/{DISCORD_CHANNEL_ID}/messages"
                headers = {
                    "Authorization": f"Bot {DISCORD_TOKEN}",
                    "Content-Type": "application/json",
                }
                for msg in subject_messages:
                    payload = {"content": msg}
                    try:
                        res = requests.post(url, headers=headers, json=payload)
                        if 200 <= res.status_code < 300:
                            logging.info(
                                "Nachricht an Discord gesendet: %s", payload["content"]
                            )
                        else:
                            logging.error(
                                f"Discord-API-Fehler ({res.status_code}): {res.text}"
                            )
                    except Exception as e:
                        logging.error(f"Fehler beim Senden an Discord: {e}")
                    time.sleep(1)
            else:
                logging.info(f"Keine neuen Noten gefunden f\xC3\xBCr {user['name']}.")

            safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", user["name"])
            with open(f"grades_{safe_name}.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            old_data[user["name"]] = data
            with open(f"old_grades_{safe_name}.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        time.sleep(INTERVAL_MINUTES * 60)
