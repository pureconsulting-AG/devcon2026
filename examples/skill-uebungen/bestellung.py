"""Berechnet Versandkosten für Bestellungen aus dem Webformular."""

GRUNDPREIS_EUR = 4.90
PREIS_PRO_KG_EUR = 0.85


def versandkosten(gewicht_kg: float) -> float:
    """Versandkosten in Euro für ein Paket."""
    return round(GRUNDPREIS_EUR + PREIS_PRO_KG_EUR * gewicht_kg, 2)


def lies_formular(daten: dict[str, str]) -> dict[str, object]:
    """Übernimmt die Felder aus dem Webformular (alle Werte kommen als Text)."""
    return {
        "kunde": daten["kunde"].strip(),
        "gewicht_kg": daten["gewicht"],
        "express": daten.get("express") == "ja",
    }


def bestellung_bearbeiten(daten: dict[str, str]) -> str:
    bestellung = lies_formular(daten)
    kosten = versandkosten(bestellung["gewicht_kg"])
    return f"{bestellung['kunde']}: {kosten:.2f} EUR"
