"""Transforme les items stockés en événements (une manif = une commune + un jour)."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import config
from .extract import CAUSE_LABELS, Commune, Gazetteer, extract, is_relevant, slugify
from .geocode import Geocoder

TZ = ZoneInfo(config.TIMEZONE)
PRECISION_RANK = {"explicite": 0, "ia": 0, "relative": 1, "publication": 2}

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


@dataclass
class Contribution:
    """Ce qu'un article apporte à une mobilisation (ville + jour)."""
    item: dict
    precision: str                       # explicite | relative | ia | publication
    causes: list[str]
    signals: set[str]
    places: list[str] = field(default_factory=list)
    time: str | None = None
    participants: int | None = None
    nature: str | None = None            # nature selon l'IA (None = analyse par règles)
    veracite: str | None = None
    resume: str | None = None
    kind_override: str | None = None


# Natures pour lesquelles un article ne crée pas de point sur la carte.
IGNORED_NATURES = {"contexte", "hors_sujet", "rappel_ancien"}
_AI_SIGNALS = {"annonce", "annulee", "interdite"}  # remplacés par le jugement de l'IA


def _from_ai(it: dict, ref: date, gaz: Gazetteer, ext) -> list[tuple[str, date, Contribution]]:
    ai = it["ai"]
    if ai["nature"] in IGNORED_NATURES:
        return []
    signals = (set(ext.signals) if ext else set()) - _AI_SIGNALS
    if ai["nature"] == "annonce":
        signals.add("annonce")
    if ai["veracite"] in ("rumeur", "non_verifie"):
        signals.add("non_verifie")
    if ai["veracite"] == "dementi":
        signals.add("dementi")
    out = []
    for ev in ai["evenements"]:
        if ev["pays"].lower() not in ("france", "fr"):
            continue  # l'international est couvert par GDELT
        commune = gaz.lookup(ev["ville"])
        if not commune:
            continue
        d, precision = ref, "publication"
        candidate = date.fromisoformat(ev["date"]) if ev["date"] else None
        # Garde-fou contre une date aberrante.
        if candidate and -30 <= (candidate - ref).days <= 45:
            d, precision = candidate, "ia"
        else:
            # Date trouvée par les règles ; pour une annonce, seulement une date à venir.
            rule_dates = [(x, pr) for x, pr in (ext.dates if ext else [])
                          if ai["nature"] != "annonce" or x >= ref]
            if rule_dates:
                d, precision = rule_dates[0]
            elif ai["nature"] == "annonce":
                continue  # annonce sans date connue : on ne la place pas « aujourd'hui » par erreur
        out.append((commune.insee, d, Contribution(
            item=it, precision=precision,
            causes=ai["causes"] or ["autre"],
            signals=signals | ({"annulee"} if ev["annule"] else set()),
            places=[ev["lieu"]] if ev["lieu"] else [],
            time=ev["heure"], participants=ai["participants"],
            nature=ai["nature"], veracite=ai["veracite"], resume=ai["resume"],
        )))
    return out


def _from_rules(it: dict, ext) -> list[tuple[str, date, Contribution]]:
    # Lieu, heure et chiffres ne sont fiables que si l'article ne parle
    # que d'une ville et d'une mobilisation dès son titre.
    focused = len(ext.communes) == 1 and is_relevant(it["title"])
    dates = ext.dates or [(_local_date(it["published"]), "publication")]
    out = []
    for commune in ext.communes:
        for d, precision in dates:
            out.append((commune.insee, d, Contribution(
                item=it, precision=precision, causes=ext.causes, signals=set(ext.signals),
                places=ext.places if focused else [],
                time=ext.time if focused and len(ext.dates) <= 1 else None,
                participants=ext.participants if focused else None,
            )))
    return out


MANUAL_OUTLET = "Ajout vérifié par l'équipe ManifCarte"


def _from_gdelt_fr(it: dict, gaz: Gazetteer) -> list[tuple[str, date, Contribution]]:
    """Événement GDELT situé en France : rattaché à la commune (point 6)."""
    if it.get("country") != "FR" or it["articles"] < config.GDELT_MIN_ARTICLES:
        return []
    commune = gaz.lookup(it["place"].split(",")[0].strip())
    if not commune:
        return []
    return [(commune.insee, date.fromisoformat(it["date"]), Contribution(
        item=it, precision="publication", causes=["autre"],
        signals={"tensions"} if any(k in it["codes"] for k in ("Manifestation violente", "Émeute")) else set(),
    ))]


def resolve_city(name: str, gaz: Gazetteer, geo: Geocoder) -> tuple[str, Commune, str] | None:
    """(clé, commune, pays) : commune française connue, sinon géocodage libre (France ou monde)."""
    commune = gaz.lookup(name)
    if commune:
        return commune.insee, commune, "France"
    hit = geo.locate_city(name)
    if not hit:
        return None
    lat, lon, city, country = hit
    return f"geo:{slugify(city)}", Commune(city, "", "", lon, lat, 0), country or "France"


def _from_manual(m: dict, gaz: Gazetteer, geo: Geocoder) -> tuple[str, date, Contribution, Commune, str] | None:
    resolved = resolve_city(m["ville"], gaz, geo)
    if not resolved:
        return None
    key, commune, country = resolved
    future = m["date"] > m["created"]
    pseudo = {
        "id": f"manuel-{m['issue']}", "kind": "manuel", "outlet": MANUAL_OUTLET,
        "title": m["description"] or f"{m['kind']} signalée à {commune.name}",
        "url": m["source"], "published": datetime.combine(m["created"], datetime.min.time(), TZ).isoformat(),
    }
    contrib = Contribution(
        item=pseudo, precision="explicite", causes=[m["cause"]],
        signals={"annonce", "verifie"} if future else {"verifie"},
        places=[m["lieu"]] if m["lieu"] else [], time=m["heure"],
        nature="annonce" if future else "compte_rendu", veracite="etabli",
        resume=(m["description"] or None) and m["description"][:160],
    )
    contrib.kind_override = m["kind"]
    return key, m["date"], contrib, commune, country


def build_fr_events(items: list[dict], gaz: Gazetteer, geo: Geocoder,
                    manual: list[dict] = ()) -> list[dict]:
    buckets: dict[tuple[str, date], list[Contribution]] = defaultdict(list)
    places_by_key: dict[str, tuple[Commune, str]] = {}
    for m in manual:
        found = _from_manual(m, gaz, geo)
        if found:
            key, d, contrib, commune, country = found
            buckets[(key, d)].append(contrib)
            places_by_key[key] = (commune, country)
    for it in items:
        if it["kind"] == "gdelt":
            found = _from_gdelt_fr(it, gaz)
            for key, d, contrib in found:
                buckets[(key, d)].append(contrib)
            continue
        ref = _local_date(it["published"])
        ext = extract(it["title"], it.get("text", ""), ref, gaz)
        if it.get("ai"):
            found = _from_ai(it, ref, gaz, ext)
        else:
            found = _from_rules(it, ext) if ext else []
        for insee, d, contrib in found:
            buckets[(insee, d)].append(contrib)

    events = []
    for (key, d), contribs in buckets.items():
        # GDELT seul (sans presse ni contribution) : seulement s'il y a beaucoup d'articles.
        if all(c.item["kind"] == "gdelt" for c in contribs) and \
                sum(c.item["articles"] for c in contribs) < config.GDELT_FR_MIN_ARTICLES_ALONE:
            continue
        commune, country = places_by_key.get(key) or (gaz.by_insee[key], "France")
        items_ = {c.item["id"]: c.item for c in contribs}.values()
        manual_contribs = [c for c in contribs if c.item["kind"] == "manuel"]
        press_outlets = {i["outlet"] for i in items_ if i["kind"] == "presse"}
        # Signaux plus faibles qu'un média : réseaux sociaux, agendas militants, détection GDELT.
        social = sum(1 for i in items_ if i["kind"] in ("social", "agenda", "gdelt"))

        causes: Counter = Counter()
        signals: set[str] = set()
        places: Counter = Counter()
        times: Counter = Counter()
        participants = None
        for c in contribs:
            for rank, cause in enumerate(c.causes):
                causes[cause] += 3 - rank
            signals |= c.signals
            places.update(c.places)
            if c.time:
                times[c.time] += 1
            if c.participants:
                participants = max(participants or 0, c.participants)

        # Synthèse du jugement de l'IA sur l'ensemble des articles.
        ai_contribs = [c for c in contribs if c.nature and c.item["kind"] != "manuel"]
        natures = Counter(c.nature for c in ai_contribs + manual_contribs)
        nature = None
        if ai_contribs or manual_contribs:
            nature = "attestee" if natures["compte_rendu"] or natures["en_cours"] else "annoncee"
        verification = None
        established = [c for c in contribs if c.veracite == "etabli" or (not c.nature and c.item["kind"] == "presse")]
        if any(c.veracite == "dementi" for c in contribs):
            verification = "dementi"
        elif ai_contribs and not established:
            verification = "non_verifie"
        signals.discard("non_verifie")
        signals.discard("dementi")
        if verification:
            signals.add(verification)
        # Annulée seulement si la majorité des articles le disent.
        if "annulee" in signals and sum("annulee" in c.signals for c in contribs) * 2 < len(contribs):
            signals.discard("annulee")
        if nature == "attestee":
            signals.discard("annonce")

        lat, lon, precision_geo, place = commune.lat, commune.lon, "commune", None
        for candidate, _ in places.most_common(3):
            hit = geo.locate(candidate, commune.name, commune.lat, commune.lon)
            if hit:
                lat, lon, precision_geo, place = hit[0], hit[1], "lieu", candidate
                break

        sources = sorted(
            ({"title": i["title"] if i["kind"] != "gdelt" else f"Détection automatique GDELT ({i['articles']} articles)",
              "url": i["url"], "outlet": i["outlet"], "kind": i["kind"],
              "published": i["published"]} for i in items_),
            key=lambda s: s["published"], reverse=True,
        )

        # Titre mis en avant : un article de presse qui cite la ville et la mobilisation.
        def headline_rank(src: dict) -> tuple:
            t = src["title"]
            return (src["kind"] == "presse", commune.name in t, is_relevant(t), src["published"])

        headline = max(sources, key=headline_rank)["title"]
        # Résumé IA : de préférence celui d'un compte rendu de presse récent.
        summaries = sorted(
            (c for c in ai_contribs if c.resume),
            key=lambda c: (c.item["kind"] == "presse", c.nature in ("compte_rendu", "en_cours"),
                           c.item["published"]),
        )
        overrides = [c.kind_override for c in manual_contribs if c.kind_override]
        kind = overrides[0] if overrides else _kind([s["title"] for s in sources] + [i.get("text", "") for i in items_])
        cause_keys = [c for c, _ in causes.most_common(4) if c != "autre"][:3] or ["autre"]
        reliability = _reliability(len(press_outlets), social)
        if verification == "dementi":
            reliability = {"level": 1, "label": "Démentie", "score": 0}
        elif verification == "non_verifie":
            reliability = {"level": 1, "label": "Non vérifiée", "score": min(reliability["score"], 1)}
        if manual_contribs and verification != "dementi":
            # Validé par l'équipe : on fait confiance, même sans article de presse.
            reliability = {"level": 3, "label": "Vérifiée par l'équipe", "score": 10 + reliability["score"]}
            signals.discard("non_verifie")
        events.append({
            "id": f"{d.isoformat()}-{slugify(commune.name)}",
            "scope": "fr" if country == "France" else "world",
            "kind": kind,
            "title": f"{kind} à {commune.name}",
            "headline": headline,
            "summary": (summaries[-1].resume if summaries
                        else next((c.resume for c in manual_contribs if c.resume), None)),
            "verified": bool(manual_contribs),
            "nature": nature,
            "ai_count": len({c.item["url"] for c in ai_contribs}),
            "city": commune.name,
            "insee": commune.insee or None,
            "dep": commune.dep or None,
            "country": country,
            "lat": lat,
            "lon": lon,
            "geo_precision": precision_geo,
            "place": place,
            "date": d.isoformat(),
            "date_precision": min((c.precision for c in contribs), key=PRECISION_RANK.__getitem__),
            "time": times.most_common(1)[0][0] if times else None,
            "causes": cause_keys,
            "cause_labels": [CAUSE_LABELS[c] for c in cause_keys],
            "signals": sorted(signals),
            "participants": participants,
            "reliability": reliability,
            "source_count": len(sources),
            "sources": sources[:12],
        })
    return events


def build_world_events(items: list[dict]) -> list[dict]:
    events = []
    for it in items:
        if it["kind"] != "gdelt" or it["articles"] < config.GDELT_MIN_ARTICLES or it.get("country") == "FR":
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
