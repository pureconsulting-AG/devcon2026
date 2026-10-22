---
name: changelog-eintrag
description: Ergänzt CHANGELOG.md um einen Eintrag im Format "Keep a Changelog". Nutzen bei "Changelog", "Release Notes", "Versionshinweise".
triggers: changelog, release notes, versionshinweise, änderungsprotokoll
tools: read_file, list_dir, run_shell, edit_file, write_file
version: 1
---

# CHANGELOG-Eintrag

## Ziel
`CHANGELOG.md` enthält unter `## [Unreleased]` einen kurzen, korrekt einsortierten Eintrag.

## Vorgehen
1. Prüfe mit `list_dir`, ob `CHANGELOG.md` existiert.
2. Existiert sie: lies sie mit `read_file`. Sonst: lege sie mit `write_file` nach dem Beispiel unten an.
3. Ermittle die Änderungen mit `run_shell` und `git diff` bzw. `git status`, falls der Auftrag sie nicht nennt.
4. Ordne jede Änderung genau einer Rubrik zu: `Added`, `Changed`, `Fixed`, `Removed`.
5. Füge die Zeilen mit `edit_file` unter `## [Unreleased]` in die passende Rubrik ein. Fehlt die Rubrik, lege sie an.

## Regeln
- Eine Zeile pro Änderung, beginnend mit einem Verb im Präsens („Ergänzt …“, „Behebt …“).
- Aus Nutzersicht schreiben, nicht aus Code-Sicht (kein Funktionsname ohne Erklärung).
- Reihenfolge der Rubriken: Added, Changed, Fixed, Removed.

## Nicht tun
- Bestehende Einträge ändern oder umsortieren.
- Versionsnummern oder Daten erfinden – neue Einträge gehören immer unter `[Unreleased]`.
- Commits oder Tags anlegen.

## Ausgabe
Die eingefügten Zeilen und die Rubrik, in der sie stehen.

## Beispiel
```markdown
# Changelog

## [Unreleased]
### Added
- Ergänzt den Export als CSV in der Sendungsliste.

### Fixed
- Behebt falsche Umlaute im PDF-Lieferschein.

## [1.2.0] - 2026-09-30
### Added
- Neue Suche nach Sendungsnummer.
```
