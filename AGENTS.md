# AGENTS

Dieses Projekt ist ein **Fux Noten Checker**. Das Python-Skript ruft regelmäßig Noten aus dem Fux Elternportal ab und sendet neue Einträge an einen Discord-Channel.

## Projektstruktur
- `main.py` enthält die Logik zum Abrufen und Parsen der Noten sowie zum Versenden von Nachrichten.
- `index.html` und `res_example.txt` stellen Beispielantworten dar und werden in den Tests verwendet.
- Die automatisierten Tests liegen im Verzeichnis `tests`.

## Konfiguration
- Erstelle eine `.env` Datei im Projektverzeichnis.
- Für jeden Benutzer definierst du `USERn`, `USERNAMEn` und `PASSWORDn`.
- Zusätzlich benötigst du folgende Variablen:
  - `DISCORD_TOKEN`: Bot-Token des Discord-Bots
  - `DISCORD_CHANNEL_ID`: Channel-ID, in dem die Nachrichten landen
  - `INTERVAL_MINUTES`: (optional) Intervall für die Abfragen, Standard 5
  - `SHOW_RES`: (optional) HTML-Responses im Log speichern
  - `SHOW_HTTPS`: (optional) HTTP-Requests mit Zugangsdaten protokollieren
  - `SHOW_YEAR_AVERAGE`: (optional) Jahresdurchschnitt in Benachrichtigungen aufnehmen
  - `DEBUG_LOCAL`: (optional) Daten aus `index.html` lesen und keinen Login durchführen

## Nutzung
1. Installiere die Abhängigkeiten:
   ```bash
   pip install -r requirements.txt
   ```
2. Starte das Skript:
   ```bash
   python3 main.py
   ```
   Mit `DEBUG_LOCAL=true` wird `http://localhost:8000/index.html` verwendet.
3. Für jeden Benutzer wird `grades_<Name>.json` erzeugt. Ereignisse landen in `noten_checker.log`.

## Tests
- Die Tests basieren auf `pytest` und starten einen lokalen Webserver.
- Führe sie mit folgendem Befehl aus:
  ```bash
  pytest -q
  ```