"""Tarifberechnung für Sendungen der Nordlicht Logistik."""

GRUNDPREIS_EUR = 4.90
PREIS_PRO_KG_EUR = 0.85
EXPRESS_ZUSCHLAG_EUR = 9.90
INSEL_ZUSCHLAG_EUR = 12.50
MAX_GEWICHT_KG = 31.5


def preis(gewicht_kg: float, express: bool = False, insel: bool = False) -> float:
    """Berechnet den Versandpreis in Euro.

    Sendungen über 31,5 kg werden nicht angenommen (ValueError).
    Inselzustellungen (z. B. Norderney, Borkum) kosten einen Zuschlag.
    """
    if gewicht_kg > MAX_GEWICHT_KG:
        raise ValueError("Sendungen über 31,5 kg sind Speditionsware")
    betrag = GRUNDPREIS_EUR + PREIS_PRO_KG_EUR * gewicht_kg
    if express:
        betrag += EXPRESS_ZUSCHLAG_EUR
    if insel:
        betrag += INSEL_ZUSCHLAG_EUR
    return round(betrag, 2)


def ist_insel(plz: str) -> bool:
    """Ostfriesische Inseln haben Postleitzahlen von 26465 bis 26579."""
    return plz.isdigit() and 26465 <= int(plz) <= 26579
