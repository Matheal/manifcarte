"""Restrictions et perturbations liées aux mobilisations.

Deux origines :
  - l'IA, qui les repère dans les articles (« lignes de bus déviées », « gare fermée »,
    « arrêté préfectoral interdisant… ») ;
  - les signalements manuels validés (formulaire GitHub « restriction »).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date

from .events import MANUAL_OUTLET, _local_date, resolve_city
from .extract import Gazetteer, slugify
from .geocode import Geocoder

TYPE_LABELS = {
    "transport": "Transports perturbés",
    "circulation": "Circulation restreinte",
    "etablissement": "Établissement fermé ou perturbé",
    "arrete": "Arrêté / interdiction",
    "commerce": "Commerces et services fermés",
    "autre": "Autre perturbation",
}
MAX_DURATION_DAYS = 60


def _dates(pt: dict, ref: date) -> tuple[date, date] | None:
    start = date.fromisoformat(pt["debut"]) if pt.get("debut") else ref
    end = date.fromisoformat(pt["fin"]) if pt.get("fin") else start
    if not (-30 <= (start - ref).days <= 45) or end < start or (end - start).days > MAX_DURATION_DAYS:
        return None
    return start, end


def _locate(place: str | None, commune, geo: Geocoder) -> tuple[float, float, str, str | None]:
    if place and commune.insee:
        hit = geo.locate(place, commune.name, commune.lat, commune.lon)
        if hit:
            return hit[0], hit[1], "lieu", place
    return commune.lat, commune.lon, "commune", None


def build_restrictions(items: list[dict], manual: list[dict], gaz: Gazetteer, geo: Geocoder) -> list[dict]:
    groups: dict[tuple, list[tuple[dict, dict, date, date]]] = defaultdict(list)
    for it in items:
        ai = it.get("ai") or {}
        if ai.get("nature") == "hors_sujet":
            continue
        ref = _local_date(it["published"])
        for pt in ai.get("perturbations", []):
            commune = gaz.lookup(pt["ville"])
            span = _dates(pt, ref)
            if not commune or not span:
                continue
            # Une restriction = une ville + un type + un jour de début (plusieurs articles fusionnés).
            groups[(commune.insee, pt["type"], span[0])].append((it, pt, *span))

    out = []
    for (insee, rtype, start), entries in groups.items():
        commune = gaz.by_insee[insee]
        entries.sort(key=lambda e: e[0]["published"], reverse=True)
        places = Counter(pt["lieu"] for _, pt, _, _ in entries if pt["lieu"])
        lat, lon, precision, place = _locate(places.most_common(1)[0][0] if places else None, commune, geo)
        descriptions = list(dict.fromkeys(pt["description"] for _, pt, _, _ in entries))
        lines = list(dict.fromkeys(line for _, pt, _, _ in entries for line in pt["lignes"]))
        sources = list({it["id"]: {"title": it["title"], "url": it["url"], "outlet": it["outlet"],
                                   "kind": it["kind"], "published": it["published"]}
                        for it, _, _, _ in entries}.values())
        out.append({
            "id": f"r-{start.isoformat()}-{slugify(commune.name)}-{rtype}",
            "type": rtype,
            "type_label": TYPE_LABELS[rtype],
            "city": commune.name,
            "lat": lat, "lon": lon, "geo_precision": precision, "place": place,
            "start": start.isoformat(),
            "end": max(e[3] for e in entries).isoformat(),
            "description": descriptions[0],
            "details": descriptions[1:4],
            "lines": lines[:10],
            "origin": "ia",
            "verified": False,
            "sources": sources[:8],
        })

    for m in manual:
        resolved = resolve_city(m["ville"], gaz, geo)
        if not resolved:
            continue
        _, commune, _ = resolved
        lat, lon, precision, place = _locate(m["lieu"], commune, geo)
        out.append({
            "id": f"r-m{m['issue']}",
            "type": m["type"],
            "type_label": TYPE_LABELS[m["type"]],
            "city": commune.name,
            "lat": lat, "lon": lon, "geo_precision": precision, "place": place or m["lieu"],
            "start": m["debut"].isoformat(),
            "end": m["fin"].isoformat(),
            "description": m["description"],
            "details": [],
            "lines": m["lignes"],
            "origin": "manuel",
            "verified": True,
            "sources": [{"title": m["description"][:120], "url": m["source"], "outlet": MANUAL_OUTLET,
                         "kind": "manuel", "published": m["debut"].isoformat() + "T00:00:00+00:00"}],
        })
    out.sort(key=lambda r: (r["start"], r["city"]), reverse=True)
    return out
