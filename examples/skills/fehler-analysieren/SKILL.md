---
name: fehler-analysieren
description: Findet die Ursache eines Python-Fehlers anhand von Traceback oder Fehlermeldung und behebt sie minimal. Nutzen bei "Traceback", "Exception", "Fehlermeldung".
triggers: traceback, stacktrace, exception, fehlermeldung, absturz, typeerror, valueerror, keyerror, attributeerror, indexerror, nameerror, importerror, modulenotfounderror, zerodivisionerror
tools: read_file, search_code, edit_file, run_shell
version: 1
---

# Fehler analysieren und beheben

## Ziel
Die Ursache ist benannt und mit der kleinstmöglichen Änderung behoben.

## Vorgehen
1. Lies den Traceback von **unten nach oben**: letzte Zeile = Fehlertyp und Meldung, darüber die Aufrufkette.
2. Nimm die unterste Zeile, die auf eine Projektdatei zeigt (nicht auf Bibliotheken). Lies diese Stelle mit `read_file` (±20 Zeilen).
3. Formuliere eine Vermutung in einem Satz: „X ist None, weil …“.
4. Prüfe die Vermutung: Woher kommt der Wert? Nutze `search_code` für Aufrufer und Zuweisungen.
5. Behebe die Ursache mit `edit_file` – an der Stelle, an der der falsche Wert entsteht, nicht dort, wo er knallt.
6. Gibt es Tests (`tests/`), führe `python -m pytest -q` mit `run_shell` aus.

## Regeln
- Erst verstehen, dann ändern: höchstens eine Änderung pro Vermutung.
- Fehler nicht mit `try/except` verstecken, außer der Fall ist wirklich erwartbar.
- Bleibt die Ursache unklar: sag das und nenne die nächste sinnvolle Prüfung.

## Nicht tun
- Mehrere „Verbesserungen“ nebenbei einbauen.
- Tests abschwächen oder löschen.
- Bibliotheksdateien (z. B. in `.venv`) ändern.

## Ausgabe
Ursache (ein Satz), geänderte Stelle mit Zeilennummer, Testergebnis.

## Beispiel
```
  File "tarife.py", line 18, in preis
    betrag = GRUNDPREIS_EUR + PREIS_PRO_KG_EUR * gewicht_kg
TypeError: can't multiply sequence by non-int of type 'float'
```
Ursache: `gewicht_kg` kommt als String aus dem Formular. Behebung beim Einlesen
(`float(gewicht)`), nicht in `preis()`.
