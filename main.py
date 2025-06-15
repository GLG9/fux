import os
import time
import json
import logging
import re
import requests
from bs4 import BeautifulSoup, NavigableString
from dotenv import load_dotenv, dotenv_values

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

    all_table = soup.find("table", id="student_main_grades_table_all")
    header_text = " ".join(
        th.get_text(" ", strip=True) for th in all_table.find_all("th", class_="text-center")
    )
    nums = re.findall(r"[0-9]+,[0-9]+", header_text)
    n1 = float(nums[0].replace(",", ".")) if len(nums) > 0 else None
    n2 = float(nums[1].replace(",", ".")) if len(nums) > 1 else None
    final = float(nums[2].replace(",", ".")) if len(nums) > 2 else None

    period1 = soup.find("table", id="student_main_grades_table_1")
    p1 = _parse_semester_table(period1)

    period2 = soup.find("table", id="student_main_grades_table_2")
    p2 = _parse_semester_table(period2)

    subjects = {}
    for row in all_table.tbody.find_all("tr"):
        tds = _iter_cells(row)
        if not tds:
            continue
        subject = tds[0].get_text(strip=True)
        finals = [td.get_text(strip=True) for td in row.find_all("td", class_="final_average")]
        finals = [f.replace(",", ".") for f in finals if f]
        finals = [float(f) for f in finals if re.match(r"^-?\d+(?:\.\d+)?$", f)]
        h1_avg = finals[0] if len(finals) > 0 else None
        if len(finals) >= 4:
            h2_avg = finals[2]
            year_avg = finals[3]
        elif len(finals) == 3:
            h2_avg = finals[1]
            year_avg = finals[2]
        elif len(finals) == 2:
            h2_avg = finals[1]
            year_avg = None
        else:
            h2_avg = None
            year_avg = None
        s1 = p1.get(subject, {})
        s2 = p2.get(subject, {})
        subjects[subject] = {
            "H1Exams": s1.get("tests", []),
            "H1Grades": s1.get("grades", []),
            "H1GradesAverage": s1.get("grades_average"),
            "H1Average": h1_avg,
            "H2Exams": s2.get("tests", []),
            "H2Grades": s2.get("grades", []),
            "H2GradesAverage": s2.get("grades_average"),
            "H2Average": h2_avg,
            "YearAverage": year_avg,
        }

    final_container = soup.find("div", id=re.compile("student_final_grades_container"))
    if final_container:
        ftbl = final_container.find("table")
        if ftbl and ftbl.tbody:
            for row in ftbl.tbody.find_all("tr"):
                cells = _iter_cells(row)
                if not cells:
                    continue
                subject = cells[0].get_text(strip=True)
                grade_cells = [td for td in cells[1:] if "display_final_grade" in td.get("class", [])]

                def parse_int_cell(td):
                    text = td.get_text(strip=True)
                    return int(text) if text.isdigit() else None

                h1_final = parse_int_cell(grade_cells[0]) if len(grade_cells) >= 1 else None
                h2_final = parse_int_cell(grade_cells[1]) if len(grade_cells) >= 2 else None
                # Keep backward compatibility: FinalGrade is last available entry
                final_grade = h2_final if h2_final is not None else h1_final

                if subject in subjects:
                    subjects[subject]["H1FinalGrade"] = h1_final
                    subjects[subject]["H2FinalGrade"] = h2_final
                    subjects[subject]["FinalGrade"] = final_grade
                else:
                    subjects[subject] = {
                        "H1Exams": [],
                        "H1Grades": [],
                        "H1GradesAverage": None,
                        "H1Average": None,
                        "H2Exams": [],
                        "H2Grades": [],
                        "H2GradesAverage": None,
                        "H2Average": None,
                        "YearAverage": None,
                        "H1FinalGrade": h1_final,
                        "H2FinalGrade": h2_final,
                        "FinalGrade": final_grade,
                    }

    return {"N1": n1, "N2": n2, "FinalAverage": final, "subjects": subjects}



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

            messages = []
            old_info_all = old_data.get(user["name"], {})
            for subject, info in data.get("subjects", {}).items():
                old_info = old_info_all.get("subjects", {}).get(subject, {})
                for sem in ["H1Grades", "H2Grades", "H1Exams", "H2Exams"]:
                    new_list = info.get(sem, [])
                    old_list = old_info.get(sem, [])
                    for grade in new_list[len(old_list):]:
                        prefix = "Klassenarbeitsnote" if sem.endswith("Exams") else "Note"
                        messages.append(
                            f"[{user['name']}] Neue {prefix} in {subject} ({sem[:2]}): {grade}"
                        )
                for key, label in [("H1FinalGrade", "HJ1"), ("H2FinalGrade", "HJ2")]:
                    new_final = info.get(key)
                    if new_final is not None and new_final != old_info.get(key):
                        messages.append(
                            f"[{user['name']}] Zeugnisnote ({label}) in {subject} steht fest: {new_final}"
                        )

            if messages:
                url = f"https://discord.com/api/channels/{DISCORD_CHANNEL_ID}/messages"
                headers = {
                    "Authorization": f"Bot {DISCORD_TOKEN}",
                    "Content-Type": "application/json",
                }
                for msg in messages:
                    payload = {"content": msg}
                    try:
                        res = requests.post(url, headers=headers, json=payload)
                        if 200 <= res.status_code < 300:
                            logging.info(f"Nachricht an Discord gesendet: {msg}")
                        else:
                            logging.error(
                                f"Discord-API-Fehler ({res.status_code}): {res.text}"
                            )
                    except Exception as e:
                        logging.error(f"Fehler beim Senden an Discord: {e}")
                    time.sleep(0.5)
            else:
                logging.info(f"Keine neuen Noten gefunden f\xC3\xBCr {user['name']}.")

            safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", user["name"])
            with open(f"grades_{safe_name}.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            old_data[user["name"]] = data
            with open(f"old_grades_{safe_name}.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        time.sleep(INTERVAL_MINUTES * 60)
