import json

import pytest

from collector import ai, config
from collector.events import build_fr_events
from collector.extract import Gazetteer

GAZ = Gazetteer()


class FakeGeo:
    def locate(self, place, city, lat, lon):
        return (48.69, 6.18) if place == "place Stanislas" else None


class FakeResponse:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text or json.dumps(payload or {})

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    """Rejoue une liste de réponses et garde les requêtes reçues."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def post(self, url, json=None, timeout=None, headers=None):
        self.requests.append((url, json))
        return self.responses.pop(0)


def gemini(results):
    return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(results)}]}}]})


def item(n, title, published="2026-10-07T08:00:00+00:00", kind="presse", outlet="L'Est Républicain"):
    return {"id": f"id{n}", "kind": kind, "outlet": outlet, "title": title, "text": "",
            "url": f"https://exemple.fr/{n}", "published": published}


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(config, "AI_MIN_SECONDS_BETWEEN_CALLS", 0)
    monkeypatch.setattr(ai.time, "sleep", lambda s: None)


def test_clean_rejects_bad_values():
    out = ai._clean({
        "nature": "n'importe quoi", "veracite": "etabli",
        "evenements": [{"ville": "Nancy", "date": "jeudi", "heure": "25h", "lieu": None, "annule": False},
                       {"ville": "", "annule": False}],
        "causes": ["education", "inconnue"], "participants": -3, "resume": "x" * 500,
    })
    assert out["nature"] == "contexte"
    assert out["evenements"] == [{"ville": "Nancy", "pays": "France", "date": None, "heure": None,
                                  "lieu": None, "annule": False}]
    assert out["causes"] == ["education"]
    assert out["participants"] is None
    assert len(out["resume"]) == 160


def test_analyze_batches_and_stores(monkeypatch):
    monkeypatch.setattr(config, "AI_BATCH_SIZE", 2)
    monkeypatch.setattr(ai, "datetime", _FrozenDatetime)
    items = [item(i, f"Article {i}", published=f"2026-10-0{i + 1}T08:00:00+00:00") for i in range(3)]
    session = FakeSession([
        gemini([{"i": 0, "nature": "annonce", "veracite": "etabli", "evenements": [], "causes": [], "resume": "a"},
                {"i": 1, "nature": "contexte", "veracite": "etabli", "evenements": [], "causes": [], "resume": "b"}]),
        gemini([{"i": 0, "nature": "compte_rendu", "veracite": "etabli", "evenements": [], "causes": [], "resume": "c"}]),
    ])
    state = {}
    report = ai.Analyzer(state, session).analyze(items)
    assert report["analyzed"] == 3
    # Les plus récents sont analysés en premier.
    assert items[2]["ai"]["nature"] == "annonce"
    assert items[0]["ai"]["nature"] == "compte_rendu"
    assert state["ai"]["calls_today"] == 2
    # Un article déjà analysé ne repart pas à l'IA.
    assert ai.Analyzer(state, FakeSession([])).analyze(items)["analyzed"] == 0


def test_quota_stops_gracefully(monkeypatch):
    monkeypatch.setattr(ai, "datetime", _FrozenDatetime)
    items = [item(1, "Article")]
    report = ai.Analyzer({}, FakeSession([FakeResponse(429, text="quota")])).analyze(items)
    assert report["quota"] is True and report["pending"] == 1
    assert "ai" not in items[0]


def test_model_fallback_and_schema_fallback(monkeypatch):
    monkeypatch.setattr(ai, "datetime", _FrozenDatetime)
    ok = gemini([{"i": 0, "nature": "annonce", "veracite": "etabli", "evenements": [], "causes": [], "resume": ""}])
    session = FakeSession([FakeResponse(404), FakeResponse(400, text="schema"), ok])
    state = {}
    ai.Analyzer(state, session).analyze([item(1, "Article")])
    urls = [u for u, _ in session.requests]
    assert config.AI_MODELS[0] in urls[0] and config.AI_MODELS[1] in urls[1]
    assert "responseSchema" not in session.requests[2][1]["generationConfig"]
    assert state["ai"]["model"] == config.AI_MODELS[1]


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    assert ai.Analyzer({}).analyze([item(1, "x")]) == {"ok": True, "disabled": True}


# --- Intégration avec le regroupement en événements ----------------------------------

def with_ai(it, nature, veracite="etabli", events=(), causes=("education",)):
    it["ai"] = {"nature": nature, "veracite": veracite, "evenements": list(events), "causes": list(causes),
                "participants": None, "resume": f"résumé {it['id']}", "v": ai.PROMPT_VERSION, "model": "m"}
    return it


def ev(ville="Nancy", date="2026-10-08", heure=None, lieu=None, annule=False):
    return {"ville": ville, "pays": "France", "date": date, "heure": heure, "lieu": lieu, "annule": annule}


def test_context_articles_create_no_event():
    it = with_ai(item(1, "Mobilisation lycéenne à Nancy : les commerçants s'inquiètent"), "contexte")
    assert build_fr_events([it], GAZ, FakeGeo()) == []


def test_announcement_uses_ai_date_place_and_time():
    it = with_ai(item(1, "Les lycéens de Nancy appellent à manifester"), "annonce",
                 events=[ev(heure="10:00", lieu="place Stanislas")])
    [e] = build_fr_events([it], GAZ, FakeGeo())
    assert e["date"] == "2026-10-08" and e["date_precision"] == "ia"
    assert e["time"] == "10:00" and e["place"] == "place Stanislas" and e["geo_precision"] == "lieu"
    assert e["nature"] == "annoncee" and "annonce" in e["signals"]
    assert e["summary"] == "résumé id1"


def test_ai_finds_city_rules_would_miss():
    it = with_ai(item(1, "Blocus au lycée Loritz ce matin"), "en_cours", events=[ev(ville="nancy", date="2026-10-07")])
    [e] = build_fr_events([it], GAZ, FakeGeo())
    assert e["city"] == "Nancy" and e["nature"] == "attestee"


def test_rumour_only_is_flagged():
    it = with_ai(item(1, "Vrai ou faux : une manifestation à Metz ?"), "annonce", veracite="rumeur",
                 events=[ev(ville="Metz")])
    [e] = build_fr_events([it], GAZ, FakeGeo())
    assert "non_verifie" in e["signals"] and e["reliability"]["label"] == "Non vérifiée"


def test_rumour_confirmed_by_press_is_not_flagged():
    a = with_ai(item(1, "Rumeur de manifestation à Metz"), "annonce", veracite="rumeur", events=[ev(ville="Metz")])
    b = with_ai(item(2, "Manifestation à Metz", outlet="Le Républicain Lorrain"), "compte_rendu",
                events=[ev(ville="Metz")])
    [e] = build_fr_events([a, b], GAZ, FakeGeo())
    assert "non_verifie" not in e["signals"] and e["nature"] == "attestee"
    assert "annonce" not in e["signals"]


def test_mixed_ai_and_rules_items_merge():
    a = with_ai(item(1, "Les lycéens appellent à manifester jeudi à Nancy"), "annonce", events=[ev()])
    b = item(2, "Manifestation des lycéens ce jeudi à Nancy", published="2026-10-08T09:00:00+00:00",
             outlet="France 3")
    [e] = build_fr_events([a, b], GAZ, FakeGeo())
    assert e["source_count"] == 2 and e["reliability"]["label"] == "Probable"


class _FrozenDatetime(ai.datetime):
    @classmethod
    def now(cls, tz=None):
        return ai.datetime(2026, 10, 10, 12, 0, tzinfo=tz or ai.timezone.utc)
