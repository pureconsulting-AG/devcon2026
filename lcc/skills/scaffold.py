"""'lcc skills new': Skill-Gerüst bzw. Beispiel-Skill pytest-test anlegen."""

from __future__ import annotations

import re
from pathlib import Path

from lcc import texts
from lcc.skills.loader import SKILL_FILE

NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EXAMPLE_NAME = "pytest-test"

TEMPLATE = """---
name: {name}
description: <Was der Skill tut> – nutzen bei "<Stichwort>", "<Stichwort>".
triggers: <stichwort>, <phrase aus zwei wörtern>
tools: read_file, search_code, edit_file, write_file, run_shell
# checks: python -m pytest -q
# context_files: pyproject.toml
version: 1
---

# {title}

## Ziel
Ein Satz: welches Ergebnis am Ende vorliegt.

## Vorgehen
1. Lies die betroffene Datei mit `read_file`.
2. Prüfe mit `search_code`, ob es schon etwas Ähnliches gibt.
3. Ändere die Datei mit `edit_file` (kleine Schritte).
4. Führe die Checks aus.

## Regeln
- Eine Regel pro Zeile, klare Verben.

## Nicht tun
- Was das Modell ausdrücklich nicht tun soll.

## Ausgabe
Kurze Zusammenfassung: geänderte Dateien, Ergebnis der Checks.

## Beispiel
<kurzes, vollständiges Beispiel>
"""

EXAMPLE = """---
name: pytest-test
description: Schreibt pytest-Tests für eine bestehende Python-Funktion. Nutzen bei "Test schreiben", "pytest", "Unit-Test".
triggers: pytest, tests, test schreiben, tests schreiben, unit-test, unittest, testfall, testfälle
tools: read_file, list_dir, search_code, edit_file, write_file, run_shell
checks: python -m pytest -q {test_file}
context_files: pyproject.toml, tests/conftest.py
model: code
version: 1
---

# pytest-Tests schreiben

## Ziel
Für die genannte Funktion gibt es Tests unter `tests/`, und `pytest` läuft grün.

## Vorgehen
1. Finde die Funktion mit `search_code` (Muster `def <name>`), falls der Pfad nicht genannt ist.
2. Lies die Funktion mit `read_file` und notiere: Eingaben, Rückgabe, Sonderfälle, Fehler.
3. Prüfe mit `list_dir` auf `tests/`, ob `tests/test_<modul>.py` schon existiert.
4. Existiert die Datei: ergänze sie mit `edit_file`. Sonst: lege sie mit `write_file` an.
5. Schreibe einen Test pro Verhalten: Normalfall, Randfall (leer, 0, None), Fehlerfall.
6. Führe `python -m pytest -q tests/test_<modul>.py` mit `run_shell` aus.
7. Schlägt ein Test fehl, lies die Fehlermeldung und korrigiere den **Test**, wenn er falsch ist.

## Regeln
- Importiere die Funktion so, wie das Projekt es tut (siehe bestehende Tests oder `pyproject.toml`).
- Testnamen: `test_<funktion>_<fall>`, z. B. `test_slugify_umlaute`.
- Keine Mocks, wenn die Funktion rein ist.
- `pytest.raises` für erwartete Fehler, `pytest.mark.parametrize` für viele ähnliche Fälle.

## Nicht tun
- Produktionscode ändern, nur damit Tests grün werden – Fehler im Code melden statt verstecken.
- Bestehende Tests löschen oder abschwächen.
- Tests schreiben, die nur prüfen, dass kein Fehler auftritt.

## Ausgabe
Kurze Zusammenfassung: Testdatei, Anzahl Tests, Ergebnis von pytest.

## Beispiel
Funktion in `utils.py`:

```python
def slugify(text: str) -> str:
    return "-".join(text.lower().split())
```

Tests in `tests/test_utils.py`:

```python
import pytest

from utils import slugify


def test_slugify_simple():
    assert slugify("Hallo Welt") == "hallo-welt"


def test_slugify_empty():
    assert slugify("") == ""


@pytest.mark.parametrize("raw", ["  a  b ", "a\\tb"])
def test_slugify_whitespace(raw):
    assert slugify(raw) == "a-b"
```
"""


class ScaffoldError(Exception):
    pass


def create_skill(base: Path, name: str, *, example: bool = False) -> Path:
    """Legt <base>/<name>/SKILL.md an (nie überschreiben)."""
    if not NAME_PATTERN.match(name):
        raise ScaffoldError(texts.SKILL_NEW_BAD_NAME.format(name=name))
    target = base / name / SKILL_FILE
    if target.exists():
        raise ScaffoldError(texts.SKILL_NEW_EXISTS.format(path=target))
    target.parent.mkdir(parents=True, exist_ok=True)
    if example:
        content = EXAMPLE
    else:
        content = TEMPLATE.format(name=name, title=name.replace("-", " ").capitalize())
    target.write_text(content, encoding="utf-8")
    return target
