---
name: abap-unit-test
description: Legt für eine ABAP-Klasse eine lokale ABAP-Unit-Testklasse an. Nutzen bei "ABAP Unit", "Testklasse", "FOR TESTING".
triggers: abap unit, abap-unit, abapunit, testklasse, for testing
tools: read_file, search_code, edit_file, write_file
version: 1
---

# ABAP-Unit-Testklasse anlegen

## Ziel
Für die genannte Klasse gibt es eine lokale Testklasse `ltc_<name>` mit einem Test pro Verhalten.

## Vorgehen
1. Lies die Klasse mit `read_file`; notiere öffentliche Methoden, Parameter, Rückgabetypen.
2. Prüfe mit `search_code` nach `FOR TESTING`, ob es schon eine Testklasse gibt.
3. Lege die Testklasse an bzw. ergänze sie (bei abapGit: Datei `<klasse>.clas.testclasses.abap`).
4. Schreibe pro Verhalten eine Methode: Normalfall, Grenzfall, `WHEN OTHERS`-Zweig.
5. Prüfe jede Methode mit `cl_abap_unit_assert=>assert_equals( act = … exp = … )`.

## Regeln
- Kopf immer: `CLASS ltc_… DEFINITION FINAL FOR TESTING DURATION SHORT RISK LEVEL HARMLESS.`
- Methodennamen sprechend, höchstens 30 Zeichen: `delivered_gives_zu`.
- Statische Methoden direkt aufrufen, für Instanzmethoden ein `cut` (class under test) in `setup`.

## Nicht tun
- Die getestete Klasse ändern.
- Datenbankzugriffe in Tests (dafür wären Test-Doubles nötig – nur nennen, nicht bauen).
- Testmethoden ohne Assertion.

## Ausgabe
Name der Testklasse, Liste der Testmethoden. Hinweis: ausführen mit Strg+Shift+F10 in ADT.

## Beispiel
```abap
CLASS ltc_kranich_status DEFINITION FINAL FOR TESTING
  DURATION SHORT RISK LEVEL HARMLESS.
  PRIVATE SECTION.
    METHODS delivered_gives_zu FOR TESTING.
    METHODS unknown_gives_uk FOR TESTING.
ENDCLASS.

CLASS ltc_kranich_status IMPLEMENTATION.
  METHOD delivered_gives_zu.
    cl_abap_unit_assert=>assert_equals(
      act = zcl_kranich_status=>to_sap_status( 'DELIVERED' )
      exp = 'ZU' ).
  ENDMETHOD.

  METHOD unknown_gives_uk.
    cl_abap_unit_assert=>assert_equals(
      act = zcl_kranich_status=>to_sap_status( 'FOO' )
      exp = 'UK' ).
  ENDMETHOD.
ENDCLASS.
```
