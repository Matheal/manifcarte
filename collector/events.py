"""Transforme les items stockés en événements (une manif = une commune + un jour)."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import config
from .extract import CAUSE_LABELS, Gazetteer, extract, is_relevant, slugify
from .geocode import Geocoder

TZ = ZoneInfo(config.TIMEZONE)
PRECISION_RANK = {"explicite": 0, "relative": 1, "publication": 2}

_KIND_RES = [
    ("Blocus", re.compile(r"\bblocus\b", re.I)),
    ("Grève", re.compile(r"\bgrève|grévistes?\b", re.I)),
    ("Rassemblement", re.compile(r"\brassemblement", re.I)),
    ("Marche", re.compile(r"\bmarche (?:blanche|pour|contre|des|du)", re.I)),
    ("Manifestation", re.compile(r"\bmanif|manifestant|cortège|défil", re.I)),
]


def _kind(texts: list[str]) -> str:
    joined = " ".join(texts)
    counts = {label: len(rx.findall(joined)) for label, rx in _KIND_RES}
    best = max(counts.items(), key=lambda kv: kv[1])
    return best[0] if best[1] else "Mobilisation"


def _local_date(iso: str) -> date:
    return datetime.fromisoformat(iso).astimezone(TZ).date()


def _reliability(press: int, social: int) -> dict:
    score = press + 0.5 * min(social, 2)
    if score >= 3:
        return {"level": 3, "label": "Confirmée", "score": score}
    if score >= 2:
        return {"level": 2, "label": "Probable", "score": score}
    return {"level": 1, "label": "À confirmer", "score": score}


def build_fr_events(items: list[dict], gaz: Gazetteer, geo: Geocoder) -> list[dict]:
    buckets: dict[tuple[str, date], list[tuple[dict, object, str]]] = defaultdict(list)
    for it in items:
        if it["kind"] == "gdelt":
            continue
        ref = _local_date(it["published"])
        ext = extract(it["title"], it.get("text", ""), ref, gaz)
        if not ext:
            continue
        dates = ext.dates or [(ref, "publication")]
        for commune in ext.communes:
            for d, precision in dates:
                buckets[(commune.insee, d)].append((it, ext, precision))

    events = []
    for (insee, d), contribs in buckets.items():
        commune = gaz.by_insee[insee]
        items_ = {c[0]["url"]: c[0] for c in contribs}.values()
        press_outlets = {i["outlet"] for i in items_ if i["kind"] == "presse"}
        social = sum(1 for i in items_ if i["kind"] == "social")

        causes: Counter = Counter()
        signals: set[str] = set()
        places: Counter = Counter()
        times: Counter = Counter()
        participants = None
        for it, ext, _ in contribs:
            for rank, cause in enumerate(ext.causes):
                causes[cause] += 3 - rank
            signals.update(ext.signals)
            # Lieu, heure et chiffres ne sont fiables que si l'article ne parle
            # que d'une ville et d'une mobilisation dès son titre.
            focused = len(ext.communes) == 1 and is_relevant(it["title"])
            if focused:
                places.update(ext.places)
                if ext.participants:
                    participants = max(participants or 0, ext.participants)
                if ext.time and len(ext.dates) <= 1:
                    times[ext.time] += 1

        lat, lon, precision_geo, place = commune.lat, commune.lon, "commune", None
        for candidate, _ in places.most_common(3):
            hit = geo.locate(candidate, commune.name, commune.lat, commune.lon)
            if hit:
                lat, lon, precision_geo, place = hit[0], hit[1], "lieu", candidate
                break

        sources = sorted(
            ({"title": i["title"], "url": i["url"], "outlet": i["outlet"], "kind": i["kind"],
              "published": i["published"]} for i in items_),
            key=lambda s: s["published"], reverse=True,
        )
        # Titre mis en avant : un article de presse qui cite la ville et la mobilisation.
        def headline_rank(src: dict) -> tuple:
            t = src["title"]
            return (src["kind"] == "presse", commune.name in t, is_relevant(t), src["published"])
        headline = max(sources, key=headline_rank)["title"]
        kind = _kind([s["title"] for s in sources] + [i.get("text", "") for i in items_])
        cause_keys = [c for c, _ in causes.most_common(4) if c != "autre"][:3] or ["autre"]
        events.append({
            "id": f"{d.isoformat()}-{slugify(commune.name)}",
            "scope": "fr",
            "kind": kind,
            "title": f"{kind} à {commune.name}",
            "headline": headline,
            "city": commune.name,
            "insee": commune.insee,
            "dep": commune.dep,
            "country": "France",
            "lat": lat,
            "lon": lon,
            "geo_precision": precision_geo,
            "place": place,
            "date": d.isoformat(),
            "date_precision": min((c[2] for c in contribs), key=PRECISION_RANK.__getitem__),
            "time": times.most_common(1)[0][0] if times else None,
            "causes": cause_keys,
            "cause_labels": [CAUSE_LABELS[c] for c in cause_keys],
            "signals": sorted(signals),
            "participants": participants,
            "reliability": _reliability(len(press_outlets), social),
            "source_count": len(sources),
            "sources": sources[:12],
        })
    return events


def build_world_events(items: list[dict]) -> list[dict]:
    events = []
    for it in items:
        if it["kind"] != "gdelt" or it["articles"] < config.GDELT_MIN_ARTICLES:
            continue
        parts = [p.strip() for p in it["place"].split(",")]
        city, country = parts[0], parts[-1]
        label = max(it["codes"].items(), key=lambda kv: kv[1])[0]
        level = 3 if it["sources"] >= 15 else 2 if it["sources"] >= 5 else 1
        events.append({
            "id": f"{it['date']}-w-{slugify(city)}-{it['id'][:6]}",
            "scope": "world",
            "kind": label,
            "title": f"{label} à {city}",
            "headline": f"{label} signalée à {it['place']}",
            "city": city,
            "country": country,
            "lat": round(it["lat"], 4),
            "lon": round(it["lon"], 4),
            "geo_precision": "commune",
            "place": None,
            "date": it["date"],
            "date_precision": "publication",
            "time": None,
            "causes": ["autre"],
            "cause_labels": [],
            "signals": ["tensions"] if label in ("Manifestation violente", "Émeute") else [],
            "participants": None,
            "reliability": {"level": level, "label": "Détection automatique", "score": it["sources"]},
            "source_count": it["articles"],
            "sources": [{"title": u.split("//", 1)[-1][:90], "url": u, "outlet": u.split("/")[2],
                         "kind": "presse", "published": it["published"]} for u in it["urls"]],
        })
    return events
