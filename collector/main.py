"""Point d'entrée du collecteur.

    python -m collector.main                       # collecte complète
    python -m collector.main --skip gdelt mastodon # sans certaines sources
    python -m collector.main --offline             # recalcule depuis les données stockées

Fichiers lus/écrits dans --data-dir : items.json (articles), state.json, geocache.json.
Fichier produit : --out (events.json lu par le site).
"""
from __future__ import annotations

import argparse
import json
import logging
import pathlib
from datetime import datetime, timedelta, timezone

from . import config, sources
from . import moderation
from .ai import Analyzer
from .restrictions import build_restrictions
from .events import _local_date, build_fr_events, build_world_events
from .extract import Gazetteer, extract
from .geocode import Geocoder

ROOT = pathlib.Path(__file__).resolve().parent.parent
log = logging.getLogger("collector")


def _load(path: pathlib.Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _dump(path: pathlib.Path, data, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=1 if pretty else None,
                      separators=None if pretty else (",", ":"))
    path.write_text(text, encoding="utf-8")


def merge_items(stored: dict[str, dict], new: list[dict]) -> int:
    added = 0
    for it in new:
        old = stored.get(it["id"])
        if old is None:
            stored[it["id"]] = it
            added += 1
        elif it["kind"] == "gdelt":
            # Même lieu, même jour : on cumule les compteurs vus dans les nouveaux fichiers.
            old["articles"] += it["articles"]
            old["sources"] += it["sources"]
            for k, v in it["codes"].items():
                old["codes"][k] = old["codes"].get(k, 0) + v
            old["urls"] = (old["urls"] + [u for u in it["urls"] if u not in old["urls"]])[:5]
    return added


def prune(stored: dict[str, dict], now: datetime) -> None:
    for key in list(stored):
        it = stored[key]
        keep = config.KEEP_DAYS_WORLD if it["kind"] == "gdelt" else config.KEEP_DAYS_FR
        stamp = it.get("date") if it["kind"] == "gdelt" else it["published"][:10]
        if stamp < (now - timedelta(days=keep)).date().isoformat():
            del stored[key]


def run(data_dir: pathlib.Path, out: pathlib.Path, skip: set[str], offline: bool) -> dict:
    now = datetime.now(timezone.utc)
    stored: dict[str, dict] = {it["id"]: it for it in _load(data_dir / "items.json", [])}
    state = _load(data_dir / "state.json", {})
    gaz = Gazetteer(ROOT / "data" / "communes.json")
    status: dict[str, dict] = state.get("sources", {})

    fetchers = {
        "google_news": sources.google_news,
        "rss": sources.rss_feeds,
        "mastodon": sources.mastodon,
        "gdelt": lambda: sources.gdelt(state) if config.GDELT_ENABLED else [],
    }
    if not offline:
        for name, fetch in fetchers.items():
            if name in skip:
                continue
            try:
                got = fetch()
            except Exception as e:  # une source en panne ne doit pas bloquer les autres
                log.exception("Source %s en échec", name)
                status[name] = {"ok": False, "at": now.isoformat(), "error": str(e)[:200],
                                "last_ok": status.get(name, {}).get("last_ok")}
                continue
            # On ne stocke que les articles utiles (localisables et parlant d'une mobilisation).
            if name != "gdelt":
                got = [it for it in got
                       if extract(it["title"], it["text"], _local_date(it["published"]), gaz)]
            added = merge_items(stored, got)
            status[name] = {"ok": True, "at": now.isoformat(), "last_ok": now.isoformat(),
                            "fetched": len(got), "added": added}
            log.info("%-12s %4d pertinents, %4d nouveaux", name, len(got), added)

    prune(stored, now)
    items = list(stored.values())

    # Analyse IA des nouveaux articles (sans effet si GEMINI_API_KEY est absente).
    if "ai" not in skip:
        analyzer = Analyzer(state)
        try:
            report = analyzer.analyze(items)
            status["ai"] = {**report, "at": now.isoformat(), "fetched": report.get("analyzed", 0),
                            "added": report.get("analyzed", 0), "model": state.get("ai", {}).get("model"),
                            "last_ok": now.isoformat() if not report.get("disabled") else None}
            log.info("ia           %s", report)
        except Exception as e:  # l'IA ne doit jamais bloquer la mise à jour de la carte
            log.exception("Analyse IA en échec")
            status["ai"] = {"ok": False, "at": now.isoformat(), "error": str(e)[:200],
                            "last_ok": status.get("ai", {}).get("last_ok")}

    # Contributions validées (ajouts, restrictions, suppressions) depuis les issues GitHub.
    mod, gh = moderation.Moderation(), None
    try:
        mod, gh = moderation.load()
        status["moderation"] = {"ok": True, "at": now.isoformat(), "last_ok": now.isoformat(),
                                "fetched": len(mod.statuses), "added": len(mod.manual_events),
                                "pending": mod.pending}
    except Exception as e:
        log.exception("Lecture des contributions en échec")
        status["moderation"] = {"ok": False, "at": now.isoformat(), "error": str(e)[:200],
                                "last_ok": status.get("moderation", {}).get("last_ok")}
    usable = [it for it in items if it["url"] not in mod.removed_urls]

    geo = Geocoder(data_dir / "geocache.json")
    events = build_fr_events(usable, gaz, geo, mod.manual_events) + build_world_events(usable)
    events = [e for e in events if e["id"] not in mod.removed_events]
    events.sort(key=lambda e: (e["date"], e["reliability"]["score"]), reverse=True)
    restrictions = [r for r in build_restrictions(usable, mod.manual_restrictions, gaz, geo)
                    if r["id"] not in mod.removed_restrictions]
    geo.save()
    moderation.notify(mod, gh, state.setdefault("moderation", {}))

    state["sources"] = status
    _dump(data_dir / "items.json", sorted(items, key=lambda i: i["id"]))
    _dump(data_dir / "state.json", state, pretty=True)
    payload = {
        "generated_at": now.isoformat(),
        "focus": config.FOCUS_CITY,
        "sources": status,
        "count": {"fr": sum(e["scope"] == "fr" for e in events),
                  "world": sum(e["scope"] == "world" for e in events)},
        "events": events,
        "restrictions": restrictions,
        "moderation": {
            "pending": mod.pending,
            "manual_events": len(mod.manual_events),
            "manual_restrictions": len(mod.manual_restrictions),
            "removed": len(mod.removed_events) + len(mod.removed_urls) + len(mod.removed_restrictions),
        },
    }
    _dump(out, payload)
    log.info("%d événements (%d France, %d monde), %d restrictions -> %s", len(events),
             payload["count"]["fr"], payload["count"]["world"], len(restrictions), out)
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description="Collecte des mobilisations")
    ap.add_argument("--data-dir", type=pathlib.Path, default=ROOT / "data" / "store")
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "site" / "public" / "data" / "events.json")
    ap.add_argument("--skip", nargs="*", default=[], choices=["google_news", "rss", "mastodon", "gdelt", "ai"])
    ap.add_argument("--offline", action="store_true", help="ne rien télécharger, recalculer seulement")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args.data_dir.mkdir(parents=True, exist_ok=True)
    run(args.data_dir, args.out, set(args.skip), args.offline)


if __name__ == "__main__":
    main()
