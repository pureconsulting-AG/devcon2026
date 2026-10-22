"""Nutzertexte (Deutsch). Alle sichtbaren Meldungen werden hier gesammelt."""

from __future__ import annotations

# Config
CONFIG_TOML_ERROR = "Config-Fehler in {path}: ungültiges TOML ({error})"
CONFIG_FILE_MISSING = "Config-Datei nicht gefunden: {path}"
CONFIG_TYPE_ERROR = (
    "Config-Fehler in {source}: '{key}' muss vom Typ {expected} sein, ist aber {actual}"
)
CONFIG_ENUM_ERROR = (
    "Config-Fehler in {source}: '{key}' muss einer von {allowed} sein, ist aber {value!r}"
)
CONFIG_URL_ERROR = (
    "Config-Fehler in {source}: '{key}' = {value!r} braucht ein Schema (z. B. http://host:11434)"
)
CONFIG_UNKNOWN_KEY = "Warnung: unbekannter Config-Key '{key}' in {source}"
CONFIG_UNKNOWN_KEY_HINT = " – meintest du '{suggestion}'?"
CONFIG_SOURCE_DEFAULT = "Default"
CONFIG_SOURCE_ENV = "Umgebung {name}"
CONFIG_SOURCE_CLI = "CLI {flag}"
CONFIG_INIT_EXISTS = "{path} existiert bereits – mit --force überschreiben."
CONFIG_INIT_DONE = "Config geschrieben: {path}"
CONFIG_SHOW_FILES = "Geladene Config-Dateien:"
CONFIG_SHOW_NO_FILES = "Keine Config-Dateien gefunden – es gelten die Defaults."

# Allgemein

# Ollama
OLLAMA_UNREACHABLE = "Ollama-Server nicht erreichbar: {url} ({error})"
OLLAMA_MODEL_MISSING = (
    "Modell '{model}' fehlt auf dem Server {url}. Auf dem Server ausführen: ollama pull {model}"
)
OLLAMA_HTTP_ERROR = "Ollama-Fehler (HTTP {status}): {error}"
OLLAMA_STREAM_ERROR = "Ollama-Fehler während der Generierung: {error}"
OLLAMA_TIMEOUT = "Zeitüberschreitung beim Warten auf {url} – ggf. [ollama].timeout_seconds erhöhen"
OLLAMA_BAD_RESPONSE = "Unerwartete Antwort von Ollama ({path})"

# doctor
DOCTOR_SERVER = "Server"
DOCTOR_SERVER_OK = "{url} erreichbar, {count} Modelle"
DOCTOR_MODEL = "Modell {name} ({roles})"
DOCTOR_PULL_HINT = "fehlt – auf dem Server ausführen: ollama pull {model}"
DOCTOR_TOOLS = "Tool-Calling ({model})"
DOCTOR_TOOLS_PROMPT = "Rufe das Tool echo mit text='ok' auf. Antworte nur mit dem Tool-Aufruf."
DOCTOR_TOOLS_OK = "native tool_calls funktionieren"
DOCTOR_TOOLS_NONE = "keine nativen tool_calls erhalten – Text-Tool-Modus (Fallback-Parser) nötig"
DOCTOR_TOOLS_TEXT_MODE = "Modell meldet keine 'tools'-Fähigkeit – Text-Tool-Modus"
DOCTOR_EMBED = "Embedding ({model})"
DOCTOR_EMBED_OK = "Dimension {dimension}"
DOCTOR_SKIPPED_MISSING = "übersprungen, Modell fehlt"
DOCTOR_RUNNING = "Prüfe {url} …"
DOCTOR_TABLE_TITLE = "Konfigurierte Modelle"
DOCTOR_COL_MODEL = "Modell"
DOCTOR_COL_ROLES = "Rollen"
DOCTOR_COL_SIZE = "Größe"
DOCTOR_COL_TOOLS = "Tools"
DOCTOR_COL_THINKING = "Thinking"
YES = "ja"
NO = "nein"
UNKNOWN = "?"

# models
MODELS_TITLE = "Modelle auf {url}"
MODELS_COL_NAME = "Name"
MODELS_COL_PARAMS = "Parameter"
MODELS_COL_QUANT = "Quant."
MODELS_COL_SIZE = "Datei"
MODELS_COL_ROLES = "in Config"
MODELS_MISSING = "In der Config, aber nicht auf dem Server: {model} ({roles}) – ollama pull {model}"

# ask
ASK_NO_INPUT = 'Keine Frage angegeben. Beispiel: lcc ask "Was macht git rebase?"'
ASK_WITH_STDIN = "{question}\n\nKontext (stdin):\n```\n{stdin}\n```"
ABORTED = "Abgebrochen."

# Sandbox / Tools (Texte gehen als Tool-Ergebnis an das Modell)
SANDBOX_OUTSIDE = "Zugriff verweigert: '{path}' liegt außerhalb des Workspace {root}"
TOOL_UNKNOWN = "Fehler: unbekanntes Tool '{name}'. Verfügbar: {available}"
TOOL_BAD_ARGS = "Fehler: ungültige Argumente für {name}: {problems}. Beispiel: {example}"
TOOL_ARG_MISSING = "'{arg}' fehlt"
TOOL_ARG_UNKNOWN = "'{arg}' ist unbekannt"
TOOL_ARG_TYPE = "'{arg}' muss {expected} sein"
TOOL_FAILED = "Fehler: {error}"
TOOL_TRUNCATED = "\n… [{count} Zeichen gekürzt] …\n"
TOOL_NOT_FOUND = "Datei oder Ordner nicht gefunden: {path}"
TOOL_NOT_A_DIR = "Kein Ordner: {path}"
TOOL_NOT_A_FILE = "Keine Datei: {path}"
TOOL_BINARY = "Binärdatei, kann nicht als Text gelesen werden: {path}"
TOOL_READ_HEADER = "{path} (Zeilen {start}-{end} von {total})"
TOOL_READ_EMPTY = "{path} ist leer"
TOOL_READ_RANGE = "Zeilenbereich {start}-{end} liegt außerhalb der Datei ({total} Zeilen)"
TOOL_READ_TRUNCATED_HINT = "\n[gekürzt – nutze start_line/end_line für den Rest]"
TOOL_DIR_EMPTY = "{path} ist leer"
TOOL_SEARCH_NONE = "Keine Treffer für {pattern!r}"
TOOL_SEARCH_BAD_REGEX = "Ungültiger regulärer Ausdruck {pattern!r}: {error}"
TOOL_SEARCH_LIMIT = "[nur die ersten {limit} Treffer]"

# Agent
AGENT_MAX_STEPS = "Maximale Anzahl Tool-Runden ({max_steps}) erreicht – Auftrag ggf. aufteilen."
AGENT_REPEATED_CALL = "Abbruch: das Modell hat {name} dreimal hintereinander gleich aufgerufen."
RUN_NO_TASK = 'Kein Auftrag angegeben. Beispiel: lcc run "Erkläre die Struktur von cli.py"'
TOOL_RESULT_LINES = "  ↳ {lines} Zeilen"
SANDBOX_GIT = "Zugriff verweigert: in .git/ darf nicht geschrieben werden ({path})"
SANDBOX_UNDO_DIR = "Zugriff verweigert: .lcc/undo/ ist für Backups reserviert ({path})"

# Schreiben / Shell
CONFIRM_PROMPT = "[j]a / [n]ein / [i]mmer für diese Session: "
CONFIRM_WRITE = "Änderung an {path}:"
CONFIRM_NO_CHANGES = "(keine inhaltliche Änderung)"
CONFIRM_SHELL = "Shell-Befehl ausführen: {command}"
WRITE_DENIED = (
    "Abgelehnt: Schreiben von {path} wurde nicht bestätigt. "
    "Frag den Nutzer oder schlage die Änderung in der Antwort vor."
)
WRITE_DENIED_NON_TTY = (
    "Abgelehnt: Schreiben von {path} braucht eine Bestätigung, aber es gibt kein Terminal "
    "(lcc run --yes erlaubt Schreiben)."
)
WRITE_DONE_NEW = "Neu angelegt: {path} ({lines} Zeilen)"
WRITE_DONE = "Geschrieben: {path} ({lines} Zeilen)"
WRITE_UNCHANGED = "Keine Änderung: {path} hat bereits diesen Inhalt"
EDIT_DONE = "Geändert: {path} (Zeilen {start}-{end})"
EDIT_NOT_FOUND = (
    "old_str kommt in {path} nicht vor. Lies die Datei mit read_file und kopiere den Text exakt "
    "(ohne Zeilennummern)."
)
EDIT_AMBIGUOUS = (
    "old_str kommt in {path} {count}-mal vor (Zeilen {lines}). Nimm mehr umgebende Zeilen "
    "in old_str auf, damit es eindeutig ist."
)
EDIT_EMPTY = "old_str darf nicht leer sein. Für neue Dateien nutze write_file."
EDIT_SAME = "old_str und new_str sind identisch – nichts zu tun."
SHELL_PARSE_ERROR = "Befehl kann nicht zerlegt werden: {error}"
SHELL_EMPTY = "Leerer Befehl"
SHELL_DENIED = "Abgelehnt: der Nutzer hat '{command}' nicht bestätigt."
SHELL_DENIED_NON_TTY = (
    "Abgelehnt: '{command}' steht nicht auf der Allowlist und es gibt kein Terminal für "
    "eine Bestätigung. Erlaubt ohne Rückfrage: {allowlist}"
)
SHELL_NOT_FOUND = "Befehl nicht gefunden: {program}"
SHELL_TIMEOUT = "Zeitüberschreitung nach {seconds:g} s: {command}"
SHELL_RESULT = "exit code: {code}\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
UNDO_NOTHING = "Nichts zum Zurücknehmen."
UNDO_RESTORED = "Zurückgenommen: {path} wiederhergestellt."
UNDO_DELETED = "Zurückgenommen: {path} gelöscht (war neu angelegt)."

# Sessions
SESSION_NOT_FOUND = "Session '{ref}' nicht gefunden. /load ohne Argument listet alle."
SESSION_AMBIGUOUS = "'{ref}' passt auf {count} Sessions – bitte genauer angeben."
SESSION_BROKEN = "Session-Datei {path} ist in Zeile {line} beschädigt."
SESSION_BAD_NAME = "Ungültiger Session-Name: {name!r}"

# REPL
REPL_PROMPT = "› "
REPL_WELCOME = "lcc – Modell {model} auf {url}. /help zeigt die Befehle, Esc+Enter für neue Zeile."
REPL_BYE = "Tschüss."
REPL_CTRL_C_HINT = "Nochmal Strg-C (oder /exit) zum Beenden."
REPL_INTERRUPTED = "Abgebrochen – die unterbrochene Antwort wurde nicht in den Verlauf übernommen."
REPL_NO_TTY = (
    'Der interaktive Modus braucht ein Terminal. Für Skripte: lcc run "…" oder lcc ask "…".'
)
REPL_UNKNOWN_COMMAND = "Unbekannter Befehl {command}."
REPL_DID_YOU_MEAN = " Meintest du {command}?"
REPL_HELP_HEADER = "Befehle:"
REPL_HELP_KEYS = "Tasten: Esc+Enter neue Zeile · Strg-C bricht die Antwort ab · 2× Strg-C beendet"
REPL_CLEARED = "Verlauf geleert, neue Session."
REPL_CURRENT_MODEL = "Aktuelles Modell: {model}"
REPL_MODEL_SET = "Modell für diese Session: {model}"
REPL_RAG_STATE = "RAG ist jetzt {state}."
REPL_ADD_USAGE = "Nutzung: /add <datei>"
REPL_ADDED = "Angehängt an die nächste Nachricht: {header}"
REPL_NO_CHANGES = "Keine Änderungen in dieser Session."
REPL_SAVED = "Session gespeichert: {path}"
REPL_NO_SESSIONS = "Keine gespeicherten Sessions."
REPL_SESSION_LINE = "  {id}  {modified}  {messages} Nachrichten"
REPL_LOADED = "Session {id} geladen ({messages} Nachrichten)."

HELP_HELP = "diese Hilfe"
HELP_EXIT = "beenden"
HELP_CLEAR = "Verlauf leeren"
HELP_MODEL = "Modell anzeigen/wechseln: /model <name>"
HELP_MODELS = "Modelle auf dem Server"
HELP_RAG = "RAG durchsuchen: /rag <frage> · /rag on|off"
HELP_SKILL = "Skill laden: /skill <name>"
HELP_SKILLS = "verfügbare Skills"
HELP_ADD = "Datei an die nächste Nachricht anhängen"
HELP_DIFF = "Änderungen dieser Session"
HELP_UNDO = "letzte Dateiänderung zurücknehmen"
HELP_SAVE = "Session speichern: /save [name]"
HELP_LOAD = "Session laden: /load <id> (ohne id: Liste)"
HELP_CONFIG = "effektive Config"

# Statusanzeige
STATUS_WAITING = "denkt nach …"
STATUS_THINKING = "überlegt …"

# RAG
RAG_MODEL_MISMATCH = (
    "Der Index wurde mit dem Embedding-Modell '{stored}' gebaut, konfiguriert ist '{current}'. "
    "Neu aufbauen: lcc rag index --rebuild"
)
RAG_DIMENSION_MISMATCH = (
    "Embedding-Dimension passt nicht zum Index ({stored} statt {current}). "
    "Neu aufbauen: lcc rag index --rebuild"
)
RAG_NO_INDEX = "Noch kein RAG-Index ({path}). Anlegen mit: lcc rag index"
RAG_DISABLED = "RAG ist abgeschaltet ([rag].enabled = false oder --no-rag)."
RAG_NO_EMBED_MODEL = "Kein Embedding-Modell konfiguriert ([models].embed)."
RAG_NO_SOURCES = "Keine RAG-Quellen gefunden. Geprüft: {sources}"
RAG_INDEXING = "Indexiere"
RAG_INDEX_DONE = (
    "Index aktualisiert: {added} neu, {updated} geändert, {unchanged} unverändert, "
    "{removed} entfernt – {documents} Dateien, {chunks} Chunks"
)
RAG_SKIPPED = "Übersprungen (binär oder zu groß): {count} Dateien"
RAG_NO_HITS = "Keine Treffer über min_score {min_score} für {query!r}."
RAG_STATS = (
    "Index: {path}\nDateien: {documents}\nChunks: {chunks}\n"
    "Embedding-Modell: {model}\nDimension: {dimension}"
)
RAG_CONTEXT_INTRO = (
    "Auszüge aus der Projektdokumentation (nenne verwendete Quellen als [n]):\n\n{hits}"
)
RAG_RERANK_PROMPT = (
    "Frage: {query}\n\nBewerte für jeden der {count} Abschnitte, wie gut er die Frage "
    "beantwortet (0 = gar nicht, 10 = vollständig). Antworte nur mit JSON "
    '{{"scores": [...]}} in der Reihenfolge der Abschnitte.\n\n{passages}'
)
RAG_USED = "RAG: {sources}"

# Skills
SKILL_NO_FRONTMATTER = "kein Frontmatter (Datei muss mit '---' beginnen)"
SKILL_UNCLOSED_FRONTMATTER = "Frontmatter nicht mit '---' abgeschlossen"
SKILL_BAD_LINE = "Zeile {line} ist kein 'key: value': {text}"
SKILL_UNKNOWN_KEY = "unbekannter Key '{key}' (Zeile {line})"
SKILL_BAD_VERSION = "version muss eine Ganzzahl sein, ist aber {value!r}"
SKILL_MISSING_FIELDS = "Pflichtfelder fehlen: {fields}"
SKILL_IGNORED = "Skill ignoriert ({path}): {reason}"
SKILL_WARNING = "Warnung in {path}: {warning}"
SKILL_SHADOWED = "Skill '{name}' aus {loser} wird von {winner} verdeckt (Projekt vor Benutzer)."
SKILL_UNKNOWN = "Unbekannter Skill '{name}'. Verfügbar: {available}"
SKILL_ALREADY_LOADED = "Skill '{name}' ist bereits geladen – siehe oben."
SKILL_LOADED = "⚙ Skill: {name}"
SKILL_CONTENT_HEADER = "Skill '{name}' (Ordner: {directory}, nur lesbar)"
SKILL_CONTEXT_FILES = "Kontextdateien:"
SKILL_NONE = "Keine Skills gefunden. Geprüft: {paths}"
SKILL_SOURCE_PROJECT = "Projekt"
SKILL_SOURCE_USER = "Benutzer"
SKILL_DISABLED = "Skills sind abgeschaltet ([skills].enabled = false oder --no-skills)."
SKILL_EMBED_FAILED = "Skill-Vorauswahl ohne Embeddings ({error})"
SKILL_REASON_TRIGGER = "Trigger '{trigger}'"
SKILL_REASON_EMBED = "Ähnlichkeit {score:.2f}"
SKILL_REASON_NONE = "kein Treffer"
SKILL_REASON_OFF = "Vorauswahl aus (alphabetisch)"
SKILL_MATCH_AUTO = "wird automatisch geladen"
SKILL_CHECK_RUNNING = "Prüfe: {command}"
SKILL_CHECK_OK = "✓ Check bestanden: {command}"
SKILL_CHECK_FAILED = "✗ Check fehlgeschlagen: {command}"
SKILL_CHECK_SKIPPED = "Check übersprungen (kein Wert für {placeholder}): {command}"
SKILL_CHECKS_FAILED_SUMMARY = (
    "Checks fehlgeschlagen – der Auftrag ist nicht erfolgreich abgeschlossen. "
    "Änderungen zurücknehmen mit /undo bzw. lcc undo."
)
SKILL_NEW_BAD_NAME = "Ungültiger Skill-Name {name!r}: nur kleine Buchstaben, Ziffern und '-'."
SKILL_NEW_EXISTS = "{path} existiert bereits – wird nicht überschrieben."
SKILL_NEW_DONE = "Skill angelegt: {path}"
SKILL_NEW_NO_NAME = "Name fehlt. Beispiel: lcc skills new changelog-eintrag (oder --example)"

LINT_NAME_CASE = "name {name!r} ist nicht kebab-case"
LINT_NAME_FOLDER = "name {name!r} passt nicht zum Ordnernamen {folder!r}"
LINT_DESCRIPTION_LONG = "description ist {length} Zeichen lang (höchstens {limit})"
LINT_BODY_EMPTY = "Body ist leer"
LINT_BODY_LONG = "Body ist {length} Zeichen lang (höchstens {limit}, ideal 1500–3000)"
LINT_NO_TRIGGERS = "keine triggers – der Skill wird nur über Embeddings oder load_skill gefunden"
LINT_UNKNOWN_TOOL = "unbekanntes Tool in tools: {tool}"
LINT_UNKNOWN_PLACEHOLDER = "unbekannter Platzhalter in checks: {{{placeholder}}}"
LINT_MODEL_HINT = "model {model!r}: erwartet 'code', 'chat' oder einen Modellnamen mit Tag"
LINT_DUPLICATE = "Skill-Name {name!r} ist doppelt (auch in {other})"
LINT_TRIGGER_OVERLAP = "Trigger '{trigger}' kommt in mehreren Skills vor: {skills}"
LINT_SUMMARY = "{errors} Fehler, {warnings} Warnungen in {skills} Skills"
LINT_ERROR = "Fehler"
LINT_WARNING = "Warnung"
SKILL_COL_SOURCE = "Quelle"
SKILL_COL_DESCRIPTION = "Beschreibung"
SKILL_COL_REASON = "Grund"
SKILL_COL_STATUS = "Status"
SKILL_MATCH_LISTED = "im Systemprompt gelistet"
SKILL_MATCH_NOT_LISTED = "nicht gelistet (max_listed)"
REPL_NO_SKILLS = "Keine Skills gefunden. Anlegen mit: lcc skills new <name> (oder --example)"
DOCTOR_COL_SMALL = "Kleinmodell-Modus"
DOCTOR_TEXT_TOOLS = " (Text-Tools)"

# Kleinmodell-Werkzeuge
WRITE_TOO_LONG = (
    "write_file ist für bestehende Dateien mit mehr als {limit} Zeilen gesperrt ({path} hat "
    "{lines}). Nutze edit_file oder replace_lines für gezielte Änderungen."
)
EDIT_DONE_FUZZY = "Geändert: {path} (Zeilen {start}-{end}, Leerzeichen/Einrückung angeglichen)"
EDIT_SIMILAR_HEADER = "Die ähnlichsten Stellen:"
EDIT_SIMILAR_LINE = "Zeilen {start}-{end} (Ähnlichkeit {ratio:.2f}):"
REPLACE_REREAD = (
    "{path} wurde seit dem letzten read_file geändert (oder noch nicht gelesen). "
    "Lies die Datei erst neu mit read_file, damit die Zeilennummern stimmen."
)
REPLACE_RANGE = "Zeilenbereich {start}-{end} passt nicht zu {path} ({total} Zeilen)."
REPLACE_DONE = (
    "Ersetzt: {path} Zeilen {start}-{end} durch {count} Zeilen. Vor weiteren "
    "replace_lines die Datei neu lesen (Zeilennummern können sich verschoben haben)."
)
TOOL_RESULT_AS_TEXT = "Ergebnis von {name}:\n{content}"

# Auto-Kontext
CONTEXT_REPO_MAP = "Projektübersicht (Dateien und Top-Level-Symbole):\n{map}"
CONTEXT_FILES = "Inhalt der genannten Dateien (mit Zeilennummern):\n\n{files}"
CONTEXT_RAG = "Passende Auszüge aus der Doku (zitiere als [n]):\n\n{hits}"
CONTEXT_MAP_MORE = "… und {count} weitere Dateien"
CONTEXT_FILE_TRUNCATED = "\n[gekürzt – Datei hat {total} Zeilen, Rest mit read_file]"

# Kleinmodell-Modus
PLAN_SYSTEM = (
    "Du planst Programmieraufgaben für einen Coding-Agenten. Zerlege den Auftrag in 1–8 "
    "Schritte. phase: explore = lesen/suchen, edit = Dateien ändern, verify = prüfen/testen. "
    "files: betroffene Dateien. Reine Fragen ohne Änderung: genau ein explore-Schritt. "
    "Keine überflüssigen Schritte."
)
PLAN_RETRY = "Der Plan ist ungültig: {error}. Antworte nur mit JSON nach dem Schema."
PLAN_FALLBACK = "Plan ungültig – arbeite den Auftrag in einem Schritt ab."
PLAN_CANCELLED = "Plan abgebrochen."
PLAN_ERR_STEPS = "'steps' fehlt oder ist keine Liste"
PLAN_ERR_COUNT = "{count} Schritte (erlaubt: 1 bis {max})"
PLAN_ERR_STEP = "Schritt {number} ist kein Objekt"
PLAN_ERR_GOAL = "Schritt {number}: 'goal' fehlt"
PLAN_ERR_PHASE = "Schritt {number}: 'phase' muss eins von {phases} sein"
PLAN_ERR_FILES = "Schritt {number}: 'files' muss eine Liste von Strings sein"
PLAN_ERR_JSON = "kein gültiges JSON ({error})"
PLAN_HEADER = "Plan:"
PLAN_PROMPT = "[Enter] ausführen / [e] bearbeiten / [n] abbrechen: "
PLAN_EDIT_HELP = (
    "Neuer Plan, ein Schritt pro Zeile im Format 'phase: Ziel' (explore/edit/verify), "
    "leere Zeile beendet:"
)
PLAN_EDIT_INVALID = "Ungültige Zeile (Format 'phase: Ziel'): {line}"
STEP_HEADER = "▶ Schritt {number}/{total} [{phase}]: {goal}"
SMALL_STEP = (
    "Auftrag: {task}\n\nPlan:\n{plan}\n\nBisher erledigt:\n{done}\n\n"
    "Jetzt Schritt {number}/{total} ({phase}): {goal}\n{hint}"
)
SMALL_NOTHING_DONE = "(noch nichts)"
SMALL_HISTORY = "Bisheriges Gespräch (gekürzt):\n{text}"
PHASE_HINTS = {
    "explore": "Nur lesen und suchen, nichts ändern. Antworte am Ende kurz mit den Erkenntnissen.",
    "edit": "Führe die Änderung aus. Lies die Stelle vorher, wenn sie oben nicht steht.",
    "verify": (
        "Prüfe das Ergebnis mit run_shell und berichte kurz. Ohne Rückfrage erlaubt: "
        "{allowlist}. Keine Pipes, keine Umleitungen."
    ),
    "free": "",
}
SUMMARY_HEAD = "Schritt {number} ({phase}): {goal}"
SUMMARY_READ = "  gelesen: {files}"
SUMMARY_CHANGED = "  geändert: {files}"
SUMMARY_COMMAND = "  Befehl: {command} → exit {code}"
SUMMARY_ERRORS = "  Tool-Fehler: {count}"
SUMMARY_STOPPED = "  abgebrochen: {reason}"
SUMMARY_NOTE = "  Ergebnis: {note}"
REPAIR_GOAL = "Behebe diesen Fehler:\n{error}"
REPAIR_START = "↻ Repair-Versuch {attempt}: Fehler aus den Checks zurück an das Modell"
REPAIR_SAME_ERROR = "Gleicher Fehler wie im letzten Versuch – Repair wird abgebrochen."
ESCALATED = "↑ Eskaliert an {model}"
SMALL_BUDGET = "Gesamtlimit von {max_steps} Tool-Runden erreicht."
SMALL_NONE = "keine"
SMALL_MISSING_CHECKS = "die Checks sind weiterhin rot"
SMALL_ABORT = (
    "Abbruch: Auftrag nicht erfolgreich abgeschlossen.\n"
    "Erledigt (geänderte Dateien): {done}\n"
    "Fehlt: {missing}\n"
    "Letzte Fehlermeldung:\n{error}\n"
    "Änderungen zurücknehmen mit /undo bzw. lcc undo."
)
SMALL_MODE_ON = "Kleinmodell-Modus ({model}, {size})"

# Kontextbudget
TRUNCATED = "[gekürzt]"
CONTEXT_SHORTENED = "Kontext fast voll – {count} ältere Tool-Ergebnisse gekürzt."
PLAN_THINKING_TOO_LONG = "Planung denkt zu lange – neuer Versuch ohne Thinking."
STATUS_TOOL = "führt {name} aus …"
STATUS_CHECK = "prüft: {command} …"
STATUS_PREPARE = "bereitet den Schritt vor …"
