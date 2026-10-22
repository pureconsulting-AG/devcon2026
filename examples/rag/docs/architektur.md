# Architektur von Kranich

Kranich besteht aus vier Komponenten:

## Erfasser
Nimmt Scans der Handscanner entgegen (MQTT, Topic `scans/+/raw`) und schreibt sie
in die Redis-Warteschlange `kranich:eingang`.

## Verarbeiter
Liest die Warteschlange, ordnet Scans einer Sendung zu und berechnet den Status.
Läuft in 3 Instanzen; jede verarbeitet etwa 400 Scans pro Sekunde.

## API
REST-Schnittstelle für Kunden und Partner. Authentifizierung über API-Schlüssel
im Header `X-Kranich-Key`. Ratenlimit: 120 Anfragen pro Minute und Schlüssel.

## SAP-Anbindung
Statusänderungen werden stündlich an SAP gemeldet. Die Zuordnung der Statuscodes
erledigt die ABAP-Klasse `ZCL_KRANICH_STATUS` (siehe `code/zcl_kranich_status.abap`).
