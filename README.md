# Fux Noten Checker

Dieses Skript ruft regelmäßig Noten aus dem Fux Elternportal ab und sendet neue Einträge an einen Discord-Channel. 

## Nutzung
1. Lege eine `.env` Datei im gleichen Verzeichnis an. Für jeden Benutzer legst
   du die Variablen `USER<n>`, `USERNAME<n>` und `PASSWORD<n>` an. Ein Beispiel
   für zwei Benutzer sieht so aus:
    ```
    USER1=NAME
    USERNAME1=<Benutzername1>
    PASSWORD1=<Passwort1>

    USER2=NAME
    USERNAME2=<Benutzername2>
    PASSWORD2=<Passwort2>

    DISCORD_TOKEN=<Bot-Token>
    DISCORD_CHANNEL_ID=<Channel-ID>
    INTERVAL_MINUTES=5
    # Set SHOW_RES=true to include HTML responses in the log
    SHOW_RES=false
    # Set SHOW_HTTPS=true to log HTTP requests with credentials
    SHOW_HTTPS=false
    # Fetch grades from a local web server instead of logging in
    # USERNAMEn and PASSWORDn become optional when enabled
    DEBUG_LOCAL=false
   ```
2. Installiere die Abhängigkeiten:
   ```bash
   pip install -r requirements.txt
   ```
3. Starte das Skript:
   ```bash
   python3 main.py
   ```
   Ist `DEBUG_LOCAL=true` gesetzt, ruft das Skript die Datei
   `http://localhost:8000/index.html` ab und verzichtet auf den Login.

 Das Skript legt f\xC3\xBCr jeden Benutzer eine Datei `grades_<Name>.json` mit den aktuellen Noten an und protokolliert Ereignisse in `noten_checker.log`.
 Neue Klassenarbeitsnoten werden gesondert mit dem Hinweis "Klassenarbeitsnote" in Discord gemeldet.

## Tests

Im Verzeichnis `tests` befinden sich automatisierte Tests auf Basis von
`pytest`. Beim Ausf\xC3\xBChren wird ein lokaler Webserver gestartet, der die
`index.html` bereitstellt. Die Tests rufen die Noten von dort ab, simulieren
\xC3\x84nderungen und pr\xC3\xBCfen die erzeugten Discord-Nachrichten.

Zum Starten der Tests:

```bash
pytest -q
```
