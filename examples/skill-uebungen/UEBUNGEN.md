# Skill-Übungen

Ein kleines Projekt der (erfundenen) Nordlicht Logistik mit je einer Ausgangslage pro
Beispiel-Skill. Die Skills liegen schon unter `.lcc/skills/`.

**Vorher:** `lcc skills` zeigt die sechs Skills. Mit `lcc skills match "<Auftrag>"` siehst du vor
jeder Übung, welcher Skill geladen würde und warum.

**Tipp:** Ohne `--yes` fragt lcc vor jeder Änderung und zeigt den Diff – so siehst du genau, was
der Skill bewirkt. Zurücknehmen mit `lcc undo` (mehrfach möglich).

---

## 1. pytest-test – Tests schreiben

**Ausgangslage:** `utils.py` hat `slugify` und `format_euro`, aber keine Tests.

```bash
lcc run "schreib Tests für slugify und format_euro in utils.py"
```

**Erwartet:** `⚙ Skill: pytest-test`, neue Datei `tests/test_utils.py`, am Ende
`✓ Check bestanden: python -m pytest -q tests/test_utils.py`.
**Prüfen:** `python -m pytest -q`

Achte darauf, ob das Modell die Testerwartung korrigiert statt den Code zu ändern, wenn es sich
bei `format_euro` (Tausenderpunkt!) verschätzt – genau das verlangt der Skill.

---

## 2. docstrings-ergaenzen – Dokumentation ergänzen

**Ausgangslage:** In `lager.py` hat keine Funktion einen Docstring.

```bash
lcc run "ergänze Docstrings für die Funktionen in lager.py"
```

**Erwartet:** `⚙ Skill: docstrings-ergaenzen`, je Funktion ein `edit_file` – nur Docstrings, keine
Logik. Das Tool-Set ist eingeschränkt: `write_file` und `run_shell` stehen nicht zur Verfügung.
**Prüfen:** `git diff lager.py` zeigt nur `"""…"""`-Zeilen.

---

## 3. fehler-analysieren – Bug beheben

**Ausgangslage:** `python main.py` stürzt ab (siehe `traceback.txt`).

```bash
cat traceback.txt | lcc run "Beim Start von main.py kommt dieser Traceback. Finde die Ursache und behebe sie."
```

**Erwartet:** `⚙ Skill: fehler-analysieren` (Trigger `traceback`). Gute Lösung: das Gewicht wird in
`lies_formular` mit `float(...)` umgewandelt – dort, wo der falsche Wert **entsteht**, nicht in
`versandkosten`.
**Prüfen:** `python main.py` → `Petra Lindner: 7.03 EUR`

Das Modell will danach oft selbst `python main.py` starten. Der Befehl steht nicht auf der
Allowlist: im Terminal fragt lcc nach (`j` erlaubt ihn), in Skripten bzw. über eine Pipe ohne
Terminal wird er abgelehnt – das Modell bekommt den Grund mitgeteilt.

---

## 4. changelog-eintrag – Änderung dokumentieren

**Ausgangslage:** `CHANGELOG.md` mit leerem `[Unreleased]`-Abschnitt.

```bash
lcc run "trag ins Changelog ein: Versandkosten werden jetzt auch korrekt berechnet, wenn das Gewicht als Text aus dem Formular kommt"
```

**Erwartet:** `⚙ Skill: changelog-eintrag`, eine neue Zeile unter `## [Unreleased]` → `### Fixed`,
beginnend mit einem Verb („Behebt …“). Alte Einträge bleiben unverändert.
**Prüfen:** `git diff CHANGELOG.md`

---

## 5. commit-nachricht – nur lesen, nichts ändern

**Ausgangslage:** Es gibt offene Änderungen (`git status`): neue Funktion `kuerzen` in
`utils.py`, geänderter Mindestbestand in `lager.py`.

```bash
lcc run "Schlag mir eine Commit-Nachricht für meine aktuellen Änderungen vor"
```

**Erwartet:** `⚙ Skill: commit-nachricht`, Aufrufe von `git status` / `git diff` (Allowlist, keine
Rückfrage), eine Nachricht im Codeblock. **Keine** Datei wird geändert, kein Commit angelegt – der
Skill erlaubt nur `run_shell` und `read_file`.
**Prüfen:** `git status` sieht danach genauso aus wie vorher.

---

## 6. abap-unit-test – ABAP-Testklasse

**Ausgangslage:** `abap/zcl_kranich_status.clas.abap` ohne Tests.

```bash
lcc run "Schreib eine ABAP-Unit-Testklasse für abap/zcl_kranich_status.clas.abap"
```

**Erwartet:** `⚙ Skill: abap-unit-test` (Trigger `abap-unit`), neue Datei
`abap/zcl_kranich_status.clas.testclasses.abap` mit `FOR TESTING`, je Statuscode eine Methode
(`DELIVERED`→`ZU`, `AT_HUB`→`UT`, `RETURNED`→`RS`, sonst `UK`).
**Prüfen:** Datei ansehen – ausführen lässt sie sich nur in einem SAP-System.

---

## Bonus: Skills in der REPL

```text
lcc
› /skills                       # alle Skills, geladene mit ⚙
› /skill commit-nachricht       # manuell laden
› Was habe ich geändert?        # nutzt den geladenen Skill
› /diff                         # Änderungen dieser Session
```

## Bonus: Skill ohne Trigger

```bash
lcc skills match "Die Funktionen in lager.py brauchen Beschreibungen"
```

Kein Trigger passt, `docstrings-ergaenzen` wird nur über die Ähnlichkeit gelistet (knapp unter der
Auto-Load-Schwelle 0.55). Bei `lcc run` mit diesem Auftrag kann das Modell den Skill selbst per
`load_skill` holen – oder eben nicht. Gut zu sehen, warum Trigger für kleine Modelle helfen.

## Neu anfangen

Einfach neu einrichten (aus dem lcc-Repo):

```bash
rm -rf ~/lcc-uebungen && /work/examples/skill-uebungen/einrichten.sh ~/lcc-uebungen
```
