import os
import time
import json
import logging
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

# Datei für gespeicherte Notenstände
DATA_FILE = "old_grades.json"

# Bereits gemeldete Noten laden (wenn Datei existiert)
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        data = json.load(f)
        old_grades = data.get("grades", [])
else:
    old_grades = []
    # Initial eine leere Struktur anlegen
    with open(DATA_FILE, "w") as f:
        json.dump({"grades": []}, f)


def fetch_grades():
    """Meldet sich im Elternportal an und gibt die aktuelle Notenliste zurück."""
    session = (
        requests.Session()
    )  # Session-Objekt für persistente Cookies verwenden

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
        return None
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
        "_refferer": "https://100308.fuxnoten.online/webinfo/",
        "_nonce": nonce,
        "_f_secure": f_secure,
    }

    # Schritt 2: Login-POST mit allen erforderlichen Feldern
    try:
        resp = session.post(login_url, data=payload, allow_redirects=True)
    except Exception as e:
        logging.error(f"Login-Request fehlgeschlagen: {e}")
        return None
    logging.info(
        "Login-POST Response (%s): %s",
        resp.status_code,
        resp.text,
    )

    # Prüfen, ob Login erfolgreich war (Seite sollte kein Login-Formular mehr enthalten)
    if resp.status_code != 200 or 'name="user"' in resp.text:
        logging.error("Login fehlgeschlagen – Status %s", resp.status_code)
        return None

    # Notenübersicht abrufen (nach erfolgreichem Login)
    try:
        grades_page = session.get(
            "https://100308.fuxnoten.online/webinfo/account/"
        )
    except Exception as e:
        logging.error(f"Fehler beim Abrufen der Notenübersicht: {e}")
        return None
    logging.info(
        "Notenübersicht Response (%s): %s",
        grades_page.status_code,
        grades_page.text,
    )
    # HTML mit BeautifulSoup parsen
    soup = BeautifulSoup(grades_page.text, "html.parser")
    grades = []
    # Notenliste aus HTML extrahieren (an Seitenstruktur anpassen)
    for row in soup.find_all("tr"):
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if not cells:
            continue
        # Annahme: Eine der Zellen enthält die Note (Ziffer 1-6 evtl. mit +/–)
        for val in cells:
            if val and val[0].isdigit() and val[0] in "123456":
                subject = cells[0]  # Fach (ersten Spalte angenommen)
                grade_value = val  # Notenwert
                grades.append({"subject": subject, "grade": grade_value})
                break
    return grades


# Hauptschleife: regelmäßige Prüfung im konfigurierten Intervall
logging.info("Noten-Checker gestartet. Warte auf neue Noten...")
while True:
    current_grades = fetch_grades()
    if current_grades is None:
        # bei Fehler (Login fehlgeschlagen oder Seitenabruf-Problem) nächsten Versuch später
        time.sleep(INTERVAL_MINUTES * 60)
        continue
    # Neue Noten ermitteln (aktueller Stand minus bereits gemeldeter Stand)
    new_entries = [g for g in current_grades if g not in old_grades]
    if new_entries:
        for grade in new_entries:
            subj = grade["subject"]
            val = grade["grade"]
            message = f"Du hast eine {val} in {subj} bekommen!"
            # Discord-Benachrichtigung senden über Bot-Token
            url = f"https://discord.com/api/channels/{DISCORD_CHANNEL_ID}/messages"
            headers = {
                "Authorization": f"Bot {DISCORD_TOKEN}",
                "Content-Type": "application/json",
            }
            payload = {"content": message}
            try:
                res = requests.post(
                    url, headers=headers, json=payload
                )  # HTTP-POST an Discord API
                if 200 <= res.status_code < 300:
                    logging.info(
                        f"Neue Note gefunden: {subj} {val} – Nachricht an Discord gesendet."
                    )
                else:
                    logging.error(
                        f"Discord-API-Fehler ({res.status_code}): {res.text}"
                    )
            except Exception as e:
                logging.error(f"Fehler beim Senden an Discord: {e}")
        # Aktualisierte Notenliste in JSON-Datei speichern
        old_grades = current_grades
        with open(DATA_FILE, "w") as f:
            json.dump({"grades": old_grades}, f, indent=4)
    else:
        logging.info("Keine neuen Noten gefunden.")
    # Warten bis zum nächsten Intervall
    time.sleep(INTERVAL_MINUTES * 60)
