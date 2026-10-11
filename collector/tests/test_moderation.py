import pathlib
import re
from datetime import date

from collector import moderation as mo
from collector.events import build_fr_events
from collector.extract import Gazetteer
from collector.restrictions import build_restrictions

GAZ = Gazetteer()
TEMPLATES = pathlib.Path(__file__).resolve().parents[2] / ".github" / "ISSUE_TEMPLATE"


class FakeGeo:
    def locate(self, place, city, lat, lon):
        return (48.6935, 6.1832) if place == "place Stanislas" else None

    def locate_city(self, name):
        return (50.8467, 4.3525, "Bruxelles", "Belgique") if name == "Bruxelles" else None


def form(**fields):
    labels = {v: k for k, v in mo.FIELDS.items()}
    return "\n\n".join(f"### {labels[k]}\n\n{v}" for k, v in fields.items())


def issue(number, label, body, assoc="OWNER", labels=(), state="open"):
    return {"number": number, "labels": [{"name": n} for n in (label, *labels)], "body": body,
            "author_association": assoc, "state": state, "created_at": "2026-10-11T09:00:00Z"}


def test_templates_match_parser():
    """Chaque intitulé des formulaires GitHub doit être connu du collecteur."""
    for path in TEMPLATES.glob("[0-9]-*.yml"):
        for label in re.findall(r"^\s+label: (.+)$", path.read_text(), flags=re.M):
            label = label.strip().strip('"')
            if label != "Vérification" and not label.startswith("Je n'ai"):
                assert label in mo.FIELDS, f"{path.name} : « {label} » inconnu"


def test_parse_form_ignores_empty():
    body = "### Ville\n\nNancy\n\n### Heure de début\n\n_No response_\n\n### Vérification\n\n- [X] ok"
    assert mo.parse_form(body) == {"ville": "Nancy"}


def test_parse_date_formats():
    ref = date(2026, 10, 11)
    assert mo.parse_date("2026-10-13", ref) == date(2026, 10, 13)
    assert mo.parse_date("13/10/2026", ref) == date(2026, 10, 13)
    assert mo.parse_date("13/10", ref) == date(2026, 10, 13)
    assert mo.parse_date("mardi 13 octobre", ref) == date(2026, 10, 13)
    assert mo.parse_date("5/1", date(2026, 12, 20)) == date(2027, 1, 5)
    assert mo.parse_date("bientôt", ref) is None
    assert mo.parse_time("14h30") == "14:30" and mo.parse_time("9 h") == "09:00"


def test_owner_contributions_apply_and_public_ones_wait():
    issues = [
        issue(1, "ajout-manif", form(ville="Nancy", date="13/10/2026", type="Blocus",
                                     cause="Éducation & lycéens", lieu="place Stanislas")),
        issue(2, "ajout-manif", form(ville="Metz", date="14/10/2026"), assoc="NONE"),
        issue(3, "ajout-manif", form(ville="Lyon", date="14/10/2026"), assoc="NONE", labels=["approuvé"]),
        issue(4, "suppression", form(lien="https://matheal.github.io/manifcarte/manif/2026-10-16-nancy/")),
        issue(5, "suppression", form(lien="https://news.google.com/rss/articles/abc")),
        issue(6, "suppression", form(lien="https://x.io/perturbations/#r-2026-10-06-nancy-transport")),
        issue(7, "ajout-manif", form(ville="Nancy", date="13/10/2026"), labels=["annulé"]),
        issue(8, "ajout-manif", form(ville="Nancy", date="un jour")),
    ]
    mod = mo.collect(issues)
    assert [m["ville"] for m in mod.manual_events] == ["Nancy", "Lyon"]
    assert mod.manual_events[0]["kind"] == "Blocus" and mod.manual_events[0]["cause"] == "education"
    assert mod.pending == 1 and mod.statuses[2] == ("pending", "")
    assert mod.removed_events == {"2026-10-16-nancy"}
    assert mod.removed_urls == {"https://news.google.com/rss/articles/abc"}
    assert mod.removed_restrictions == {"r-2026-10-06-nancy-transport"}
    assert mod.statuses[7] == ("cancelled", "")
    assert mod.statuses[8][0] == "error"


def test_manual_event_creates_verified_event():
    mod = mo.collect([issue(1, "ajout-manif", form(
        ville="Nancy", date="13/10/2026", heure="10h", type="Blocus", cause="Éducation & lycéens",
        lieu="place Stanislas", description="Blocus devant le lycée Poincaré"))])
    [e] = build_fr_events([], GAZ, FakeGeo(), mod.manual_events)
    assert e["id"] == "2026-10-13-nancy" and e["kind"] == "Blocus" and e["time"] == "10:00"
    assert e["verified"] and e["reliability"]["label"] == "Vérifiée par l'équipe"
    assert e["place"] == "place Stanislas" and "annonce" in e["signals"]
    assert e["summary"] == "Blocus devant le lycée Poincaré"


def test_manual_event_abroad_is_world_scope():
    mod = mo.collect([issue(1, "ajout-manif", form(ville="Bruxelles", date="13/10/2026"))])
    [e] = build_fr_events([], GAZ, FakeGeo(), mod.manual_events)
    assert e["scope"] == "world" and e["country"] == "Belgique"


def test_restrictions_from_ai_are_merged_and_manual_kept():
    def art(n, desc, lignes):
        return {"id": f"a{n}", "kind": "presse", "outlet": f"Média {n}", "title": f"Article {n}",
                "url": f"https://ex.fr/{n}", "published": "2026-10-06T07:00:00+00:00",
                "ai": {"nature": "contexte", "perturbations": [
                    {"type": "transport", "ville": "Nancy", "lieu": "place Stanislas", "lignes": lignes,
                     "debut": None, "fin": None, "description": desc}]}}

    items = [art(1, "Lignes T1 et 2 déviées", ["T1", "2"]), art(2, "Tram coupé en centre-ville", ["T1"])]
    mod = mo.collect([issue(9, "restriction", form(
        rtype="Arrêté / interdiction", ville="Nancy", debut="13/10/2026", fin="16/10/2026",
        description="Interdiction des artifices et aérosols"))])
    rs = build_restrictions(items, mod.manual_restrictions, GAZ, FakeGeo())
    auto = next(r for r in rs if r["origin"] == "ia")
    manual = next(r for r in rs if r["origin"] == "manuel")
    assert auto["id"] == "r-2026-10-06-nancy-transport" and auto["lines"] == ["T1", "2"]
    assert len(auto["sources"]) == 2 and auto["geo_precision"] == "lieu"
    assert manual["type"] == "arrete" and manual["start"] == "2026-10-13" and manual["end"] == "2026-10-16"
    assert manual["verified"]
