import os
import time
import json
import logging
import re
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Konfiguration aus .env laden
# .env-Datei einlesen
load_dotenv()
USERNAME = os.getenv("USERNAME")
PASSWORD = os.getenv("PASSWORD")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")
INTERVAL_MINUTES = int(os.getenv("INTERVAL_MINUTES", "5"))


def check_env():
    """Ensure all required environment variables are present."""
    required = {
        "USERNAME": USERNAME,
        "PASSWORD": PASSWORD,
        "DISCORD_TOKEN": DISCORD_TOKEN,
        "DISCORD_CHANNEL_ID": DISCORD_CHANNEL_ID,
    }
    missing = [key for key, value in required.items() if not value]
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


def _parse_semester_table(table):
    """Return dict of subject -> (grades list, average) for a semester table."""
    result = {}
    if not table:
        return result
    for row in table.tbody.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        subject = cells[0].get_text(strip=True)
        grades = []
        avg = None
        for td in cells[1:]:
            classes = td.get("class", [])
            text = td.get_text(strip=True)
            if "final_average" in classes:
                if text:
                    try:
                        avg = float(text.replace(",", "."))
                    except ValueError:
                        pass
            else:
                if text:
                    grades.append(text)
        result[subject] = {"grades": grades, "average": avg}
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
        tds = row.find_all("td")
        if not tds:
            continue
        subject = tds[0].get_text(strip=True)
        finals = row.find_all("td", class_="final_average")
        h1_avg = float(finals[0].get_text(strip=True).replace(",", ".")) if len(finals) > 0 else None
        h2_avg = float(finals[1].get_text(strip=True).replace(",", ".")) if len(finals) > 1 else None
        year_avg = float(finals[2].get_text(strip=True).replace(",", ".")) if len(finals) > 2 else None
        subjects[subject] = {
            "H1Grades": p1.get(subject, {}).get("grades", []),
            "H1Average": h1_avg,
            "H2Grades": p2.get(subject, {}).get("grades", []),
            "H2Average": h2_avg,
            "YearAverage": year_avg,
        }

    final_container = soup.find("div", id=re.compile("student_final_grades_container"))
    if final_container:
        ftbl = final_container.find("table")
        if ftbl and ftbl.tbody:
            for row in ftbl.tbody.find_all("tr"):
                cells = row.find_all("td")
                if not cells:
                    continue
                subject = cells[0].get_text(strip=True)
                grade_cells = [td for td in cells[1:] if "display_final_grade" in td.get("class", [])]
                final_grade = None
                if grade_cells:
                    text = grade_cells[-1].get_text(strip=True)
                    if text.isdigit():
                        final_grade = int(text)
                if subject in subjects:
                    subjects[subject]["FinalGrade"] = final_grade
                else:
                    subjects[subject] = {
                        "H1Grades": [],
                        "H1Average": None,
                        "H2Grades": [],
                        "H2Average": None,
                        "YearAverage": None,
                        "FinalGrade": final_grade,
                    }

    return {"N1": n1, "N2": n2, "FinalAverage": final, "subjects": subjects}


def _read_local_html():
    """Fallback: read HTML from req.txt if available."""
    try:
        with open("req.txt", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logging.error(f"Lokale req.txt konnte nicht gelesen werden: {e}")
        return None

# Datei für gespeicherte Notenstände
DATA_FILE = "old_grades.json"

# Bereits gemeldete Noten laden (wenn Datei existiert)
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        old_data = json.load(f)
else:
    old_data = {}


def fetch_html():
    """Meldet sich im Elternportal an und gibt den HTML-Quelltext zurück."""
    session = requests.Session()

    # Schritt 1: Login-Seite abrufen, um Nonce und versteckte Felder zu erhalten
    login_url = "https://100308.fuxnoten.online/webinfo"
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "Referer": login_url,
        }
    )
    try:
        login_page = session.get(login_url)
    except Exception as e:
        logging.error(f"Login-Seite nicht erreichbar: {e}")
        return _read_local_html()
    logging.info(
        "Login-Seite Response (%s): %s",
        login_page.status_code,
        login_page.text,
    )

    soup = BeautifulSoup(login_page.text, "html.parser")
    nonce_field = soup.find("input", {"name": "_nonce"})
    f_secure_field = soup.find("input", {"name": "_f_secure"})
    nonce = nonce_field["value"] if nonce_field else ""
    f_secure = f_secure_field["value"] if f_secure_field else ""

    payload = {
        "user": USERNAME,
        "password": PASSWORD,
        "fuxnoten_post_controller": "\\Objects\\Webinfo_Object",
        "acount_action": "login",
        "_referrer": "https://100308.fuxnoten.online/webinfo/",
        "_nonce": nonce,
        "_f_secure": f_secure,
    }

    # Schritt 2: Login-POST mit allen erforderlichen Feldern
    try:
        resp = session.post(login_url, data=payload, allow_redirects=True)
    except Exception as e:
        logging.error(f"Login-Request fehlgeschlagen: {e}")
        return _read_local_html()
    logging.info(
        "Login-POST Response (%s): %s",
        resp.status_code,
        resp.text,
    )

    # Prüfen, ob Login erfolgreich war (Seite sollte kein Login-Formular mehr enthalten)
    if resp.status_code != 200 or 'name="user"' in resp.text:
        logging.error("Login fehlgeschlagen – Status %s", resp.status_code)
        return _read_local_html()

    # Notenübersicht abrufen (nach erfolgreichem Login)
    try:
        grades_page = session.get(
            "https://100308.fuxnoten.online/webinfo/account/"
        )
    except Exception as e:
        logging.error(f"Fehler beim Abrufen der Notenübersicht: {e}")
        return _read_local_html()
    logging.info(
        "Notenübersicht Response (%s): %s",
        grades_page.status_code,
        grades_page.text,
    )

    return grades_page.text


if __name__ == "__main__":
    # Hauptschleife: regelmäßige Prüfung im konfigurierten Intervall
    logging.info("Noten-Checker gestartet. Warte auf neue Noten...")
    while True:
        html = fetch_html()
        if html is None:
            # Fehler beim Abrufen – später erneut versuchen
            time.sleep(INTERVAL_MINUTES * 60)
            continue

        data = parse_grades(html)

        messages = []
        for subject, info in data.get("subjects", {}).items():
            old_info = old_data.get("subjects", {}).get(subject, {})
            for sem in ["H1Grades", "H2Grades"]:
                new_list = info.get(sem, [])
                old_list = old_info.get(sem, [])
                for grade in new_list[len(old_list):]:
                    messages.append(f"Neue Note in {subject} ({sem[:2]}): {grade}")
            new_final = info.get("FinalGrade")
            if new_final is not None and new_final != old_info.get("FinalGrade"):
                messages.append(f"Zeugnisnote in {subject} steht fest: {new_final}")

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
        else:
            logging.info("Keine neuen Noten gefunden.")

        # Ergebnisse speichern
        with open("grades.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        old_data = data
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(old_data, f, indent=2, ensure_ascii=False)

        time.sleep(INTERVAL_MINUTES * 60)
