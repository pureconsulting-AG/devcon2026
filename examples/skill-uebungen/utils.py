"""Hilfsfunktionen für die Nordlicht-Webseite."""

import re

UMLAUTE = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}


def slugify(text: str) -> str:
    """Wandelt einen Titel in einen URL-tauglichen Slug um."""
    text = text.lower().strip()
    for umlaut, ersatz in UMLAUTE.items():
        text = text.replace(umlaut, ersatz)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def format_euro(betrag: float) -> str:
    """Formatiert einen Betrag deutsch: 1234.5 -> '1.234,50 €'."""
    text = f"{betrag:,.2f}"
    text = text.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} €"
