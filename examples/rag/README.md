# RAG-Beispiele: „Kranich“ (Nordlicht Logistik)

Erfundene Dokumentation einer Sendungsverfolgung. Alle Fakten sind ausgedacht – ein Modell
kann sie nur über RAG kennen. So sieht man sofort, ob die Suche greift.

Gemischte Dateitypen, wie in `rag.include`: Markdown, Text, Python, ABAP, TOML und ein
englisches Dokument (prüft, ob deutsche Fragen englische Texte finden).

## Ausprobieren

**Variante A – in einem eigenen Ordner (empfohlen):** `docs/` in ein Projekt kopieren, dort gilt
der Default `rag.sources = ["./docs"]`:

```bash
cp -r docs ~/lcc-spielwiese/
cd ~/lcc-spielwiese
lcc rag index
lcc rag search "Wer gibt Deployments frei?"
lcc ask "Wann darf Kranich ausgerollt werden und wer gibt frei?"
```

**Variante B – direkt hier im Repo** über die mitgelieferte Config:

```bash
lcc --config examples/rag/lcc.toml rag index
lcc --config examples/rag/lcc.toml ask "Wie lange werden Backups aufbewahrt?"
```

## Testfragen und erwartete Antworten

| Frage | Erwartet | Quelle |
|---|---|---|
| Wann darf Kranich ausgerollt werden und wer gibt frei? | mittwochs 6–8 Uhr, Tobias Reinhardt (Vertretung Aylin Demir) | `handbuch/betrieb.md` |
| Wann wechselt die Rufbereitschaft und wer kommt nach Aylin? | freitags 12 Uhr, danach Malte Krüger | `handbuch/betrieb.md` |
| Wie lange werden Backups aufbewahrt? | 35 Tage | `handbuch/betrieb.md` |
| Auf welchem Port läuft die REST-API? | 8421 | `handbuch/installation.md` |
| Welche PostgreSQL-Version braucht Kranich? | nur PostgreSQL 16 | `handbuch/installation.md` |
| Wie schalte ich den Wartungsmodus ein? | `KRANICH_MAINTENANCE=1`, API antwortet mit 503 | `handbuch/installation.md` |
| Was kostet eine Expresssendung mit 2 kg? | 4,90 + 2 × 0,85 + 9,90 = 16,50 € | `code/tarife.py` |
| Ab welchem Gewicht wird eine Sendung abgelehnt? | über 31,5 kg | `code/tarife.py` |
| Welchen SAP-Status bekommt eine Sendung im Hub? | `UT` (unterwegs) | `code/zcl_kranich_status.abap` |
| Nach wie vielen Zustellversuchen geht ein Paket zurück? | nach drei | `glossar.md` |
| Ab wann warnt Kranich wegen Liegezeit? | ab 48 Stunden | `glossar.md`, `config/kranich.toml` |
| Wie lange ist ein API-Schlüssel gültig? | 365 Tage | `english/api.md` (englisch!) |
| Kann ich eine Sendung an einen Abholpunkt umleiten? | ja, aber nur vor dem ersten Zustellversuch | `english/api.md` |
| Wie viele Scans schafft ein Verarbeiter pro Sekunde? | etwa 400 | `architektur.md` |
| Warum steht eine Sendung auf „unbekannt“? | seit über 7 Tagen kein Scan | `faq.txt` |

Fragen ohne Treffer zum Gegencheck: „Wie heißt der Hund von Tobias?“ – hier soll das Modell
sagen, dass es dazu nichts in der Dokumentation gibt.
