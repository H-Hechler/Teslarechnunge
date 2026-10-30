# Supercharger-Rechnungen

Lädt verfügbare Rechnungs-PDFs über die offizielle Tesla Fleet API. Alle Seiten und alle Rechnungen eines Ladevorgangs werden verarbeitet. Vorhandene PDFs werden übersprungen. Es werden keine Fahrzeugbefehle gesendet.

## Einmalige Vorbereitung

1. Im [Tesla-Entwicklerportal](https://developer.tesla.com/) eine Anwendung erstellen. Die Einrichtung einschließlich gegebenenfalls regionaler Partner-Registrierung gemäß Portal-Anweisungen abschließen. API-Zugang und gegebenenfalls Abrechnung freischalten; mögliche Kosten im Portal prüfen.
2. OAuth Authorization Code aktivieren. Erlaubten Ursprung `http://localhost:8585` und exakte Redirect-URI `http://localhost:8585/callback` eintragen. Falls das Portal diese lokale URI für deine Anwendung nicht zulässt, ist diese Konfiguration dort nicht nutzbar.
3. „Vehicle Charging Management“ (`vehicle_charging_cmds`) freigeben. Das Programm benötigt zusätzlich `openid` und `offline_access`. Tesla bündelt Ladehistorie und Ladebefehle in dieser Berechtigung; dieses Programm verwendet nur lesende Endpunkte.
4. Client-ID und Client-Secret bereithalten. Diese gehören zur Entwickler-Anwendung, nicht zum Tesla-Benutzerkonto.
5. Im PyCharm-Terminal installieren:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Start

`main.py` in PyCharm ausführen oder:

```powershell
.\.venv\Scripts\python.exe main.py
```

Beim ersten Start Client-ID und verdeckt Client-Secret eingeben. Für Deutschland `EU` wählen. Anschließend öffnet sich die Tesla-Anmeldeseite im Browser: anmelden und Zugriff erlauben. Port 8585 muss frei sein; die Anmeldung wartet maximal fünf Minuten.

Die PDFs landen im Projektordner `Rechnungen`. Stabile Dateinamen aus der Rechnungs-ID vermeiden doppelte Downloads und enthalten keine Fahrzeugdaten. Secret und Zugangstoken liegen über `keyring` in der Windows-Anmeldeverwaltung; `config.json` enthält nur Client-ID und Region. Zwei Instanzen nicht gleichzeitig starten, weil Tesla Refresh-Token rotiert.

## Automatischer Abruf

```powershell
.\.venv\Scripts\python.exe main.py --interval 60
```

Prüft stündlich, solange Programm und Rechner laufen. Beenden mit Strg+C. Nach einem Fehler stoppt das Programm mit Fehlercode 1. Ein erneuter Start versucht fehlende Rechnungen nochmals. Ohne `--interval` eignet sich der Aufruf für die Windows-Aufgabenplanung unter demselben Windows-Benutzer nach einmaliger interaktiver Anmeldung.

Weitere Optionen:

```powershell
.\.venv\Scripts\python.exe main.py --login
.\.venv\Scripts\python.exe main.py --setup
.\.venv\Scripts\python.exe main.py --output "D:\Tesla-Rechnungen" --vin DEINE_FIN
```

`--login` erneuert die Anmeldung; `--setup` ersetzt die Einrichtung. Keine Passwörter in den Quelltext schreiben. Ladevorgänge ohne verfügbare Rechnung werden gezählt und später erneut geprüft.

## Grenzen und Quellen

Der echte Abruf erfordert deine freigeschaltete Entwickler-Anwendung und Anmeldung. Ohne diese Daten lässt sich nur das lokale Programmverhalten prüfen. Tesla dokumentiert die Endpunkte, aber nicht alle Antwortdetails auf der öffentlich lesbaren Dokumentationsseite. Unbekannte Historienformate und wiederholte Seiten führen deshalb zu einer sichtbaren Fehlermeldung.

- [Tesla: Charging Endpoints](https://developer.tesla.com/docs/fleet-api/endpoints/charging-endpoints)
- [Tesla: OAuth und Token-Erneuerung](https://developer.tesla.com/docs/fleet-api/authentication/third-party-tokens)
- [Tesla: Berechtigungen](https://developer.tesla.com/docs/fleet-api/authentication/overview)
