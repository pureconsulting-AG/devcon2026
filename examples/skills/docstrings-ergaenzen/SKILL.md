---
name: docstrings-ergaenzen
description: Ergänzt fehlende Docstrings in Python-Funktionen und -Klassen, ohne Logik zu ändern. Nutzen bei "Docstring", "dokumentiere die Funktion".
triggers: docstring, docstrings, dokumentiere die funktion, dokumentiere die klasse
tools: read_file, search_code, edit_file
version: 1
---

# Docstrings ergänzen

## Ziel
Jede öffentliche Funktion und Klasse in der genannten Datei hat einen kurzen, korrekten Docstring.

## Vorgehen
1. Lies die Datei mit `read_file`.
2. Liste alle `def` und `class` ohne Docstring auf (Namen mit `_` am Anfang überspringen).
3. Lies für jede Funktion den Rumpf und notiere: was sie zurückgibt, welche Fehler sie wirft.
4. Ergänze die Docstrings einzeln mit `edit_file`. `old_str` ist die `def`-Zeile, `new_str` dieselbe Zeile plus Docstring – mit derselben Einrückung wie der Rumpf.

## Regeln
- Erste Zeile: ein Satz im Präsens, was die Funktion tut („Berechnet …“).
- Danach nur, was nicht offensichtlich ist: Einheiten, Grenzen, Fehlerfälle.
- Sprache der vorhandenen Kommentare übernehmen.
- Bestehende Docstrings nicht umschreiben.

## Nicht tun
- Code, Signaturen oder Typannotationen ändern.
- Parameter dokumentieren, die es nicht gibt.
- Mehrere Funktionen in einem `edit_file`-Aufruf ändern.

## Ausgabe
Liste der ergänzten Funktionen/Klassen mit Zeilennummer.

## Beispiel
Vorher:
```python
def ist_insel(plz: str) -> bool:
    return plz.isdigit() and 26465 <= int(plz) <= 26579
```

Nachher:
```python
def ist_insel(plz: str) -> bool:
    """Prüft, ob die Postleitzahl zu einer Ostfriesischen Insel gehört (26465–26579)."""
    return plz.isdigit() and 26465 <= int(plz) <= 26579
```
