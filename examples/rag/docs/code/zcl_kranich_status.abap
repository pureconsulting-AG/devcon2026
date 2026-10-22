CLASS zcl_kranich_status DEFINITION PUBLIC FINAL CREATE PUBLIC.
  PUBLIC SECTION.
    "! Übersetzt Kranich-Statuscodes in SAP-Lieferstatus
    CLASS-METHODS to_sap_status
      IMPORTING iv_kranich_code   TYPE string
      RETURNING VALUE(rv_status) TYPE char2.
ENDCLASS.

CLASS zcl_kranich_status IMPLEMENTATION.
  METHOD to_sap_status.
    " ZU = zugestellt, UT = unterwegs, RS = Rücksendung, UK = unbekannt
    CASE iv_kranich_code.
      WHEN 'DELIVERED'.
        rv_status = 'ZU'.
      WHEN 'IN_TRANSIT' OR 'AT_HUB'.
        rv_status = 'UT'.
      WHEN 'RETURNED'.
        rv_status = 'RS'.
      WHEN OTHERS.
        rv_status = 'UK'.
    ENDCASE.
  ENDMETHOD.
ENDCLASS.
