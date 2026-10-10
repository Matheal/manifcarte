from datetime import date

import pytest

from collector import extract as ex

GAZ = ex.Gazetteer()
# Mercredi 7 octobre 2026
REF = date(2026, 10, 7)


@pytest.mark.parametrize("text,expected", [
    ("Manifestation des lycéens à Nancy", True),
    ("Blocus devant le lycée Poincaré", True),
    ("Grève à la SNCF ce jeudi", True),
    ("Le défilé de mode de Paris a ébloui", False),
    ("Une manifestation culturelle au musée", False),
    ("Le maire inaugure une nouvelle piscine", False),
])
def test_is_relevant(text, expected):
    assert ex.is_relevant(text) is expected


def test_communes_title_and_demonym():
    found = [c.name for c in GAZ.find("Nouvelle journée d'action à Metz et Nancy")]
    assert found == ["Metz", "Nancy"]
    assert [c.name for c in GAZ.find("Les lycéens nancéiens dans la rue")] == ["Nancy"]


def test_communes_ignore_lowercase_and_sport():
    assert GAZ.find("trois tours de piste") == []
    assert GAZ.find("Le Paris Saint-Germain s'impose") == []


@pytest.mark.parametrize("text,expected", [
    ("ce qui est prévu ce jeudi", date(2026, 10, 8)),
    ("manifestation ce lundi", date(2026, 10, 5)),
    ("rendez-vous demain place Stanislas", date(2026, 10, 8)),
    ("rassemblement après-demain", date(2026, 10, 9)),
    ("hier soir, des incidents", date(2026, 10, 6)),
    ("appel à manifester le 15 octobre", date(2026, 10, 15)),
    ("mardi 13 octobre, nouvelle journée", date(2026, 10, 13)),
    ("le 1er novembre", date(2026, 11, 1)),
    ("jeudi prochain", date(2026, 10, 8)),
    ("lundi prochain", date(2026, 10, 12)),
    ("samedi dernier", date(2026, 10, 3)),
    ("le 14/10", date(2026, 10, 14)),
])
def test_dates(text, expected):
    assert expected in [d for d, _ in ex.find_dates(text, REF)]


def test_dates_year_rollover():
    assert ex.find_dates("le 5 janvier", date(2026, 12, 20))[0][0] == date(2027, 1, 5)


def test_time_and_places():
    text = "Rendez-vous à 14h30 place Stanislas puis devant le lycée Henri-Loritz et à la préfecture"
    assert ex.find_time(text) == "14:30"
    places = ex.find_places(text)
    assert "place Stanislas" in places
    assert "lycée Henri-Loritz" in places
    assert "Préfecture" in places


def test_causes_and_signals():
    text = "Blocus et tensions au lycée : les lycéens appellent à une nouvelle journée"
    assert ex.find_causes(text)[0] == "education"
    sig = ex.find_signals(text)
    assert {"blocus", "tensions", "annonce"} <= set(sig)


@pytest.mark.parametrize("text,expected", [
    ("des milliers de lycéens", 2000),
    ("3 000 manifestants selon la police", 3000),
    ("environ 450 personnes", 450),
    ("en 2026 personnes", None),
])
def test_participants(text, expected):
    assert ex.find_participants(text) == expected


def test_extract_full():
    e = ex.extract(
        "Manifestations lycéennes en Meurthe-et-Moselle : ce qui est prévu ce jeudi à Nancy",
        "Les lycéens donnent rendez-vous à 10h place Stanislas.",
        REF, GAZ,
    )
    assert e is not None
    assert e.communes[0].name == "Nancy"
    assert e.dates[0][0] == date(2026, 10, 8)
    assert e.time == "10:00"
    assert "annonce" in e.signals
