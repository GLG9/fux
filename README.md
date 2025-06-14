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

## Tests

Automatische Tests befinden sich im Ordner `tests`. Sie starten einen lokalen
HTTP‑Server auf Port `8000`, um die bereitgestellte `index.html` zu laden. Die
Tests prüfen die Notenparsing‑Funktion sowie das Versenden der Discord‑Nachrichten
bei neuen oder unveränderten Noten.

Installiere zunächst die Abhängigkeiten inklusive `pytest` und führe dann alle
Tests mit:

```bash
pytest
```
