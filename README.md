# lcc – local code cli

Eine Coding-CLI, die **ausschließlich** mit einem lokalen Ollama-Server arbeitet – kein
Cloud-Modell, keine API-Keys, keine Telemetrie. lcc liest, sucht und ändert Dateien in deinem
Projekt, führt (bestätigte) Shell-Befehle aus, durchsucht deine Dokumentation (RAG) und lädt
kleine, fokussierte Anleitungen (Skills) genau dann, wenn sie gebraucht werden.

lcc ist auf **kleine Modelle** wie `qwen3.5:9b` ausgelegt: Statt langer Prompts gleicht lcc ihre
Schwächen durch Struktur aus – Plan, Schritte mit wenigen Tools, Auto-Kontext, Prüfung und
Reparatur (siehe [Kleinmodell-Modus](#kleinmodell-modus)).

**Neu hier?** Das [Tutorial](TUTORIAL.md) führt Schritt für Schritt durch alle Funktionen –
mit einem Übungsprojekt zum Mitmachen.

---

## Inhalt

- [Installation](#installation)
- [Schnellstart](#schnellstart)
- [Befehle](#befehle)
- [Interaktiver Modus (REPL)](#interaktiver-modus-repl)
- [Konfiguration](#konfiguration)
- [Sicherheit: Sandbox, Bestätigungen, Undo](#sicherheit-sandbox-bestätigungen-undo)
- [RAG: Dokumentation durchsuchen](#rag-dokumentation-durchsuchen)
- [Skills](#skills)
- [Eigene Skills schreiben](#eigene-skills-schreiben)
- [Kleinmodell-Modus](#kleinmodell-modus)
- [Skripte und Pipelines (`--json`)](#skripte-und-pipelines---json)
- [Beispiele zum Ausprobieren](#beispiele-zum-ausprobieren)
- [Entwicklung](#entwicklung)

---

## Installation

Voraussetzungen: Python ≥ 3.12 und ein erreichbarer Ollama-Server (Default
`http://192.168.178.79:11434`) mit einem Chat-/Code-Modell und einem Embedding-Modell:

```bash
# auf dem Ollama-Server
ollama pull qwen3.5:9b
ollama pull bge-m3
```

lcc installieren:

```bash
pip install -e .            # im Repo, z. B. in einer venv
# oder für alle Shells:
pipx install -e /pfad/zu/lcc
```

Prüfen, ob alles passt:

```bash
lcc doctor
```

```
✓ Server: http://192.168.178.79:11434 erreichbar, 14 Modelle
✓ Modell qwen3.5:9b (code, chat): 9.7B
✓ Modell bge-m3 (embed): 566.70M
✓ Tool-Calling (qwen3.5:9b): native tool_calls funktionieren
✓ Embedding (bge-m3): Dimension 1024
┏━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┓
┃ Modell     ┃ Rollen     ┃ Größe   ┃ Tools ┃ Thinking ┃ Kleinmodell-Modus ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━┩
│ qwen3.5:9b │ code, chat │ 9.7B    │ ja    │ ja       │ ja                │
│ bge-m3     │ embed      │ 566.70M │ nein  │ nein     │ –                 │
└────────────┴────────────┴─────────┴───────┴──────────┴───────────────────┘
```

Anderer Server? `lcc config init` legt `~/.config/lcc/config.toml` an – dort `base_url` und die
Modellnamen anpassen (oder einmalig `--url` / `LCC_OLLAMA_URL`).

---

## Schnellstart

```bash
cd mein-projekt

# Eine Frage ohne Tools
lcc ask "Was ist der Unterschied zwischen git merge und git rebase?"
cat utils.py | lcc ask "Erkläre diese Datei"

# Ein Auftrag mit Tools (liest, sucht, ändert – mit Diff und Rückfrage)
lcc run "füge in utils.py eine Funktion slugify hinzu und schreibe einen Test"

# Interaktiv
lcc
```

**Tipp:** Probiere lcc zuerst in einem eigenen Ordner mit `git init` aus. lcc arbeitet nur
innerhalb des Projekts (Git-Root bzw. aktueller Ordner), und mit Git siehst du jede Änderung.

---

## Befehle

| Befehl | Zweck |
|---|---|
| `lcc` | interaktiver Modus (REPL) mit Agent |
| `lcc ask "Frage"` | einmalige Antwort **ohne** Tools (Modell `chat`); nutzt RAG, wenn ein Index existiert |
| `lcc run "Auftrag"` | Agent-Lauf mit Tools (Modell `code`) |
| `lcc run --yes "…"` | Schreiben ohne Rückfrage (Shell außerhalb der Allowlist bleibt bestätigungspflichtig) |
| `lcc run --small` / `--no-small` | Kleinmodell-Modus erzwingen / abschalten |
| `lcc undo` | letzte Dateiänderung zurücknehmen (mehrfach möglich) |
| `lcc models` | Modelle auf dem Server; markiert, was die Config nutzt bzw. was fehlt |
| `lcc doctor` | Server, Modelle, Tool-Calling, Embedding-Dimension, Kleinmodell-Modus |
| `lcc rag index [--rebuild]` | Dokumentation indexieren (inkrementell) |
| `lcc rag search "…"` | Treffer mit Score, Datei und Zeilenbereich |
| `lcc rag stats` | Dateien, Chunks, Embedding-Modell, Dimension |
| `lcc skills` | gefundene Skills mit Quelle und Beschreibung |
| `lcc skills show <name>` | Frontmatter und Inhalt eines Skills |
| `lcc skills new <name> [--user]` | Skill-Gerüst anlegen; `--example` legt `pytest-test` an |
| `lcc skills check` | Skills prüfen |
| `lcc skills match "Auftrag"` | welche Skills mit welchem Score und Grund gewählt würden |
| `lcc config show` | effektive Config mit Quelle jedes Werts |
| `lcc config init [--force]` | Beispiel-Config nach `~/.config/lcc/config.toml` |

**Globale Flags** (vor dem Befehl): `--config <datei>`, `--url`, `--model`, `--no-rag`,
`--no-skills`, `--json`, `--show-thinking`, `-v/--verbose`.

**Exit-Codes:** `0` ok · `1` Auftrag nicht erfolgreich (z. B. Checks rot) · `2` Config-Fehler ·
`3` Server nicht erreichbar · `4` Modell fehlt (Hinweis `ollama pull …`) · `130` Abbruch.

---

## Interaktiver Modus (REPL)

```text
$ lcc
lcc – Modell qwen3.5:9b auf http://192.168.178.79:11434. /help zeigt die Befehle, Esc+Enter für neue Zeile.
› Was macht die Funktion preis in tarife.py?
⠹ denkt nach … 4s
→ read_file(path='tarife.py')
  ↳ 28 Zeilen
Die Funktion berechnet …
```

| Befehl | Wirkung |
|---|---|
| `/help`, `/exit` | Hilfe, beenden |
| `/clear` | Verlauf leeren (neue Session) |
| `/model <name>`, `/models` | Modell wechseln, Modelle anzeigen |
| `/add <datei>` | Datei an die nächste Nachricht anhängen (Tab vervollständigt Pfade) |
| `/diff` | alle Änderungen dieser Session |
| `/undo` | letzte Änderung zurücknehmen |
| `/rag <frage>`, `/rag on\|off` | Doku durchsuchen; RAG-Tool an/aus |
| `/skill <name>`, `/skills` | Skill laden; Skills anzeigen (geladene mit ⚙) |
| `/save [name]`, `/load [id]` | Session speichern; laden (ohne id: Liste) |
| `/config` | effektive Config |

**Tasten:** Esc+Enter = neue Zeile · ↑/↓ = Verlauf · Strg-C bricht die laufende Antwort ab
(die Runde wird verworfen) · zweimal Strg-C oder Strg-D beendet.

Sessions werden als JSONL unter `~/.local/state/lcc/sessions/` gespeichert (Ordner nur für dich
lesbar). Thinking-Text wird nie gespeichert.

---

## Konfiguration

lcc liest die Config in dieser Reihenfolge – spätere überschreiben frühere, **Key für Key**:

1. eingebaute Defaults
2. `~/.config/lcc/config.toml` (Benutzer)
3. `./.lcc/config.toml` im Git-Root bzw. aktuellen Ordner (Projekt)
4. `--config <datei>`
5. Umgebung: `LCC_OLLAMA_URL`, `LCC_CODE_MODEL`
6. Flags: `--url`, `--model`

`lcc config show` zeigt jeden Wert mit seiner Quelle:

```toml
[ollama]
base_url = "http://192.168.178.79:11434"  # Default
[models]
code = "qwen3.5:9b"  # /home/dev/.config/lcc/config.toml
```

Alle Keys mit Kommentaren stehen in [`config.example.toml`](config.example.toml). Die wichtigsten:

| Key | Default | Bedeutung |
|---|---|---|
| `ollama.base_url` | `http://192.168.178.79:11434` | der einzige Server, den lcc kontaktiert |
| `models.code` / `models.chat` / `models.embed` | `qwen3.5:9b` / `qwen3.5:9b` / `bge-m3` | Modelle je Rolle |
| `models.options.num_ctx` | `16384` | Kontextgröße; ab ~80 % kürzt lcc alte Tool-Ergebnisse |
| `models.thinking.enabled` | `false` | Thinking an/aus (Anzeige nur mit `--show-thinking`) |
| `agent.shell_allowlist` | `ls`, `cat`, `rg`, `grep`, `git status`, `git diff`, `pytest`, `python -m pytest`, `python -m py_compile` | ohne Rückfrage erlaubte Befehle |
| `agent.max_steps` | `25` | maximale Tool-Runden pro Auftrag |
| `workspace.root` | `.` (Projekt) | Agent liest/schreibt nur hier |
| `rag.sources` | `./docs`, `~/rag-docs` | Quellen für den Index |
| `skills.paths` | `./.lcc/skills`, `~/.config/lcc/skills` | Skill-Ordner (Projekt vor Benutzer) |
| `small_model.mode` | `auto` | `auto` = Modelle ≤ 14 Mrd. Parameter, `on`, `off` |

Relative Pfade gelten relativ zu der Datei, in der sie stehen. Tippfehler in Keys werden als
Warnung mit Vorschlag gemeldet, falsche Typen sind Fehler (Exit 2).

Projektspezifische Regeln für das Modell (z. B. „Nutze immer Typhints“) gehören in
`./.lcc/AGENT.md` – lcc hängt sie an den Systemprompt.

---

## Sicherheit: Sandbox, Bestätigungen, Undo

- **Pfad-Jail:** Der Agent liest und schreibt nur innerhalb von `workspace.root` – auch nicht
  über `..`, absolute Pfade oder Symlinks. In `.git/` wird nie geschrieben.
- **Bestätigungen:** Vor jeder Änderung zeigt lcc einen farbigen Diff:
  `[j]a / [n]ein / [i]mmer für diese Session`. Shell-Befehle außerhalb der Allowlist werden
  ebenfalls bestätigt („immer“ gilt dann nur für genau diesen Befehl).
- **Keine Shell:** Befehle laufen ohne Shell (`shlex`); `ls; rm -rf /` ist harmlos.
- **Ohne Terminal** (Skripte, Pipes): Schreiben nur mit `--yes`, Shell außerhalb der Allowlist
  wird immer abgelehnt – das Modell erfährt den Grund.
- **Undo:** Vor jeder Änderung landet ein Backup in `.lcc/undo/`; `lcc undo` bzw. `/undo` nimmt
  die letzte Änderung zurück, auch aus früheren Läufen. Neu angelegte Dateien werden gelöscht.

---

## RAG: Dokumentation durchsuchen

```bash
lcc rag index                       # Quellen aus rag.sources (Default ./docs, ~/rag-docs)
lcc rag search "Wer gibt Deployments frei?"
lcc ask "Wann darf ausgerollt werden und wer gibt frei?"
```

```
RAG: [1] docs/handbuch/betrieb.md:3-9, [2] docs/faq.txt:1-17
Neue Versionen werden nur mittwochs zwischen 6 und 8 Uhr ausgerollt; die Freigabe erteilt
Tobias Reinhardt [1].
```

- Markdown wird an Überschriften zerlegt, Code an Funktionsgrenzen (auch ABAP), der Rest nach
  Zeichen mit Überlappung. Zeilenbereiche bleiben erhalten.
- Neu indexieren ist inkrementell (nur geänderte Dateien); gelöschte Dateien verschwinden.
- `lcc ask` stellt passende Treffer automatisch vor die Frage; der Agent hat das Tool
  `rag_search`. Quellen werden als `[n]` zitiert.
- Embedding-Modell gewechselt? lcc bricht mit Hinweis ab: `lcc rag index --rebuild`.
- `bge-m3` ist mehrsprachig: deutsche Fragen finden auch englische Dokumente.

---

## Skills

Ein Skill ist eine **kleine Anleitung für genau eine Art von Aufgabe** – z. B. „pytest-Tests
schreiben“ oder „CHANGELOG-Eintrag“. Das Modell sieht zunächst nur Name und Beschreibung; den
Inhalt lädt lcc erst, wenn der Auftrag passt. So bleibt der Kontext klein.

```bash
lcc skills new --example                          # legt .lcc/skills/pytest-test/ an
lcc skills match "schreib Tests für slugify"
```

```
┏━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Skill       ┃ Score ┃ Grund           ┃ Status                   ┃
┡━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ pytest-test │  1.00 │ Trigger 'tests' │ wird automatisch geladen │
└─────────────┴───────┴─────────────────┴──────────────────────────┘
```

So wählt lcc Skills aus – je Auftrag:

1. **Trigger:** Kommt ein Trigger-Wort im Auftrag vor (Wortgrenzen, Groß/Klein egal) → Score 1.0.
2. **Ähnlichkeit:** Sonst zählt die Embedding-Ähnlichkeit zwischen Auftrag und Beschreibung.
3. Die besten Skills (höchstens `max_listed`) stehen mit Name + Beschreibung im Systemprompt.
4. Ab Score 0.55 lädt lcc den besten Skill **vorab** (`⚙ Skill: pytest-test`); sonst kann das
   Modell ihn mit `load_skill` holen.
5. Solange ein Skill aktiv ist, gelten seine `tools`-Liste und ggf. sein `model`.
6. Hat er `checks`, laufen sie nach den Änderungen – rote Checks bedeuten Exit 1.

Projekt-Skills (`./.lcc/skills/`) gewinnen gegen gleichnamige Benutzer-Skills
(`~/.config/lcc/skills/`).

---

## Eigene Skills schreiben

### 1. Gerüst anlegen

```bash
lcc skills new changelog-eintrag          # Projekt-Skill
lcc skills new commit-nachricht --user    # für alle Projekte
```

Das legt `.lcc/skills/<name>/SKILL.md` an. Optional daneben: `examples/` und `templates/` –
der Skill-Ordner ist für das Modell lesbar, solange der Skill aktiv ist.

### 2. Frontmatter ausfüllen

```markdown
---
name: changelog-eintrag
description: Ergänzt CHANGELOG.md um einen Eintrag im Format "Keep a Changelog". Nutzen bei "Changelog", "Release Notes".
triggers: changelog, release notes, versionshinweise
tools: read_file, list_dir, run_shell, edit_file, write_file
checks: python -m pytest -q {test_file}
context_files: pyproject.toml
model: code
version: 1
---
```

| Feld | Pflicht | Hinweis |
|---|---|---|
| `name` | ja | kebab-case, gleich dem Ordnernamen |
| `description` | ja | eine Zeile, ≤ 200 Zeichen: **was** der Skill tut und **wann** er greift |
| `triggers` | nein | Stichwörter/Phrasen, kommagetrennt (optional in `[ … ]`) |
| `tools` | nein | erlaubte Tools, solange der Skill aktiv ist |
| `checks` | nein | Prüfbefehle nach den Änderungen; Platzhalter `{changed}` (geänderte Dateien), `{test_file}` (zuletzt geschriebene Datei unter `tests/`) |
| `context_files` | nein | Dateien/Globs, die beim Laden mitgeliefert werden (gekürzt) |
| `model` | nein | `code`, `chat` oder ein konkreter Modellname |
| `version` | nein | Ganzzahl, nur zur Info |

### 3. Inhalt schreiben

```markdown
# CHANGELOG-Eintrag

## Ziel
`CHANGELOG.md` enthält unter `[Unreleased]` einen korrekt einsortierten Eintrag.

## Vorgehen
1. Lies `CHANGELOG.md` mit `read_file`.
2. Ordne die Änderung einer Rubrik zu: Added, Changed, Fixed, Removed.
3. Füge eine Zeile mit `edit_file` unter `## [Unreleased]` ein.

## Regeln
- Eine Zeile pro Änderung, beginnend mit einem Verb („Behebt …“).

## Nicht tun
- Bestehende Einträge ändern oder Versionsnummern erfinden.

## Ausgabe
Die eingefügte Zeile und ihre Rubrik.

## Beispiel
### Fixed
- Behebt falsche Umlaute im PDF-Lieferschein.
```

### 4. Prüfen

```bash
lcc skills check                                       # Fehler/Warnungen
lcc skills match "trag das ins Changelog ein"          # greift der Trigger?
```

### Faustregeln

- **Ein Skill = eine Aufgabe.** Lieber drei kleine Skills als ein großer.
- **Kurz:** ideal 1500–3000 Zeichen, höchstens `skills.max_body_chars` (6000).
- **Nummerierte Schritte mit klaren Verben** statt Prosa – nenne die Tools beim Namen.
- **Ein kurzes, vollständiges Beispiel** schlägt jede Beschreibung.
- **„Nicht tun“ ausdrücklich nennen** – kleine Modelle halten sich daran erstaunlich gut.
- **Trigger mit Bedacht:** Wortgrenzen gelten – `test` trifft nicht „Tests“. Zu allgemeine
  Trigger („fehler“, „code“) laden den Skill bei fast jedem Auftrag.
- **`tools` einschränken:** Ein Skill, der nichts ändern soll (z. B. Commit-Nachricht
  formulieren), bekommt nur `read_file` und `run_shell`.
- **`checks` nur mit Befehlen aus der Allowlist** – sonst werden sie ohne Terminal abgelehnt
  und gelten als fehlgeschlagen.

Sechs fertige Beispiele (pytest, Changelog, Commit-Nachricht, Docstrings, Fehleranalyse,
ABAP-Unit) liegen in [`examples/skills/`](examples/skills/).

---

## Kleinmodell-Modus

Kleine Modelle (≈ 3–14 Mrd. Parameter) können programmieren, scheitern aber oft an langen
Kontexten, vielen Tools, mehrstufiger Planung und exakten Textersetzungen. lcc erkennt sie
automatisch (`lcc doctor` zeigt es) und arbeitet dann so:

```
$ lcc run "Ergänze in calc.py eine Funktion mul(a, b)"
Kleinmodell-Modus (qwen3.5:9b, 9.7B)
Plan:
1. [explore] calc.py lesen (calc.py)
2. [edit] mul in calc.py ergänzen (calc.py)
3. [verify] Tests ausführen
[Enter] ausführen / [e] bearbeiten / [n] abbrechen:
▶ Schritt 1/3 [explore]: calc.py lesen
…
✓ Check bestanden: python -m py_compile calc.py
✗ Check fehlgeschlagen: python -m pytest -q
↻ Repair-Versuch 1: Fehler aus den Checks zurück an das Modell
▶ Schritt 4/4 [edit]: Behebe diesen Fehler: …
✓ Check bestanden: python -m pytest -q
```

- **Auto-Kontext:** erwähnte Dateien (mit Zeilennummern), eine Übersicht über Dateien und
  Symbole sowie die besten RAG-Treffer werden vorab mitgeliefert.
- **Plan:** strukturiert (JSON-Schema), 1–8 Schritte, anzeigbar und bearbeitbar.
- **Schritte:** je Schritt frischer Kontext, nur 2–5 Tools der Phase (`explore`, `edit`,
  `verify`) und kurze, von lcc erzeugte Zusammenfassungen der vorigen Schritte.
- **Robuste Werkzeuge:** `edit_file` verzeiht Abweichungen bei Leerzeichen/Einrückung und nennt
  sonst die drei ähnlichsten Stellen; `replace_lines` arbeitet mit Zeilennummern;
  `write_file` auf bestehende Dateien > 200 Zeilen ist gesperrt.
- **Verify & Repair:** Skill-`checks` → `small_model.verify_commands` → automatisch
  (`py_compile` für geänderte Python-Dateien, `pytest`, wenn `tests/` existiert). Fehler gehen
  gekürzt zurück an das Modell – höchstens `max_repair_attempts` Mal, bei gleichem Fehler sofort
  Abbruch.
- **Eskalation:** Ist `small_model.escalate_model` gesetzt (z. B. `qwen3.5:27b` auf demselben
  Server), versucht lcc den Fehler einmal mit diesem Modell.
- **Ehrlich:** Bleiben Checks rot, meldet lcc das mit Exit 1, der letzten Fehlermeldung und dem
  `undo`-Hinweis – nie „Erfolg“.

Modelle ohne Tool-Fähigkeit laufen im **Text-Tool-Modus**: lcc beschreibt die Tools im Prompt
und liest Aufrufe der Form `{"tool": "...", "arguments": {...}}` aus der Antwort.

---

## Skripte und Pipelines (`--json`)

Mit `--json` gibt lcc **eine JSON-Zeile je Ereignis** aus:

```bash
lcc --json run --yes "lege hallo.txt mit Hallo Welt an" | jq -c 'select(.type != "token")'
```

```json
{"type": "tool_call", "name": "write_file", "arguments": {"path": "hallo.txt", "content": "Hallo Welt"}}
{"type": "tool_result", "name": "write_file", "ok": true, "content": "Neu angelegt: hallo.txt (1 Zeilen)"}
{"type": "final", "content": "Datei angelegt.", "model": "qwen3.5:9b", "ok": true, "small_mode": false, …}
```

| Typ | Inhalt |
|---|---|
| `token` | Textstück der Antwort |
| `tool_call`, `tool_result` | Tool-Aufruf und Ergebnis |
| `plan`, `step`, `check` | Kleinmodell-Modus: Plan, Schritt, Prüfergebnis |
| `info`, `notice` | Statuszeilen (z. B. geladener Skill), Hinweise |
| `final` | Ergebnis mit `ok`, Modell, ggf. Quellen |
| `error` | Fehler mit `exit_code` |

`lcc models`, `doctor`, `config show`, `rag search/stats`, `skills …` und `undo` liefern mit
`--json` ebenfalls maschinenlesbare Ausgaben.

---

## Beispiele zum Ausprobieren

| Ordner | Inhalt |
|---|---|
| [`examples/rag/`](examples/rag/) | erfundene Doku „Kranich“ (Markdown, Text, Python, ABAP, TOML, Englisch) mit 15 Testfragen |
| [`examples/skills/`](examples/skills/) | sechs Beispiel-Skills mit erwarteter Auswahl |
| [`examples/skill-uebungen/`](examples/skill-uebungen/) | Übungsprojekt: je eine Aufgabe pro Skill; `einrichten.sh ~/lcc-uebungen` |

---

## Entwicklung

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

python -m pytest -q                                   # Tests (Ollama per httpx.MockTransport)
LCC_IT=1 python -m pytest -q tests/test_integration.py  # optional gegen den echten Server
ruff check . && ruff format --check .
mypy                                                  # --strict
```

Aufbau:

```
lcc/
  cli.py, repl.py, output.py     Befehle, interaktiver Modus, Ausgabe
  config.py, texts.py            Config (Laden/Mergen/Validieren), alle Nutzertexte
  ollama_client.py, model_info.py
  agent/                         Schleife, Tools, Sandbox, Prompts, Kleinmodell-Modus,
                                 Auto-Kontext, Verify, Fallback-Parser
  rag/                           Chunker, SQLite-Store, Indexer, Suche
  skills/                        Loader, Vorauswahl, Laufzeit, Linter, Gerüst
```

Abhängigkeiten: `httpx`, `typer`, `prompt_toolkit`, `rich`, `numpy`, `tomli-w` – sonst nichts.
