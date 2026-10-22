from lager import Artikel, nachbestellen


def test_nachbestellen_unter_mindestbestand():
    artikel = [Artikel("A1", "Karton", 2), Artikel("A2", "Klebeband", 10)]
    assert [a.nummer for a in nachbestellen(artikel)] == ["A1"]
