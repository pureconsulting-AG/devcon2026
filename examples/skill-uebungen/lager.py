from dataclasses import dataclass


@dataclass
class Artikel:
    nummer: str
    name: str
    bestand: int
    mindestbestand: int = 5


def nachbestellen(artikel: list[Artikel]) -> list[Artikel]:
    return [a for a in artikel if a.bestand < a.mindestbestand]


def bestand_buchen(artikel: Artikel, menge: int) -> Artikel:
    if artikel.bestand + menge < 0:
        raise ValueError(f"Bestand von {artikel.nummer} würde negativ")
    return Artikel(artikel.nummer, artikel.name, artikel.bestand + menge, artikel.mindestbestand)


def lagerwert(artikel: list[Artikel], preise: dict[str, float]) -> float:
    return round(sum(a.bestand * preise.get(a.nummer, 0.0) for a in artikel), 2)
