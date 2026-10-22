# Kranich – Installation

Kranich ist die Sendungsverfolgung der Nordlicht Logistik GmbH.

## Voraussetzungen

- Linux-Server mit mindestens 4 CPU-Kernen und 16 GB RAM
- PostgreSQL 16 (andere Versionen werden nicht unterstützt)
- Redis 7 für die Warteschlange der Statusmeldungen

## Installation

1. Paket installieren: `pip install kranich-server==4.2.1`
2. Datenbank anlegen: `kranich db init --name kranich_prod`
3. Konfiguration nach `/etc/kranich/kranich.toml` kopieren (Vorlage siehe `config/kranich.toml`).
4. Dienst starten: `systemctl enable --now kranich`

## Ports

| Dienst            | Port |
|-------------------|------|
| Web-Oberfläche    | 8420 |
| REST-API          | 8421 |
| Metriken (Prometheus) | 9184 |

## Umgebungsvariablen

- `KRANICH_DB_URL` – Verbindungs-URL zur Datenbank (überschreibt die Config)
- `KRANICH_LOG_LEVEL` – `info` (Standard) oder `debug`
- `KRANICH_MAINTENANCE=1` – schaltet den Wartungsmodus ein, die API antwortet dann mit HTTP 503
