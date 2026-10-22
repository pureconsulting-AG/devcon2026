"""Erzeugt slides/lcc-tutorial.html aus den Inhalten unten.

    python slides/build_slides.py

Aufbau: Titel → Überblick → Agenda → je Lektion eine Einstiegsfolie und ein Fall pro Folie
(Ziel · Du tippst · Du siehst · Merke). Codeblöcke werden zeilenweise eingefärbt:
"$ …" Befehl, "# …" Kommentar, "✓" ok, "✗" Fehler, "→"/"⚙"/"▶"/"↻" Info, "[j]a…" Rückfrage.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from pathlib import Path

OUT = Path(__file__).with_name("lcc-tutorial.html")


@dataclass
class Case:
    title: str
    goal: str
    typed: str
    seen: str
    note: str = ""
    note_label: str = "Merke"


@dataclass
class Lesson:
    number: int
    title: str
    intro: str
    learn: list[str]
    cases: list[Case] = field(default_factory=list)
    extra_html: str = ""  # optionale Abschlussfolie (z. B. Spickzettel)


LESSONS: list[Lesson] = [
    Lesson(
        0,
        "Vorbereitung",
        "Einmal einrichten, dann kann es losgehen.",
        ["lcc aufrufen und den Server prüfen", "Übungsprojekt anlegen", "prüfen, wo lcc arbeitet"],
        [
            Case(
                "lcc starten und prüfen",
                "lcc ist aufrufbar und der Ollama-Server antwortet.",
                "$ source /work/.venv/bin/activate\n# oder einmalig: pipx install -e /work\n$ lcc doctor",
                "✓ Server: … erreichbar, 14 Modelle\n✓ Modell qwen3.5:9b (code, chat): 9.7B\n"
                "✓ Modell bge-m3 (embed): 566.70M\n✓ Tool-Calling: native tool_calls funktionieren\n"
                "✓ Embedding (bge-m3): Dimension 1024",
                "Alle Zeilen brauchen ein ✓. In der Tabelle steht bei qwen3.5:9b "
                "„Kleinmodell-Modus: ja“ – wichtig für Lektion 4.",
            ),
            Case(
                "Übungsprojekt anlegen",
                "Ein eigenes Git-Projekt mit Code, Doku und Skills zum Üben.",
                "$ /work/examples/skill-uebungen/einrichten.sh ~/lcc-tutorial\n$ cd ~/lcc-tutorial\n"
                '$ cp -r /work/examples/rag/docs docs\n$ git add docs && git commit -m "Doku dazu"\n$ ls',
                "abap  bestellung.py  CHANGELOG.md  docs  lager.py\nmain.py  README.md  tests  "
                "traceback.txt  UEBUNGEN.md  utils.py",
                "Darin: Python-Code mit eingebautem Fehler, ein CHANGELOG, eine ABAP-Klasse, die Doku "
                "„Kranich“ und sechs Skills unter .lcc/skills/.",
            ),
            Case(
                "Prüfen, wo lcc arbeitet",
                "Sicherstellen, dass lcc nur im Übungsprojekt liest und schreibt.",
                "$ lcc config show | grep -A1 '^\\[workspace\\]'",
                '[workspace]\nroot = "/home/dev/lcc-tutorial"  # Default',
                "lcc arbeitet im Git-Root des Ordners, in dem du es startest. Mit git diff siehst du "
                "jede Änderung.",
            ),
        ],
    ),
    Lesson(
        1,
        "Fragen stellen",
        "lcc ask beantwortet Fragen – ohne Werkzeuge, ohne etwas zu ändern.",
        [
            "eine einfache Frage stellen",
            "eine Datei erklären lassen",
            "eine Fehlermeldung erklären lassen",
        ],
        [
            Case(
                "Eine Frage stellen",
                "Eine schnelle Antwort, ganz ohne Projekt-Kontext.",
                '$ lcc ask "Unterschied zwischen Liste und Tupel in Python? Kurz."',
                "⠹ denkt nach … 3s\nEine Liste ist veränderbar, ein Tupel nicht. …",
                "ask nutzt keine Werkzeuge und ändert nie etwas. Der Spinner zeigt, dass das Modell "
                "arbeitet.",
            ),
            Case(
                "Eine Datei erklären lassen",
                "Eine Datei als Kontext mitgeben – per Pipe.",
                '$ cat bestellung.py | lcc ask "Erkläre diese Datei in drei Sätzen."',
                "Die Datei berechnet Versandkosten …\nlies_formular übernimmt die Felder …\n"
                "bestellung_bearbeiten verbindet beides …",
                "Alles, was über stdin kommt, hängt lcc an die Frage an.",
            ),
            Case(
                "Eine Fehlermeldung erklären lassen",
                "Die Ausgabe eines Programms direkt weitergeben.",
                '$ python main.py 2>&1 | lcc ask "Was bedeutet dieser Fehler?"',
                "Der TypeError entsteht, weil gewicht_kg ein String ist\n"
                '("2.5") und mit einer Zahl multipliziert wird. …',
                "2>&1 schickt auch die Fehlerausgabe in die Pipe. Beheben lassen wir den Fehler in "
                "Lektion 4.",
                "Probier auch",
            ),
        ],
    ),
    Lesson(
        2,
        "Code verstehen",
        "lcc run liest und durchsucht das Projekt selbst.",
        ["eine Datei erklären lassen, die lcc selbst liest", "das Projekt durchsuchen lassen"],
        [
            Case(
                "lcc liest selbst",
                "lcc öffnet die Datei, statt dass du sie mitgibst.",
                '$ lcc run --no-small "Welche Funktionen gibt es in lager.py?"',
                "→ read_file(path='lager.py')\n  ↳ 25 Zeilen\nIn lager.py gibt es drei Funktionen:\n"
                "- nachbestellen …\n- bestand_buchen …\n- lagerwert …",
                "→ zeigt einen Tool-Aufruf, ↳ die Größe des Ergebnisses. --no-small zeigt den "
                "einfachen Ablauf (Lektion 4 erklärt den Rest).",
            ),
            Case(
                "Das Projekt durchsuchen",
                "Finden, wo etwas verwendet wird.",
                '$ lcc run --no-small "Wo wird versandkosten aufgerufen?"',
                "→ search_code(pattern='versandkosten')\n  ↳ 3 Zeilen\n"
                "versandkosten wird in bestellung.py, Zeile 24, aufgerufen …",
                "Lese-Werkzeuge: list_dir, read_file, search_code. Keines davon ändert etwas.",
            ),
        ],
    ),
    Lesson(
        3,
        "Code ändern – und zurücknehmen",
        "lcc ändert Dateien nur mit deinem Okay. Jede Änderung lässt sich zurücknehmen.",
        [
            "eine Funktion hinzufügen lassen",
            "die Änderung prüfen und zurücknehmen",
            "Shell-Befehle und die Allowlist",
            "ohne Rückfragen arbeiten",
        ],
        [
            Case(
                "Eine Funktion hinzufügen",
                "lcc schlägt eine Änderung vor – du entscheidest.",
                '$ lcc run --no-small "Füge in utils.py eine Funktion ist_gerade(n) hinzu."',
                "Änderung an utils.py:\n--- a/utils.py\n+++ b/utils.py\n+def ist_gerade(n: int) -> bool:\n"
                "+    return n % 2 == 0\n[j]a / [n]ein / [i]mmer für diese Session:",
                "j erlaubt, n lehnt ab (das Modell erfährt es), i erlaubt alle weiteren Änderungen "
                "in diesem Lauf.",
            ),
            Case(
                "Prüfen und zurücknehmen",
                "Sehen, was geändert wurde – und es rückgängig machen.",
                "$ git diff utils.py\n$ lcc undo\n$ git diff utils.py",
                "+def ist_gerade(n: int) -> bool:\n+    return n % 2 == 0\n"
                "Zurückgenommen: utils.py wiederhergestellt.\n(keine Änderungen mehr)",
                "lcc undo geht mehrfach hintereinander und löscht auch Dateien, die lcc neu angelegt "
                "hat. Backups liegen in .lcc/undo/.",
            ),
            Case(
                "Shell-Befehle und Allowlist",
                "Verstehen, wann lcc vor einem Befehl fragt.",
                '$ lcc run --no-small "Führe main.py aus und sag mir das Ergebnis."',
                "→ run_shell(command='python main.py')\nShell-Befehl ausführen: python main.py\n"
                "[j]a / [n]ein / [i]mmer für diese Session:",
                "Ohne Rückfrage erlaubt: ls, cat, rg, grep, git status, git diff, pytest, "
                "python -m pytest, python -m py_compile. Alles andere wird bestätigt.",
            ),
            Case(
                "Ohne Rückfragen arbeiten",
                "Änderungen direkt schreiben lassen – du prüfst danach mit git diff.",
                '$ lcc run --yes "Füge in utils.py eine Funktion ist_gerade(n) hinzu."\n$ git diff',
                "→ edit_file(path='utils.py', …)\n  ↳ 1 Zeilen\nFunktion ist_gerade hinzugefügt.",
                "--yes gilt nur für Dateien. Shell-Befehle außerhalb der Allowlist bleiben "
                "bestätigungspflichtig – ohne Terminal werden sie abgelehnt.",
            ),
        ],
    ),
    Lesson(
        4,
        "Kleinmodell-Modus",
        "Kleine Modelle scheitern an langen Aufgaben. lcc hilft mit Struktur: "
        "Plan → Schritte → Prüfen → Reparieren.",
        [
            "einen Plan ansehen und bestätigen",
            "Schritte und Prüfungen verfolgen",
            "einen Plan bearbeiten",
            "verstehen, was bei roten Prüfungen passiert",
        ],
        [
            Case(
                "Den Plan ansehen",
                "Den Fehler aus Lektion 1 beheben – lcc plant zuerst.",
                '$ cat traceback.txt\n$ lcc run "Beim Start von main.py kommt der Fehler aus '
                'traceback.txt. Finde die Ursache in bestellung.py und behebe sie."',
                "⚙ Skill: fehler-analysieren\nKleinmodell-Modus (qwen3.5:9b, 9.7B)\nPlan:\n"
                "1. [explore] bestellung.py lesen (bestellung.py)\n"
                "2. [edit] Gewicht in lies_formular in float umwandeln\n"
                "[Enter] ausführen / [e] bearbeiten / [n] abbrechen:",
                "Automatisch aktiv bei Modellen bis 14 Mrd. Parameter. Phasen: explore = lesen, "
                "edit = ändern, verify = prüfen. Der genaue Plan variiert.",
            ),
            Case(
                "Schritte und Prüfungen",
                "Mit Enter den Plan ausführen und zusehen.",
                "[Enter]",
                "▶ Schritt 1/2 [explore]: bestellung.py lesen\n→ read_file(path='bestellung.py')\n"
                "▶ Schritt 2/2 [edit]: Gewicht in float umwandeln\n→ edit_file(path='bestellung.py', …)\n"
                "✓ Check bestanden: python -m py_compile bestellung.py\n✓ Check bestanden: python -m pytest -q",
                "Jeder Schritt bekommt nur die Werkzeuge seiner Phase und eine kurze Zusammenfassung "
                "der vorigen Schritte. Danach prüft lcc selbst.",
            ),
            Case(
                "Den Plan bearbeiten",
                "Den Plan selbst vorgeben, wenn er dir nicht gefällt.",
                "[Enter] ausführen / [e] bearbeiten / [n] abbrechen: e\n"
                "> explore: bestellung.py und main.py lesen\n> edit: Gewicht in lies_formular mit float() umwandeln\n>",
                "Plan:\n1. [explore] bestellung.py und main.py lesen\n"
                "2. [edit] Gewicht in lies_formular mit float() umwandeln\n"
                "[Enter] ausführen / [e] bearbeiten / [n] abbrechen:",
                "Eine Zeile pro Schritt im Format „phase: Ziel“, leere Zeile beendet. n bricht ab, "
                "ohne etwas zu ändern.",
                "Probier auch",
            ),
            Case(
                "Wenn eine Prüfung rot ist",
                "Verstehen, wie lcc repariert – und wann es ehrlich aufgibt.",
                "# lcc prüft nach den Änderungen automatisch:\n# py_compile für geänderte Python-Dateien,\n"
                "# pytest, wenn es tests/ gibt",
                "✗ Check fehlgeschlagen: python -m pytest -q\n"
                "↻ Repair-Versuch 1: Fehler aus den Checks zurück an das Modell\n"
                "▶ Schritt 3/3 [edit]: Behebe diesen Fehler: …\n✓ Check bestanden: python -m pytest -q",
                "Bleibt es rot: Abbruch mit Exit 1, letzter Fehlermeldung und Hinweis auf lcc undo – "
                "nie „Erfolg“. Prüfe danach: python main.py → Petra Lindner: 7.03 EUR",
            ),
        ],
    ),
    Lesson(
        5,
        "Interaktiv arbeiten",
        "In der REPL führst du ein Gespräch mit Verlauf – mit Slash-Befehlen für alles Weitere.",
        [
            "die REPL starten und mit Verlauf fragen",
            "eine Datei anhängen",
            "Änderungen ansehen und zurücknehmen",
            "Sessions speichern und laden",
        ],
        [
            Case(
                "Die REPL starten",
                "Fragen stellen, die aufeinander aufbauen.",
                "$ lcc\n› Was macht format_euro in utils.py?\n› Und mit negativen Zahlen?",
                "lcc – Modell qwen3.5:9b … /help zeigt die Befehle\n→ read_file(path='utils.py')\n"
                "format_euro formatiert … 1.234,50 €\n… bei -5 ergibt sich -5,00 €",
                "Die zweite Frage versteht lcc, weil der Verlauf erhalten bleibt. "
                "Esc+Enter = neue Zeile, ↑/↓ = frühere Eingaben.",
            ),
            Case(
                "Eine Datei anhängen",
                "lcc eine Datei direkt in die nächste Nachricht legen.",
                "› /add lager.py\n› Was passiert, wenn der Bestand negativ würde?",
                "Angehängt an die nächste Nachricht: lager.py (Zeilen 1-… von …)\n"
                "bestand_buchen wirft dann einen ValueError …",
                "Tab vervollständigt Pfade nach /add. Gut, wenn das Modell sonst rät.",
            ),
            Case(
                "Änderungen ansehen und zurücknehmen",
                "Alles, was lcc in dieser Session geändert hat, im Blick behalten.",
                "› Ergänze in utils.py eine Funktion ist_gerade(n)\n› /diff\n› /undo",
                "[j]a / [n]ein / [i]mmer für diese Session: j\n+def ist_gerade(n: int) -> bool: …\n"
                "Zurückgenommen: utils.py wiederhergestellt.",
                "Auch in der REPL gilt der Kleinmodell-Modus: bei Änderungen erscheint der Plan.",
            ),
            Case(
                "Sessions speichern und laden",
                "Ein Gespräch später fortsetzen.",
                "› /save tutorial\n› /clear\n› /load\n› /load tutorial\n› /exit",
                "Session gespeichert: ~/.local/state/lcc/sessions/tutorial.jsonl\n"
                "Verlauf geleert, neue Session.\n  tutorial  2026-10-13 10:15  6 Nachrichten\n"
                "Session tutorial geladen (6 Nachrichten).",
                "Strg-C bricht nur die laufende Antwort ab, zweimal Strg-C (oder /exit) beendet. "
                "/help zeigt alle Befehle.",
            ),
        ],
    ),
    Lesson(
        6,
        "Eigene Doku durchsuchen (RAG)",
        "lcc beantwortet Fragen aus deinen Dokumenten – mit Quellenangabe.",
        [
            "den Index bauen",
            "die Doku durchsuchen",
            "Fragen mit Quellen beantworten",
            "englische Doku und Code finden",
            "RAG im Agenten und in der REPL",
        ],
        [
            Case(
                "Den Index bauen",
                "lcc liest die Dokumente unter docs/ ein.",
                "$ lcc rag index\n$ lcc rag stats",
                "Index aktualisiert: 9 neu, 0 geändert, 0 unverändert, 0 entfernt – 9 Dateien, 26 Chunks\n"
                "Dateien: 9\nChunks: 26\nEmbedding-Modell: bge-m3\nDimension: 1024",
                "Standard-Quellen: ./docs und ~/rag-docs. Nach Änderungen einfach erneut indexieren – "
                "nur Geändertes wird neu berechnet.",
            ),
            Case(
                "Die Doku durchsuchen",
                "Sehen, welche Stellen zu einer Frage passen.",
                '$ lcc rag search "Wer gibt Deployments frei?"',
                "[1] docs/handbuch/betrieb.md:3-9 (score 0.54)\n## Deployment\n"
                "Neue Versionen von Kranich werden nur mittwochs …\n[2] …",
                "Jeder Treffer mit Datei, Zeilenbereich und Score. Gut zum Prüfen, bevor du fragst.",
            ),
            Case(
                "Fragen mit Quellen",
                "Eine Antwort, die nur in deiner Doku steht.",
                '$ lcc ask "Wann darf Kranich ausgerollt werden und wer gibt frei?"',
                "RAG: [1] docs/handbuch/betrieb.md:3-9, [2] …\nKranich wird nur mittwochs zwischen "
                "6:00 und 8:00 Uhr\nausgerollt; die Freigabe erteilt Tobias Reinhardt,\n"
                "in Vertretung Aylin Demir [1].",
                "[n] verweist auf die Quellen in der ersten Zeile. Kein Modell kennt diese Fakten – "
                "sie kommen aus docs/.",
            ),
            Case(
                "Englische Doku und Code",
                "Testen, was die Suche alles findet.",
                '$ lcc ask "Wie lange ist ein API-Schlüssel gültig?"\n'
                '$ lcc ask "Was kostet eine Expresssendung mit 2 kg?"\n'
                '$ lcc ask "Wie heißt der Hund von Tobias?"',
                "… 365 Tage [1]        # aus docs/english/api.md\n"
                "… 4,90 + 2 × 0,85 + 9,90 = 16,50 € [1]   # aus tarife.py\n"
                "… dazu steht nichts in der Dokumentation.",
                "Deutsche Fragen finden auch englische Texte. Die letzte Frage ist die Gegenprobe – "
                "das Modell soll nichts erfinden.",
                "Probier auch",
            ),
            Case(
                "RAG im Agenten und in der REPL",
                "lcc sucht selbst in der Doku, wenn es nötig ist.",
                '$ lcc run --no-small "Wie wechselt die Rufbereitschaft?"\n$ lcc\n› /rag Backups\n› /rag off',
                "→ rag_search(query='Rufbereitschaft Wechsel')\nJeden Freitag um 12:00 Uhr … [1]\n"
                "[1] docs/handbuch/betrieb.md:21-26 …\nRAG ist jetzt off.",
                "--no-rag schaltet RAG für einen Aufruf ab. Eigene Quellen: [rag] sources in der "
                "Config (Lektion 8).",
            ),
        ],
    ),
    Lesson(
        7,
        "Skills",
        "Ein Skill ist eine kurze Anleitung für genau eine Art von Aufgabe. lcc lädt ihn nur, "
        "wenn der Auftrag passt.",
        [
            "vorhandene Skills ansehen",
            "verstehen, welcher Skill geladen wird",
            "einen Skill arbeiten lassen",
            "einen nur lesenden Skill nutzen",
            "einen eigenen Skill schreiben (3 Fälle)",
        ],
        [
            Case(
                "Vorhandene Skills ansehen",
                "Wissen, welche Skills im Projekt bereitstehen.",
                "$ lcc skills\n$ lcc skills show changelog-eintrag",
                "abap-unit-test        Projekt  Legt eine ABAP-Unit-Testklasse an …\n"
                "changelog-eintrag     Projekt  Ergänzt CHANGELOG.md …\n"
                "commit-nachricht      Projekt  Formuliert eine Commit-Nachricht …\n…",
                "Das Modell sieht zunächst nur Name und Beschreibung – den Inhalt erst, wenn er passt. "
                "Das hält den Kontext klein.",
            ),
            Case(
                "Welcher Skill wird geladen?",
                "Vor dem Auftrag prüfen, was lcc wählen würde.",
                '$ lcc skills match "trag ins Changelog ein: Versand funktioniert jetzt"',
                "changelog-eintrag  1.00  Trigger 'changelog'  wird automatisch geladen\n"
                "commit-nachricht   0.49  Ähnlichkeit 0.49     im Systemprompt gelistet",
                "Trigger (Stichwort im Auftrag) → Score 1.0. Sonst zählt die Ähnlichkeit: ab 0.55 "
                "wird geladen, darunter nur gelistet.",
            ),
            Case(
                "Einen Skill arbeiten lassen",
                "Einen Eintrag ins CHANGELOG schreiben lassen.",
                '$ lcc run "trag ins Changelog ein: Versandkosten funktionieren jetzt mit Text-Gewicht"\n'
                "$ git diff CHANGELOG.md",
                "⚙ Skill: changelog-eintrag\nPlan: …\n## [Unreleased]\n+### Fixed\n"
                "+- Behebt die Versandkosten bei Gewicht als Text.",
                "⚙ zeigt, welcher Skill geladen wurde. Alte Einträge bleiben unverändert – so steht es "
                "im Skill unter „Nicht tun“.",
            ),
            Case(
                "Ein Skill, der nichts ändern darf",
                "Eine Commit-Nachricht vorschlagen lassen.",
                '$ git status\n$ lcc run "Schlag mir eine Commit-Nachricht für meine Änderungen vor"\n'
                "$ git status",
                "⚙ Skill: commit-nachricht\n→ run_shell(command='git status')\n"
                "→ run_shell(command='git diff …')\n```\nErgänze kuerzen() und erhöhe den Mindestbestand\n```",
                "Der Skill erlaubt nur run_shell und read_file – lcc schränkt die Werkzeuge ein. "
                "git status sieht danach genauso aus wie vorher.",
            ),
            Case(
                "Eigener Skill (1/3): Gerüst",
                "Einen Skill anlegen, der TODO-Kommentare sammelt.",
                "$ printf '\\n# TODO: Mindestbestand aus der Config lesen\\n' >> lager.py\n"
                "$ printf '\\n# TODO: Expresszuschlag ergänzen\\n' >> bestellung.py\n"
                "$ lcc skills new todo-sammeln",
                "Skill angelegt: ~/lcc-tutorial/.lcc/skills/todo-sammeln/SKILL.md",
                "Das Gerüst enthält schon alle Abschnitte: Ziel, Vorgehen, Regeln, Nicht tun, Ausgabe, "
                "Beispiel.",
            ),
            Case(
                "Eigener Skill (2/3): SKILL.md",
                "Beschreibung, Trigger, Werkzeuge und Schritte festlegen.",
                "---\nname: todo-sammeln\ndescription: Sammelt alle TODO-Kommentare in TODO.md.\n"
                '  Nutzen bei "TODOs sammeln", "offene Punkte".\n'
                "triggers: todo, todos, offene punkte\ntools: search_code, read_file, write_file\n---\n"
                "# TODOs sammeln\n## Vorgehen\n1. Suche mit `search_code` nach `TODO`.\n"
                "2. Schreibe `TODO.md` mit `write_file`.\n## Nicht tun\n- Code ändern.",
                "description  → was + wann; sieht das Modell immer\ntriggers     → sichere Stichwörter\n"
                "               (Wortgrenzen: todo ≠ todos)\ntools        → nur diese, solange aktiv\n"
                "Vorgehen     → nummerierte Schritte mit Tool-Namen\nNicht tun    → ausdrücklich nennen",
                "Kurz halten: ideal 1500–3000 Zeichen. Ein kurzes Beispiel am Ende hilft dem Modell "
                "mehr als jede Beschreibung.",
            ),
            Case(
                "Eigener Skill (3/3): prüfen und nutzen",
                "Den Skill testen – und arbeiten lassen.",
                '$ lcc skills check\n$ lcc skills match "Sammle alle TODOs im Projekt"\n'
                '$ lcc run "Sammle alle TODOs im Projekt"\n$ cat TODO.md',
                "0 Fehler, 0 Warnungen in 7 Skills\ntodo-sammeln  1.00  Trigger 'todos'\n"
                "⚙ Skill: todo-sammeln\n- [ ] bestellung.py:26 – Expresszuschlag ergänzen\n"
                "- [ ] lager.py:25 – Mindestbestand aus der Config lesen",
                "Für alle Projekte: lcc skills new <name> --user → ~/.config/lcc/skills/. "
                "Projekt-Skills haben Vorrang.",
            ),
        ],
        extra_html="""
  <div class="kicker">Lektion 7 · Spickzettel</div>
  <h2>Faustregeln für gute Skills</h2>
  <div class="grid2">
    <ul>
      <li><b>Ein Skill = eine Aufgabe.</b> Lieber drei kleine als einen großen.</li>
      <li><b>Kurz:</b> ideal 1500–3000 Zeichen.</li>
      <li><b>Nummerierte Schritte</b> mit klaren Verben und Tool-Namen.</li>
      <li><b>Ein kurzes Beispiel</b> schlägt jede Beschreibung.</li>
    </ul>
    <ul>
      <li><b>„Nicht tun“</b> ausdrücklich nennen.</li>
      <li><b>Trigger mit Bedacht</b> – zu allgemeine laden ständig.</li>
      <li><b><code>tools</code> einschränken</b>, wenn nichts geändert werden soll.</li>
      <li><b><code>checks</code></b> nur mit Befehlen aus der Allowlist.</li>
    </ul>
  </div>""",
    ),
    Lesson(
        8,
        "lcc anpassen",
        "Einstellungen fürs Projekt oder für dich – ohne Code zu ändern.",
        [
            "sehen, welche Einstellung woher kommt",
            "die Allowlist erweitern",
            "Projektregeln für das Modell festlegen",
        ],
        [
            Case(
                "Woher kommt eine Einstellung?",
                "Die wirksame Config mit Herkunft jedes Werts sehen.",
                "$ lcc config show | less",
                '[ollama]\nbase_url = "http://192.168.178.79:11434"  # Default\n[models]\n'
                'code = "qwen3.5:9b"  # Default\nembed = "bge-m3"  # Default',
                "Reihenfolge: Defaults → ~/.config/lcc/config.toml → ./.lcc/config.toml → --config → "
                "Umgebung → Flags. lcc config init legt die Benutzer-Config an.",
            ),
            Case(
                "Die Allowlist erweitern",
                "python main.py ohne Rückfrage erlauben – nur in diesem Projekt.",
                '$ cat > .lcc/config.toml <<\'EOF\'\n[agent]\nshell_allowlist = ["ls", "cat", "rg", "grep",\n'
                '  "git status", "git diff", "pytest", "python -m pytest",\n'
                '  "python -m py_compile", "python main.py"]\nEOF\n$ lcc config show | grep shell_allowlist',
                'shell_allowlist = [… "python main.py"]  # …/.lcc/config.toml',
                "Verglichen wird der Anfang des Befehls: python main.py erlaubt genau diesen Aufruf, "
                "nicht python anderes.py.",
            ),
            Case(
                "Projektregeln für das Modell",
                "Dem Modell Hausregeln mitgeben, die immer gelten.",
                "$ cat > .lcc/AGENT.md <<'EOF'\n- Schreibe Kommentare auf Deutsch.\n"
                "- Nutze Typannotationen bei neuen Funktionen.\n"
                "- Beträge immer in Euro mit zwei Nachkommastellen.\nEOF",
                "# Ab jetzt hängt lcc diese Regeln an jeden\n# Systemprompt in diesem Projekt.",
                "Kurz halten – kleine Modelle lesen jedes Wort. Für Aufgaben-Anleitungen sind Skills "
                "besser geeignet.",
            ),
        ],
    ),
    Lesson(
        9,
        "lcc in Skripten",
        "Mit --json liefert lcc maschinenlesbare Ereignisse – für Skripte und Pipelines.",
        ["JSON-Ereignisse ausgeben und filtern", "am Exit-Code erkennen, ob es geklappt hat"],
        [
            Case(
                "JSON-Ereignisse",
                "Eine Antwort maschinenlesbar weiterverarbeiten.",
                '$ lcc --json ask "Antworte nur mit: ok" | tail -1\n'
                '$ lcc --json run --yes "Sammle alle TODOs" \\\n    | jq -c \'select(.type=="check")\'',
                '{"type": "final", "content": "ok", "model": "qwen3.5:9b", …}\n'
                '{"type": "check", "command": "python -m pytest -q", "ok": true, …}',
                "Typen: token, tool_call, tool_result, plan, step, check, info, final, error. Ohne "
                "Terminal fragt lcc nie – Schreiben nur mit --yes.",
            ),
            Case(
                "Hat es geklappt?",
                "Den Exit-Code im Skript auswerten.",
                '$ lcc run --yes "…"; echo "exit=$?"',
                "exit=0     ok\nexit=1     nicht erfolgreich (z. B. Checks rot)\nexit=2     Config-Fehler\n"
                "exit=3     Server nicht erreichbar\nexit=4     Modell fehlt\nexit=130   Abbruch mit Strg-C",
                "Bei exit=1 nach Änderungen: git diff ansehen, ggf. lcc undo.",
            ),
        ],
    ),
]

CHEATSHEET = """
  <div class="kicker">Lektion 10</div>
  <h2>Wenn etwas hakt</h2>
  <table>
    <tr><th>Problem</th><th>Lösung</th></tr>
    <tr><td>Server nicht erreichbar (Exit 3)</td><td><code>lcc doctor</code>, URL in <code>lcc config show</code>, <code>--url</code></td></tr>
    <tr><td>Modell fehlt (Exit 4)</td><td>auf dem Server <code>ollama pull &lt;modell&gt;</code></td></tr>
    <tr><td>falscher Ordner</td><td><code>lcc config show | grep -A1 workspace</code> – lcc nutzt den Git-Root</td></tr>
    <tr><td>Modell rät statt zu lesen</td><td>Datei im Auftrag nennen oder <code>/add datei</code></td></tr>
    <tr><td>Änderung gefällt nicht</td><td><code>lcc undo</code> oder <code>git checkout -- datei</code></td></tr>
    <tr><td>Befehl abgelehnt</td><td>Allowlist erweitern (Lektion 8) oder im Terminal bestätigen</td></tr>
    <tr><td>Skill lädt nicht</td><td><code>lcc skills match "…"</code> – Trigger ergänzen</td></tr>
    <tr><td>RAG findet nichts</td><td><code>lcc rag stats</code>, <code>lcc rag index</code>, nach Modellwechsel <code>--rebuild</code></td></tr>
    <tr><td>langsam</td><td>für Fragen <code>lcc ask</code> oder <code>--no-small</code></td></tr>
  </table>"""

# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_code(text: str) -> str:
    """Färbt Zeilen nach ihrem Anfang ein (Befehl, Kommentar, ok, Fehler, Info, Rückfrage)."""
    lines = []
    for raw in text.split("\n"):
        line = html.escape(raw)
        stripped = raw.lstrip()
        if raw.startswith("$ "):
            lines.append(f'<span class="cmd">{html.escape(raw[2:])}</span>')
        elif raw.startswith("› "):
            lines.append(
                f'<span class="repl">›</span> <span class="cmd-plain">{html.escape(raw[2:])}</span>'
            )
        elif stripped.startswith("# ") and not stripped.startswith("# TODO"):
            lines.append(f'<span class="cm">{line}</span>')
        elif stripped.startswith(("✓", "+")) and not stripped.startswith("+++"):
            lines.append(f'<span class="ok">{line}</span>')
        elif stripped.startswith(("✗", "-")) and not stripped.startswith(("---", "- ")):
            lines.append(f'<span class="bad">{line}</span>')
        elif stripped.startswith(("→", "⚙", "▶", "↻", "⠹", "Kleinmodell-Modus", "RAG:")):
            lines.append(f'<span class="info">{line}</span>')
        elif "[j]a" in raw or "[Enter]" in raw or raw.startswith("> "):
            lines.append(f'<span class="warn">{line}</span>')
        elif stripped.startswith("↳"):
            lines.append(f'<span class="muted">{line}</span>')
        else:
            lines.append(line)
    return "\n".join(lines)


def slide(body: str, cls: str = "") -> str:
    return f'<section class="slide {cls}">{body}\n</section>'


def title_slide() -> str:
    return slide(
        """
  <div class="kicker">Tutorial</div>
  <h1>lcc<br><span class="muted" style="font-size:48px">local code cli</span></h1>
  <p style="font-size:26px;max-width:900px">Eine Coding-CLI, die nur mit deinem lokalen Ollama-Server
  arbeitet – Schritt für Schritt, ein Fall pro Folie.</p>
  <p style="margin-top:24px"><span class="badge">qwen3.5:9b</span><span class="badge">bge-m3</span>
  <span class="badge">kein Cloud-Modell</span><span class="badge">keine Telemetrie</span></p>
  <p class="muted small" style="margin-top:40px">Blättern mit den Buttons unten oder ← / → · F für Vollbild</p>""",
        "title-slide",
    )


def overview_slide() -> str:
    cards = [
        ("Fragen", "<code>lcc ask</code> – Antworten ohne Werkzeuge, auch zu Dateien per Pipe."),
        ("Code", "<code>lcc run</code> – liest, sucht, ändert Dateien. Mit Diff &amp; Rückfrage."),
        ("Interaktiv", "<code>lcc</code> – REPL mit Verlauf und Slash-Befehlen."),
        ("RAG", "Eigene Doku durchsuchen und mit Quellen <code>[n]</code> zitieren."),
        ("Skills", "Kleine Anleitungen, die lcc nur bei Bedarf lädt."),
        ("Kleine Modelle", "Plan → Schritte → Prüfen → Reparieren statt langer Prompts."),
    ]
    inner = "".join(f'<div class="card"><h3>{t}</h3><p>{d}</p></div>' for t, d in cards)
    return slide(
        f"""
  <div class="kicker">Überblick</div>
  <h2>Was lcc kann</h2>
  <div class="grid3">{inner}</div>
  <div class="tip"><b>So ist das Tutorial aufgebaut:</b> je Lektion eine Einstiegsfolie, dann ein Fall pro
  Folie – mit Ziel, Befehl, Ergebnis und dem Wichtigsten zum Merken.</div>"""
    )


def agenda_slide() -> str:
    items = "".join(
        f'<li><span class="no">{lesson.number}</span><span>{html.escape(lesson.title)}</span>'
        f'<span class="count">{len(lesson.cases)} Fälle</span></li>'
        for lesson in LESSONS
    )
    items += '<li><span class="no">10</span><span>Wenn etwas hakt</span><span class="count">Spickzettel</span></li>'
    return slide(
        f"""
  <div class="kicker">Agenda</div>
  <h2>Elf Lektionen, ein Übungsprojekt</h2>
  <ol class="agenda">{items}</ol>"""
    )


def lesson_intro(lesson: Lesson) -> str:
    learn = "".join(f"<li>{html.escape(item)}</li>" for item in lesson.learn)
    return slide(
        f"""
  <div class="lesson-no">{lesson.number}</div>
  <div class="kicker">Lektion {lesson.number}</div>
  <h1 style="font-size:60px">{html.escape(lesson.title)}</h1>
  <p style="font-size:26px;max-width:960px">{html.escape(lesson.intro)}</p>
  <h3 style="margin-top:18px">Das lernst du</h3>
  <ol class="learn">{learn}</ol>""",
        "intro-slide",
    )


def case_slide(lesson: Lesson, index: int, case: Case) -> str:
    total = len(lesson.cases)
    return slide(
        f"""
  <div class="kicker">Lektion {lesson.number} · {html.escape(lesson.title)}
    <span class="step">Fall {index} / {total}</span></div>
  <h2>{html.escape(case.title)}</h2>
  <p class="goal"><b>Ziel:</b> {html.escape(case.goal)}</p>
  <div class="case">
    <div class="pane"><div class="label">Du tippst</div><pre>{render_code(case.typed)}</pre></div>
    <div class="pane"><div class="label">Du siehst</div><pre>{render_code(case.seen)}</pre></div>
  </div>
  <div class="tip"><b>{html.escape(case.note_label)}:</b> {html.escape(case.note)}</div>"""
    )


def end_slide() -> str:
    return slide(
        """
  <div class="kicker">Wie geht es weiter?</div>
  <h2 style="font-size:52px">Jetzt du.</h2>
  <ol class="learn" style="max-width:1000px">
    <li>Übungen: <code>UEBUNGEN.md</code> im Projekt – je eine Aufgabe pro Skill</li>
    <li>Eigenes Projekt: <code>cd mein-projekt &amp;&amp; lcc doctor &amp;&amp; lcc</code></li>
    <li>Skills für deine wiederkehrenden Aufgaben schreiben</li>
    <li>Doku nach <code>./docs</code> oder <code>~/rag-docs</code> legen und indexieren</li>
    <li>Nachschlagen: <code>README.md</code> · Mitmachen: <code>TUTORIAL.md</code></li>
  </ol>""",
        "title-slide",
    )


def build() -> str:
    slides = [title_slide(), overview_slide(), agenda_slide()]
    for lesson in LESSONS:
        slides.append(lesson_intro(lesson))
        slides += [case_slide(lesson, i, case) for i, case in enumerate(lesson.cases, 1)]
        if lesson.extra_html:
            slides.append(slide(lesson.extra_html))
    slides.append(slide(CHEATSHEET))
    slides.append(end_slide())
    return TEMPLATE.replace("<!--SLIDES-->", "\n\n".join(slides))


TEMPLATE = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>lcc – Tutorial</title>
<!-- Erzeugt von slides/build_slides.py – bitte dort ändern. -->
<style>
  :root {
    --bg: #0f1419; --panel: #161d26; --panel-2: #1c2531; --text: #e6e9ee; --muted: #9aa5b4;
    --accent: #5cc8ff; --accent-2: #7ee0a1; --warn: #ffcf6b; --err: #ff7b72; --border: #2a3542;
    --mono: "JetBrains Mono", "Fira Code", "DejaVu Sans Mono", Menlo, Consolas, monospace;
    --sans: "Inter", "Segoe UI", "DejaVu Sans", system-ui, sans-serif;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: #070a0d; color: var(--text); font-family: var(--sans); }
  #viewport { position: fixed; inset: 0 0 64px 0; display: flex; align-items: center; justify-content: center; overflow: hidden; }
  #stage { width: 1280px; height: 720px; position: relative; transform-origin: center center; }
  section.slide { position: absolute; inset: 0; padding: 48px 64px 60px; background: var(--bg); border-radius: 14px;
    display: none; flex-direction: column; overflow: hidden; box-shadow: 0 20px 60px rgba(0,0,0,.5); }
  section.slide.active { display: flex; }
  .kicker { color: var(--accent); font-size: 17px; letter-spacing: .1em; text-transform: uppercase; font-weight: 600;
    margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }
  .kicker .step { font-family: var(--mono); letter-spacing: 0; text-transform: none; color: var(--muted);
    background: var(--panel-2); border: 1px solid var(--border); border-radius: 999px; padding: 3px 12px; font-size: 15px; }
  h1 { font-size: 64px; margin: 0 0 16px; line-height: 1.05; }
  h2 { font-size: 38px; margin: 0 0 10px; line-height: 1.15; }
  h3 { font-size: 21px; margin: 0 0 10px; color: var(--accent-2); }
  p, li { font-size: 22px; line-height: 1.45; }
  p { margin: 0 0 12px; }
  ul, ol { margin: 0 0 12px; padding-left: 28px; }
  li { margin-bottom: 6px; }
  .muted { color: var(--muted); }
  .small { font-size: 18px; }
  code { font-family: var(--mono); font-size: .88em; background: var(--panel-2); padding: 1px 6px; border-radius: 5px; color: #cfe8ff; }
  .goal { font-size: 21px; color: var(--muted); margin-bottom: 16px; }
  .goal b { color: var(--text); }
  .case { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; flex: 1; min-height: 0; }
  .pane { display: flex; flex-direction: column; min-height: 0; }
  .label { font-size: 14px; text-transform: uppercase; letter-spacing: .1em; color: var(--muted); margin-bottom: 6px; font-weight: 600; }
  pre { font-family: var(--mono); font-size: 16px; line-height: 1.45; background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 14px 18px; margin: 0; white-space: pre-wrap; color: #d6dde6; flex: 1; overflow: hidden; }
  .cmd { color: var(--accent); } .cmd::before { content: "$ "; color: var(--muted); }
  .cmd-plain { color: var(--accent); } .repl { color: var(--muted); }
  .cm { color: #6b7a8c; } .ok { color: var(--accent-2); } .bad { color: var(--err); }
  .warn { color: var(--warn); } .info { color: var(--accent); }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; }
  .grid3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px; }
  .card p { font-size: 19px; }
  table { border-collapse: collapse; width: 100%; font-size: 19px; }
  th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }
  th { color: var(--muted); font-weight: 600; font-size: 15px; text-transform: uppercase; letter-spacing: .06em; }
  .tip { margin-top: 16px; background: rgba(92,200,255,.08); border-left: 4px solid var(--accent); padding: 12px 18px;
    border-radius: 6px; font-size: 19px; line-height: 1.4; }
  .tip b { color: var(--accent); }
  .title-slide, .intro-slide { justify-content: center; background: radial-gradient(circle at 80% 20%, #1b3346 0%, var(--bg) 55%); }
  .title-slide h1 { font-size: 88px; }
  .badge { display: inline-block; font-family: var(--mono); font-size: 16px; padding: 4px 10px; border-radius: 999px;
    border: 1px solid var(--border); color: var(--muted); margin-right: 8px; }
  .lesson-no { position: absolute; right: 64px; top: 40px; font-family: var(--mono); color: #22303e; font-size: 200px; font-weight: 700; line-height: 1; }
  ol.learn { list-style: none; padding: 0; counter-reset: learn; }
  ol.learn li { counter-increment: learn; padding-left: 44px; position: relative; font-size: 24px; }
  ol.learn li::before { content: counter(learn); position: absolute; left: 0; top: 2px; width: 30px; height: 30px; border-radius: 50%;
    background: var(--panel-2); border: 1px solid var(--border); color: var(--accent); font: 600 16px/30px var(--mono); text-align: center; }
  ol.agenda { list-style: none; padding: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 10px 32px; margin-top: 12px; }
  ol.agenda li { display: grid; grid-template-columns: 52px 1fr auto; align-items: center; background: var(--panel);
    border: 1px solid var(--border); border-radius: 10px; padding: 10px 16px; font-size: 22px; margin: 0; }
  ol.agenda .no { font-family: var(--mono); color: var(--accent); font-weight: 700; font-size: 24px; }
  ol.agenda .count { color: var(--muted); font-size: 15px; font-family: var(--mono); }
  footer.bar { position: absolute; left: 64px; right: 64px; bottom: 20px; display: flex; justify-content: space-between;
    color: #4f5d6d; font-size: 14px; font-family: var(--mono); }
  #progress { position: fixed; left: 0; bottom: 0; height: 4px; background: var(--accent); transition: width .2s; }
  #help { position: fixed; right: 14px; bottom: 12px; color: #3f4b58; font: 12px var(--mono); }
  #nav { position: fixed; left: 50%; bottom: 14px; transform: translateX(-50%); display: flex; align-items: center; gap: 10px;
    background: rgba(22,29,38,.92); border: 1px solid var(--border); border-radius: 999px; padding: 6px;
    box-shadow: 0 8px 24px rgba(0,0,0,.45); backdrop-filter: blur(6px); z-index: 10; user-select: none; }
  #nav button { font: 600 15px var(--sans); color: var(--text); background: var(--panel-2); border: 1px solid var(--border);
    border-radius: 999px; padding: 8px 18px; cursor: pointer; display: flex; align-items: center; gap: 8px;
    transition: background .15s, border-color .15s, color .15s, transform .1s; }
  #nav button:hover:not(:disabled) { background: #22303e; border-color: var(--accent); color: var(--accent); }
  #nav button:active:not(:disabled) { transform: scale(.96); }
  #nav button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  #nav button:disabled { opacity: .35; cursor: default; }
  #nav button.next { background: var(--accent); color: #062033; border-color: var(--accent); }
  #nav button.next:hover:not(:disabled) { background: #7fd6ff; color: #062033; }
  #nav .arrow { font-size: 18px; line-height: 1; }
  #nav .pos { font: 14px var(--mono); color: var(--muted); min-width: 64px; text-align: center; }
  @media print {
    html, body { background: white; }
    #viewport { position: static; display: block; }
    #stage { transform: none !important; width: auto; height: auto; }
    section.slide { display: flex !important; position: relative; width: 1280px; height: 720px; page-break-after: always;
      box-shadow: none; border-radius: 0; }
    #progress, #help, #nav { display: none; }
  }
</style>
</head>
<body>
<div id="viewport"><div id="stage">
<!--SLIDES-->
</div></div>
<div id="progress"></div>
<nav id="nav" aria-label="Folien-Navigation">
  <button type="button" class="prev" id="prev" title="Vorherige Folie (←)"><span class="arrow">‹</span>Zurück</button>
  <span class="pos" id="pos">1 / 1</span>
  <button type="button" class="next" id="next" title="Nächste Folie (→)">Weiter<span class="arrow">›</span></button>
</nav>
<div id="help">← → · F Vollbild · P Drucken</div>
<script>
(function () {
  const slides = Array.from(document.querySelectorAll("section.slide"));
  const stage = document.getElementById("stage");
  const progress = document.getElementById("progress");
  let index = 0;
  slides.forEach((slide, i) => {
    const bar = document.createElement("footer");
    bar.className = "bar";
    bar.innerHTML = "<span>lcc · Tutorial</span><span>" + (i + 1) + "</span>";
    slide.appendChild(bar);
  });
  function fit() {
    // unten 64 px frei für die Navigationsleiste
    const scale = Math.min(window.innerWidth / 1280, (window.innerHeight - 64) / 720) * 0.98;
    stage.style.transform = "scale(" + scale + ")";
  }
  const prev = document.getElementById("prev");
  const next = document.getElementById("next");
  const pos = document.getElementById("pos");
  function show(i) {
    index = Math.max(0, Math.min(slides.length - 1, i));
    slides.forEach((s, j) => s.classList.toggle("active", j === index));
    progress.style.width = ((index + 1) / slides.length * 100) + "%";
    pos.textContent = (index + 1) + " / " + slides.length;
    prev.disabled = index === 0;
    next.disabled = index === slides.length - 1;
    if (location.hash !== "#" + (index + 1)) history.replaceState(null, "", "#" + (index + 1));
  }
  prev.addEventListener("click", () => show(index - 1));
  next.addEventListener("click", () => show(index + 1));
  document.addEventListener("keydown", (e) => {
    if (e.target.closest && e.target.closest("button") && (e.key === " " || e.key === "Enter")) return;
    if (["ArrowRight", "PageDown", " "].includes(e.key)) { e.preventDefault(); show(index + 1); }
    else if (["ArrowLeft", "PageUp", "Backspace"].includes(e.key)) { e.preventDefault(); show(index - 1); }
    else if (e.key === "Home") show(0);
    else if (e.key === "End") show(slides.length - 1);
    else if (e.key === "f" || e.key === "F") {
      if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen();
    } else if (e.key === "p" || e.key === "P") window.print();
  });
  window.addEventListener("resize", fit);
  fit();
  const start = parseInt(location.hash.slice(1), 10);
  show(Number.isFinite(start) ? start - 1 : 0);
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"{OUT} geschrieben")
