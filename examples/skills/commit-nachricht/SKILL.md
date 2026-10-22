---
name: commit-nachricht
description: Formuliert eine Commit-Nachricht aus den aktuellen Änderungen (git diff). Nutzen bei "Commit-Nachricht", "commit message".
triggers: commit-nachricht, commitnachricht, commit message, commit-message
tools: run_shell, read_file
version: 1
---

# Commit-Nachricht formulieren

## Ziel
Eine fertige Commit-Nachricht als Text in der Antwort – nichts wird geändert oder committet.

## Vorgehen
1. Führe `git status` mit `run_shell` aus, um die geänderten Dateien zu sehen.
2. Führe `git diff` aus (für bereits vorgemerkte Änderungen zusätzlich `git diff --cached`).
3. Lies bei Bedarf einzelne Dateien mit `read_file`, wenn der Diff allein unklar ist.
4. Fasse das **Warum** der Änderung zusammen, nicht nur das Was.
5. Gib die Nachricht im Format unten aus.

## Regeln
- Betreffzeile höchstens 60 Zeichen, Imperativ, kein Punkt am Ende („Behebe …“, „Ergänze …“).
- Leerzeile, dann ein Textkörper mit Stichpunkten (je höchstens 72 Zeichen pro Zeile).
- Sprache der bisherigen Commits übernehmen, falls erkennbar (`git log` ist nicht freigegeben – im Zweifel Deutsch).

## Nicht tun
- `git commit`, `git add` oder andere verändernde Befehle ausführen.
- Dateien ändern.
- Änderungen erfinden, die nicht im Diff stehen.

## Ausgabe
Nur die Commit-Nachricht in einem Codeblock, danach ein Satz, welche Dateien sie abdeckt.

## Beispiel
```
Behebe Rundungsfehler im Inselzuschlag

- preis() rundete vor dem Zuschlag statt danach
- Test für Norderney (PLZ 26548) ergänzt
```
