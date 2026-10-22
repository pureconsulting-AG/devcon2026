# lcc-Tutorial: Schritt für Schritt

Dieses Tutorial führt dich in etwa einer Stunde durch alle Funktionen von lcc – zum Mitmachen
im Terminal. Jede Lektion hat ein **Ziel**, die **Befehle** und **was du dabei siehst**.
Zum Nachschlagen gibt es die [README](README.md), als Präsentation die
[Slides](slides/lcc-tutorial.html) (im Browser öffnen, Pfeiltasten zum Blättern).

Du arbeitest in einem Übungsprojekt der (erfundenen) Nordlicht Logistik: ein bisschen Python-Code
mit eingebautem Fehler, ein CHANGELOG, eine ABAP-Klasse, eine Doku-Sammlung und sechs Skills.

> **Hinweis zu den Laufzeiten:** Mit `qwen3.5:9b` dauern Fragen einige Sekunden, Aufträge mit
> Änderungen 1–4 Minuten. Während das Modell arbeitet, zeigt lcc `⠹ denkt nach … 12s`.

---

## Lektion 0 – Vorbereitung

**Ziel:** lcc ist aufrufbar, der Server antwortet, das Übungsprojekt liegt bereit.

```bash
source /work/.venv/bin/activate          # oder einmalig: pipx install -e /work
lcc doctor
```

Alle Zeilen sollten ein `✓` haben. In der Tabelle steht bei `qwen3.5:9b` unter
„Kleinmodell-Modus“ ein **ja** – das wird in Lektion 4 wichtig.

Übungsprojekt anlegen (eigenes Git-Repo, damit lcc nur dort arbeitet):

```bash
/work/examples/skill-uebungen/einrichten.sh ~/lcc-tutorial
cd ~/lcc-tutorial
cp -r /work/examples/rag/docs docs
git add docs && git commit -m "Doku dazu"
ls
```

```
abap  bestellung.py  CHANGELOG.md  docs  lager.py  main.py  README.md  tests  traceback.txt  UEBUNGEN.md  utils.py
```

**Warum ein eigenes Repo?** lcc arbeitet nur im Projekt – das ist der Git-Root des Ordners, in
dem du lcc startest. Mit `git diff` siehst du jederzeit, was lcc geändert hat.

Prüfe kurz, dass der richtige Ordner gilt:

```bash
lcc config show | grep -A1 '^\[workspace\]'
```

```
[workspace]
root = "/home/dev/lcc-tutorial"  # Default
```

---

## Lektion 1 – Fragen stellen (`lcc ask`)

**Ziel:** Einfache Fragen ohne Werkzeuge, mit und ohne Datei als Kontext.

```bash
lcc ask "Was ist der Unterschied zwischen einer Liste und einem Tupel in Python? Kurz."
```

`ask` nutzt keine Tools und ändert nichts. Eine Datei gibst du per Pipe mit:

```bash
cat bestellung.py | lcc ask "Erkläre diese Datei in drei Sätzen."
```

Das geht mit jeder Ausgabe – auch mit Fehlermeldungen:

```bash
python main.py 2>&1 | lcc ask "Was bedeutet dieser Fehler?"
```

**Tipp:** `ask` ist der schnellste Weg für Fragen. Sobald lcc Dateien selbst lesen, suchen oder
ändern soll, nimm `lcc run` (nächste Lektion).

---

## Lektion 2 – Code verstehen (`lcc run`, nur lesen)

**Ziel:** lcc liest und durchsucht das Projekt selbst.

```bash
lcc run --no-small "Welche Funktionen gibt es in lager.py und was machen sie?"
```

```
→ read_file(path='lager.py')
  ↳ 25 Zeilen
In lager.py gibt es drei Funktionen:
- nachbestellen(…) …
```

Die Zeilen mit `→` sind **Tool-Aufrufe**: lcc zeigt, was das Modell gerade tut. `↳` ist die
Größe des Ergebnisses. Verfügbare Lese-Tools: `list_dir`, `read_file`, `search_code`.

Eine Suche über das ganze Projekt:

```bash
lcc run --no-small "Wo wird versandkosten aufgerufen?"
```

```
→ search_code(pattern='versandkosten')
```

> `--no-small` schaltet hier den Kleinmodell-Modus ab, damit du den einfachen Ablauf siehst.
> In Lektion 4 lernst du, was er zusätzlich macht.

---

## Lektion 3 – Code ändern, bestätigen, zurücknehmen

**Ziel:** lcc ändert Dateien – du behältst die Kontrolle.

```bash
lcc run --no-small "Füge in utils.py eine Funktion ist_gerade(n) hinzu, die True für gerade Zahlen liefert."
```

Vor der Änderung zeigt lcc einen farbigen **Diff** und fragt:

```
Änderung an utils.py:
--- a/utils.py
+++ b/utils.py
@@ …
+def ist_gerade(n: int) -> bool:
+    return n % 2 == 0
[j]a / [n]ein / [i]mmer für diese Session:
```

- `j` – diese Änderung erlauben
- `n` – ablehnen (das Modell erfährt es und kann reagieren)
- `i` – alle weiteren Änderungen in diesem Lauf ohne Rückfrage

Danach:

```bash
git diff utils.py        # was hat sich geändert?
lcc undo                 # letzte Änderung zurücknehmen
git diff utils.py        # wieder weg
```

`lcc undo` funktioniert mehrfach hintereinander und auch für Dateien, die lcc neu angelegt hat
(sie werden gelöscht). Die Backups liegen in `.lcc/undo/`.

**Shell-Befehle:** Will das Modell etwas ausführen, gilt die **Allowlist** (`ls`, `cat`, `rg`,
`grep`, `git status`, `git diff`, `pytest`, `python -m pytest`, `python -m py_compile`). Alles
andere fragt lcc vorher – z. B. `python main.py`. In Lektion 8 erweiterst du die Liste.

**Ohne Rückfragen** (z. B. wenn du dem Ergebnis per `git diff` ohnehin prüfst):

```bash
lcc run --yes "…"
```

`--yes` gilt nur für Dateiänderungen – Shell-Befehle außerhalb der Allowlist bleiben
bestätigungspflichtig.

---

## Lektion 4 – Der Kleinmodell-Modus: Plan, Schritte, Prüfen, Reparieren

**Ziel:** Verstehen, wie lcc einem kleinen Modell bei größeren Aufgaben hilft.

Ohne `--no-small` arbeitet lcc mit `qwen3.5:9b` automatisch im Kleinmodell-Modus. Probier den
Bug aus der Übung:

```bash
cat traceback.txt
lcc run "Beim Start von main.py kommt der Fehler aus traceback.txt. Finde die Ursache in bestellung.py und behebe sie."
```

Was du siehst (der genaue Plan variiert von Lauf zu Lauf):

```
⚙ Skill: fehler-analysieren
Kleinmodell-Modus (qwen3.5:9b, 9.7B)
Plan:
1. [explore] bestellung.py lesen (bestellung.py)
2. [edit] Gewicht in lies_formular in float umwandeln (bestellung.py)
[Enter] ausführen / [e] bearbeiten / [n] abbrechen:
```

0. **Skill:** Das Wort „Traceback“ lädt den passenden Skill (mehr dazu in Lektion 7).
1. **Plan:** Das Modell zerlegt den Auftrag in Schritte mit einer Phase:
   `explore` (lesen), `edit` (ändern), `verify` (prüfen).
2. **Dein Einfluss:** Enter führt aus, `n` bricht ab, `e` lässt dich den Plan neu schreiben –
   eine Zeile pro Schritt, z. B. `edit: Gewicht in lies_formular mit float() umwandeln`,
   leere Zeile beendet.
3. **Schritte:** `▶ Schritt 1/2 [explore]: …` – jeder Schritt bekommt nur die Werkzeuge
   seiner Phase und eine kurze Zusammenfassung der vorigen Schritte. Das hält den Kontext klein.
4. **Prüfen:** Nach den Änderungen startet lcc selbst Prüfbefehle:
   ```
   ✓ Check bestanden: python -m py_compile bestellung.py
   ✓ Check bestanden: python -m pytest -q
   ```
5. **Reparieren:** Wäre ein Check rot, gibt lcc die Fehlermeldung als neuen Schritt an das
   Modell zurück: `↻ Repair-Versuch 1 …`. Bleibt es rot, bricht lcc **ehrlich** ab (Exit 1,
   letzte Fehlermeldung, Hinweis auf `lcc undo`).

Prüfe das Ergebnis:

```bash
python main.py           # → Petra Lindner: 7.03 EUR
```

**Wann was?**

| Situation | Empfehlung |
|---|---|
| Aufgabe mit Änderungen an Code und Tests | Kleinmodell-Modus (automatisch) |
| kurze Frage zum Code | `lcc run --no-small …` oder `lcc ask` |
| großes Modell (> 14 Mrd. Parameter) | lcc schaltet den Modus automatisch ab |
| Modus erzwingen / abschalten | `--small` / `--no-small` |

---

## Lektion 5 – Interaktiv arbeiten (REPL)

**Ziel:** Ein Gespräch mit Verlauf, Dateien anhängen, Änderungen ansehen.

```bash
lcc
```

```
lcc – Modell qwen3.5:9b auf http://192.168.178.79:11434. /help zeigt die Befehle, Esc+Enter für neue Zeile.
›
```

Probier nacheinander:

```text
› /add utils.py
Angehängt an die nächste Nachricht: utils.py (Zeilen 1-… von …)
› Was macht format_euro mit 1234.5?
› Und mit negativen Zahlen?
```

Die zweite Frage versteht lcc, weil der Verlauf erhalten bleibt.

Auch in der REPL gilt der Kleinmodell-Modus: Bei Aufträgen mit Änderungen erscheint der Plan
mit `[Enter] ausführen / [e] bearbeiten / [n] abbrechen`.

```text
› Ergänze in utils.py einen Docstring-Beispielaufruf für format_euro
› /diff                     # alle Änderungen dieser Session
› /undo                     # letzte zurücknehmen
› /save tutorial            # Session speichern
› /clear                    # Verlauf leeren
› /load tutorial            # und wieder laden
› /help                     # alle Befehle
```

**Tasten:** Esc+Enter für eine neue Zeile · ↑/↓ blättert durch frühere Eingaben · Tab
vervollständigt `/befehle` und Pfade nach `/add` · Strg-C bricht die laufende Antwort ab ·
zweimal Strg-C (oder `/exit`) beendet.

---

## Lektion 6 – Eigene Dokumentation durchsuchen (RAG)

**Ziel:** lcc beantwortet Fragen aus deinen Dokumenten – mit Quellenangabe.

Im Ordner `docs/` liegt die Doku der Sendungsverfolgung „Kranich“ – Fakten, die kein Modell
kennen kann. Erst indexieren:

```bash
lcc rag index
lcc rag stats
```

```
Index aktualisiert: 9 neu, 0 geändert, 0 unverändert, 0 entfernt – 9 Dateien, 26 Chunks
```

Dann suchen und fragen:

```bash
lcc rag search "Wer gibt Deployments frei?"
lcc ask "Wann darf Kranich ausgerollt werden und wer gibt frei?"
```

```
RAG: [1] docs/handbuch/betrieb.md:3-9, [2] …
Kranich wird nur mittwochs zwischen 6:00 und 8:00 Uhr ausgerollt; die Freigabe erteilt
Tobias Reinhardt, in Vertretung Aylin Demir [1].
```

Die `[n]` verweisen auf die Quellen in der ersten Zeile. Weitere Fragen zum Ausprobieren
(Antworten in `/work/examples/rag/README.md`):

```bash
lcc ask "Wie lange werden Backups aufbewahrt?"
lcc ask "Wie lange ist ein API-Schlüssel gültig?"        # steht nur im englischen Dokument
lcc ask "Was kostet eine Expresssendung mit 2 kg?"       # steht im Code docs/code/tarife.py
lcc ask "Wie heißt der Hund von Tobias?"                 # steht nirgends – Gegenprobe
```

**Doku ändern:** Datei bearbeiten und `lcc rag index` erneut aufrufen – nur geänderte Dateien
werden neu berechnet.

**RAG im Agenten und in der REPL:**

```bash
lcc run --no-small "Schau in der Doku nach, wie die Rufbereitschaft wechselt."
```

```
→ rag_search(query='Rufbereitschaft Wechsel')
```

In der REPL: `/rag Backups` zeigt Treffer direkt, `/rag off` schaltet das Tool ab.
`--no-rag` schaltet RAG für einen Aufruf ab.

**Eigene Quellen:** Standard ist `./docs` und `~/rag-docs`. Andere Ordner trägst du in der
Config ein (Lektion 8): `[rag] sources = ["./handbuch", "~/wiki"]`.

---

## Lektion 7 – Skills: Anleitungen, die lcc bei Bedarf lädt

**Ziel:** Skills nutzen und einen eigenen schreiben.

### 7.1 Vorhandene Skills ansehen

```bash
lcc skills
lcc skills show changelog-eintrag
```

Ein Skill ist eine kurze Anleitung für **eine** Art von Aufgabe. lcc lädt ihn nur, wenn der
Auftrag passt – vorher sieht das Modell nur Name und Beschreibung.

### 7.2 Welcher Skill würde geladen?

```bash
lcc skills match "trag ins Changelog ein: Versandkosten funktionieren jetzt mit Text-Gewicht"
```

```
│ changelog-eintrag │ 1.00 │ Trigger 'changelog' │ wird automatisch geladen │
│ commit-nachricht  │ 0.49 │ Ähnlichkeit 0.49    │ im Systemprompt gelistet │
```

(Die Ähnlichkeitswerte hängen vom Embedding-Modell ab und können leicht abweichen.)

- **Trigger** (Stichwort im Auftrag) → Score 1.0 → wird automatisch geladen.
- **Ähnlichkeit** (Bedeutung des Auftrags) → Score 0–1; ab 0.55 wird geladen, darunter nur
  gelistet – das Modell kann ihn dann selbst holen.

### 7.3 Skill in Aktion

```bash
lcc run "trag ins Changelog ein: Versandkosten funktionieren jetzt mit Text-Gewicht"
```

```
⚙ Skill: changelog-eintrag
```

Danach: `git diff CHANGELOG.md` – eine neue Zeile unter `[Unreleased]` → `### Fixed`.

Ein Skill, der **nichts ändern darf**:

```bash
git status                                    # zwei offene Änderungen aus der Einrichtung
lcc run "Schlag mir eine Commit-Nachricht für meine aktuellen Änderungen vor"
git status                                    # unverändert
```

Der Skill `commit-nachricht` erlaubt nur `run_shell` (für `git status`/`git diff`) und
`read_file` – lcc schränkt die Werkzeuge ein, solange er aktiv ist. Im Plan siehst du Schritte
wie `[explore] git diff anzeigen`, am Ende steht die Nachricht im Codeblock.

Mehr Aufgaben pro Skill: [`UEBUNGEN.md`](examples/skill-uebungen/UEBUNGEN.md) im Projekt.

### 7.4 Einen eigenen Skill schreiben

Wir bauen einen Skill, der alle `TODO`-Kommentare in einer `TODO.md` sammelt.

**1. Etwas zum Sammeln anlegen:**

```bash
printf '\n# TODO: Mindestbestand aus der Config lesen\n' >> lager.py
printf '\n# TODO: Expresszuschlag ergänzen\n' >> bestellung.py
```

**2. Gerüst erzeugen:**

```bash
lcc skills new todo-sammeln
```

**3. `.lcc/skills/todo-sammeln/SKILL.md` ersetzen durch:**

```markdown
---
name: todo-sammeln
description: Sammelt alle TODO-Kommentare im Projekt in einer Datei TODO.md. Nutzen bei "TODOs sammeln", "offene Punkte".
triggers: todo, todos, offene punkte
tools: search_code, read_file, write_file
version: 1
---

# TODOs sammeln

## Ziel
`TODO.md` listet alle TODO-Kommentare mit Datei und Zeile.

## Vorgehen
1. Suche mit `search_code` nach dem Muster `TODO`.
2. Schreibe `TODO.md` mit `write_file`: je Fund eine Zeile `- [ ] <datei>:<zeile> – <text>`.

## Nicht tun
- Code ändern oder TODO-Kommentare entfernen.

## Ausgabe
Anzahl der gefundenen TODOs.

## Beispiel
- [ ] lager.py:12 – Mindestbestand aus der Config lesen
```

Was die Felder bedeuten:
- `description` – **was** der Skill tut und **wann**; das sieht das Modell immer.
- `triggers` – Stichwörter, die den Skill sicher laden (Wortgrenzen: `todo` trifft nicht
  „todos“ – deshalb stehen beide drin).
- `tools` – nur diese Werkzeuge, solange der Skill aktiv ist. Hier kann er nichts außer
  `TODO.md` schreiben – `edit_file` fehlt bewusst.

**4. Prüfen und ausprobieren:**

```bash
lcc skills check
lcc skills match "Sammle alle TODOs im Projekt"
lcc run "Sammle alle TODOs im Projekt"
cat TODO.md
```

```
⚙ Skill: todo-sammeln
…
- [ ] bestellung.py:26 – Expresszuschlag ergänzen
- [ ] lager.py:25 – Mindestbestand aus der Config lesen
```

**Faustregeln** für gute Skills: eine Aufgabe pro Skill, nummerierte Schritte mit Tool-Namen,
ein kurzes Beispiel, „Nicht tun“ ausdrücklich nennen, 1500–3000 Zeichen. Mehr dazu im
README-Kapitel [Eigene Skills schreiben](README.md#eigene-skills-schreiben).

**Für alle Projekte:** `lcc skills new <name> --user` legt den Skill in
`~/.config/lcc/skills/` an.

---

## Lektion 8 – lcc anpassen (Config, Projektregeln)

**Ziel:** Einstellungen fürs Projekt ändern.

Die effektive Config mit Herkunft jedes Werts:

```bash
lcc config show | less
```

**Projekt-Config** `./.lcc/config.toml` – gilt nur hier. Beispiel: `python main.py` ohne
Rückfrage erlauben:

```bash
cat > .lcc/config.toml <<'EOF'
[agent]
shell_allowlist = ["ls", "cat", "rg", "grep", "git status", "git diff",
                   "pytest", "python -m pytest", "python -m py_compile",
                   "python main.py"]
EOF
lcc config show | grep shell_allowlist
```

```
shell_allowlist = [… "python main.py"]  # /home/dev/lcc-tutorial/.lcc/config.toml
```

Die Allowlist vergleicht den **Anfang** des Befehls: `python main.py` erlaubt genau diesen Aufruf
(auch mit weiteren Argumenten), aber nicht `python anderes.py`.

**Projektregeln für das Modell** in `./.lcc/AGENT.md`:

```bash
cat > .lcc/AGENT.md <<'EOF'
- Schreibe Kommentare und Docstrings auf Deutsch.
- Nutze Typannotationen bei neuen Funktionen.
- Beträge sind immer Euro mit zwei Nachkommastellen.
EOF
```

lcc hängt diese Regeln an jeden Systemprompt in diesem Projekt.

**Weitere nützliche Einstellungen:**

```toml
[models]
chat = "qwen3.5:9b"          # Modell für lcc ask

[small_model]
mode = "auto"                # "on" | "off"
verify_commands = ["python -m pytest -q"]   # eigene Prüfbefehle statt automatisch
escalate_model = ""          # z. B. ein größeres Modell für hartnäckige Fehler

[ui]
show_tool_calls = true       # false = keine →-Zeilen
```

Für alle Projekte: `lcc config init` legt `~/.config/lcc/config.toml` mit allen Keys und
Kommentaren an. Einmalig für einen Aufruf: `lcc --model qwen2.5-coder:14b run "…"`.

---

## Lektion 9 – lcc in Skripten (`--json`)

**Ziel:** lcc automatisiert aufrufen und das Ergebnis auswerten.

```bash
lcc --json ask "Antworte nur mit: ok" | tail -1
```

```json
{"type": "final", "content": "ok", "model": "qwen3.5:9b", "sources": []}
```

Jedes Ereignis ist eine Zeile: `token`, `tool_call`, `tool_result`, `plan`, `step`, `check`,
`info`, `final`, `error`. Mit `jq` filtern:

```bash
lcc --json run --yes "Sammle alle TODOs im Projekt" \
  | jq -c 'select(.type == "tool_call" or .type == "check" or .type == "final") | {type, name, command, ok}'
```

Der **Exit-Code** sagt, ob es geklappt hat:

```bash
lcc run --yes "…"; echo "exit=$?"
```

| Code | Bedeutung |
|---|---|
| 0 | ok |
| 1 | Auftrag nicht erfolgreich (z. B. Checks rot) |
| 2 | Config-Fehler |
| 3 | Server nicht erreichbar |
| 4 | Modell fehlt (Hinweis `ollama pull …`) |
| 130 | Abbruch mit Strg-C |

Ohne Terminal (Skript, Cron, Pipe) fragt lcc nie: Schreiben nur mit `--yes`, Shell außerhalb der
Allowlist wird abgelehnt.

---

## Lektion 10 – Wenn etwas hakt

| Problem | Lösung |
|---|---|
| `Ollama-Server nicht erreichbar` (Exit 3) | `lcc doctor`; URL prüfen (`lcc config show`), ggf. `--url` / `LCC_OLLAMA_URL` |
| `Modell '…' fehlt` (Exit 4) | auf dem Server `ollama pull <modell>` oder anderes Modell in der Config |
| lcc arbeitet im falschen Ordner | `lcc config show \| grep -A1 workspace` – lcc nutzt den Git-Root |
| Modell rät statt zu lesen | Datei im Auftrag nennen („in utils.py …“) oder in der REPL `/add utils.py` |
| Änderung gefällt nicht | `lcc undo` (mehrfach) oder `git checkout -- <datei>` |
| Befehl wird abgelehnt | steht nicht auf der Allowlist → im Terminal bestätigen oder Allowlist erweitern (Lektion 8) |
| Skill wird nicht geladen | `lcc skills match "<Auftrag>"` – ggf. Trigger ergänzen |
| RAG findet nichts | `lcc rag stats`; nach Doku-Änderungen `lcc rag index`; nach Modellwechsel `--rebuild` |
| sehr langsam | erster Aufruf lädt das Modell; der Kleinmodell-Modus braucht mehrere Runden – für Fragen `--no-small` oder `lcc ask` |
| `Kontext fast voll – … gekürzt` | normal bei langen Sitzungen; in der REPL `/clear` für einen frischen Start |

Mehr Details siehst du mit `-v` (z. B. verdeckte Skills) und `--show-thinking` (Gedanken des
Modells, wenn `[models.thinking] enabled = true`).

---

## Wie geht es weiter?

- Übe mit [`UEBUNGEN.md`](examples/skill-uebungen/UEBUNGEN.md) – je eine Aufgabe pro Skill.
- Nimm dir ein eigenes Projekt: `cd mein-projekt && lcc doctor && lcc`.
- Schreib Skills für deine wiederkehrenden Aufgaben – lieber mehrere kleine als einen großen.
- Leg deine Doku nach `./docs` oder `~/rag-docs` und indexiere sie.
- Alles zum Nachschlagen: [README](README.md).
