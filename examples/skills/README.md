# Beispiel-Skills

Sechs kleine Mini-Skills nach den Faustregeln aus der CLAUDE.md (9.1): eine Aufgabe je Skill,
nummerierte Schritte, „Nicht tun“, ein kurzes Beispiel.

| Skill | Aufgabe | Schränkt Tools ein | checks |
|---|---|---|---|
| `pytest-test` | pytest-Tests für eine Funktion schreiben | ja | `python -m pytest -q {test_file}` |
| `changelog-eintrag` | Eintrag in `CHANGELOG.md` (Keep a Changelog) | ja | – |
| `commit-nachricht` | Commit-Nachricht aus `git diff` formulieren, **ohne** etwas zu ändern | nur `run_shell`, `read_file` | – |
| `docstrings-ergaenzen` | fehlende Docstrings ergänzen, Logik unverändert | ja | – |
| `fehler-analysieren` | Ursache eines Tracebacks finden und minimal beheben | ja | – |
| `abap-unit-test` | lokale ABAP-Unit-Testklasse anlegen | ja | – (kein ABAP-System) |

## Benutzen

**In einem eigenen Projekt:** Ordner nach `.lcc/skills/` (Projekt) oder `~/.config/lcc/skills/`
(für alle Projekte) kopieren:

```bash
mkdir -p .lcc/skills && cp -r /work/examples/skills/*/ .lcc/skills/
lcc skills check
lcc skills match "schreib Tests für slugify"
```

**Direkt hier im Repo:**

```bash
lcc --config examples/skills/lcc.toml skills
lcc --config examples/skills/lcc.toml skills match "Ich bekomme einen TypeError"
```

## Beispielaufträge und erwartete Auswahl

Geprüft mit `bge-m3` (Scores können je Modell leicht abweichen).

| Auftrag | Auswahl | Grund |
|---|---|---|
| schreib Tests für slugify | `pytest-test` (auto) | Trigger `tests` |
| trag die neue CSV-Funktion ins Changelog ein | `changelog-eintrag` (auto) | Trigger `changelog` |
| Was wäre eine gute Commit-Nachricht für meine Änderungen? | `commit-nachricht` (auto) | Trigger |
| Ich bekomme einen TypeError beim Aufruf von preis() | `fehler-analysieren` (auto) | Trigger `typeerror` |
| Schreib eine ABAP-Unit-Testklasse für zcl_kranich_status | `abap-unit-test` (auto) | Trigger `abap-unit` |
| Die Funktionen in tarife.py brauchen Beschreibungen | `docstrings-ergaenzen` gelistet (0.53) | nur Ähnlichkeit – knapp unter `auto_load_min_score` 0.55, das Modell kann ihn per `load_skill` holen |
| Was ist die Hauptstadt von Frankreich? | nichts automatisch | alle Scores < 0.25 |

Zum Ausprobieren der Aufträge passen die RAG-Beispiele aus `examples/rag/docs/code/`
(`tarife.py`, `zcl_kranich_status.abap`).

## Hinweise

- **checks und Allowlist:** Checks laufen über die Sandbox. Steht der Befehl nicht in
  `agent.shell_allowlist`, fragt lcc nach – ohne Terminal (z. B. `lcc run` in Skripten) wird er
  abgelehnt und der Check gilt als fehlgeschlagen. Deshalb nutzen die Beispiele nur
  `python -m pytest`, das in der Default-Allowlist steht.
- **Trigger:** Wortgrenzen beachten – `test` trifft nicht „Tests“. Haben mehrere Skills einen
  Trigger-Treffer, entscheidet die Ähnlichkeit der Beschreibung.
- **Prüfen:** `lcc skills check` vor dem Einsatz; `lcc skills match "…"` zeigt Score und Grund.
