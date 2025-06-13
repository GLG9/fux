# Fux Noten Checker

Dieses Skript ruft regelmäßig Noten aus dem Fux Elternportal ab und sendet neue Einträge an einen Discord-Channel. 

## Nutzung
1. Lege eine `.env` Datei im gleichen Verzeichnis an und fülle sie mit folgenden Variablen:
   ```
   USERNAME=<Benutzername>
   PASSWORD=<Passwort>
   DISCORD_TOKEN=<Bot-Token>
   DISCORD_CHANNEL_ID=<Channel-ID>
   INTERVAL_MINUTES=5
   # Set SHOW_RES=true to omit HTML responses from the log
   SHOW_RES=false
   ```
2. Installiere die Abhängigkeiten:
   ```bash
   pip install -r requirements.txt
   ```
3. Starte das Skript:
   ```bash
   python3 main.py
   ```

Das Skript protokolliert Ereignisse in `noten_checker.log`.
