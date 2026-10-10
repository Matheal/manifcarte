"""Récupération des sources. Chaque fonction renvoie une liste d'« items » (dict).

Format d'un item :
    id, kind ("presse" | "social" | "gdelt"), outlet, title, text, url, published (ISO UTC)
Les items GDELT portent en plus les champs déjà géolocalisés (lat, lon, place, country…).
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import time
import urllib.parse
import zipfile
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from . import config
from .extract import clean_text

log = logging.getLogger(__name__)

SESSION = requests.Session()
SESSION.headers["User-Agent"] = config.USER_AGENT


def _id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def _iso(struct) -> str | None:
    if not struct:
        return None
    return datetime(*struct[:6], tzinfo=timezone.utc).isoformat()


def _feed_items(content: bytes, outlet_default: str, kind: str = "presse") -> list[dict]:
    feed = feedparser.parse(content)
    items = []
    for e in feed.entries:
        title = clean_text(e.get("title", ""))
        outlet = outlet_default
        src = e.get("source")
        if src and src.get("title"):
            outlet = src["title"]
            suffix = f" - {outlet}"
            if title.endswith(suffix):
                title = title[: -len(suffix)]
        link = e.get("link")
        published = _iso(e.get("published_parsed") or e.get("updated_parsed"))
        if not (title and link and published):
            continue
        summary = clean_text(e.get("summary", ""))
        # Google News répète le titre dans le résumé : inutile de le garder.
        if summary.startswith(title[:40]):
            summary = ""
        items.append({
            "id": _id(link), "kind": kind, "outlet": outlet, "title": title,
            "text": summary[:600], "url": link, "published": published,
        })
    return items


def google_news() -> list[dict]:
    items: list[dict] = []
    for q in config.GOOGLE_NEWS_QUERIES:
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": f"{q} when:7d", "hl": "fr", "gl": "FR", "ceid": "FR:fr"})
        r = SESSION.get(url, timeout=config.HTTP_TIMEOUT)
        r.raise_for_status()
        items += _feed_items(r.content, "Google News")
        time.sleep(1)  # politesse
    return items


def rss_feeds() -> list[dict]:
    items: list[dict] = []
    for outlet, url in config.RSS_FEEDS.items():
        try:
            r = SESSION.get(url, timeout=config.HTTP_TIMEOUT)
            r.raise_for_status()
            items += _feed_items(r.content, outlet)
        except requests.RequestException as e:
            log.warning("RSS %s indisponible : %s", outlet, e)
    return items


def mastodon() -> list[dict]:
    items: list[dict] = []
    for instance in config.MASTODON_INSTANCES:
        for tag in config.MASTODON_TAGS:
            try:
                r = SESSION.get(f"https://{instance}/api/v1/timelines/tag/{tag}",
                                params={"limit": 40}, timeout=config.HTTP_TIMEOUT)
                r.raise_for_status()
            except requests.RequestException as e:
                log.warning("Mastodon %s #%s indisponible : %s", instance, tag, e)
                continue
            for post in r.json():
                if post.get("language") not in (None, "fr"):
                    continue
                text = clean_text(post.get("content", ""))
                url = post.get("url") or post.get("uri")
                if not text or not url:
                    continue
                # On ne conserve ni pseudo ni avatar : seulement le texte et le lien public.
                items.append({
                    "id": _id(url), "kind": "social", "outlet": f"Mastodon ({instance})",
                    "title": text[:140], "text": text[:600], "url": url,
                    "published": post["created_at"].replace("Z", "+00:00"),
                })
    return items


# --- GDELT ------------------------------------------------------------------------

GDELT_BASE = "https://data.gdeltproject.org/gdeltv2/"
CAMEO_PROTEST = {
    "140": "Manifestation", "141": "Manifestation", "1411": "Manifestation", "1412": "Manifestation",
    "1413": "Manifestation", "1414": "Manifestation", "142": "Grève de la faim",
    "143": "Grève / boycott", "1431": "Grève", "1432": "Boycott", "1433": "Grève", "1434": "Grève",
    "144": "Blocage", "1441": "Blocage", "1442": "Blocage", "1443": "Blocage", "1444": "Blocage",
    "145": "Manifestation violente", "1451": "Émeute", "1452": "Émeute", "1453": "Émeute", "1454": "Émeute",
}


def _gdelt_stamps(last: str | None) -> list[str]:
    """Liste des horodatages de fichiers GDELT (pas de 15 min) à télécharger."""
    r = SESSION.get(GDELT_BASE + "lastupdate.txt", timeout=config.HTTP_TIMEOUT)
    r.raise_for_status()
    newest = r.text.split()[2].rsplit("/", 1)[1][:14]
    end = datetime.strptime(newest, "%Y%m%d%H%M%S")
    if last:
        start = max(datetime.strptime(last, "%Y%m%d%H%M%S") + timedelta(minutes=15),
                    end - timedelta(minutes=15 * (config.GDELT_MAX_FILES_PER_RUN - 1)))
    else:
        start = end - timedelta(minutes=15 * (config.GDELT_BACKFILL_FILES - 1))
    stamps = []
    t = start
    while t <= end:
        stamps.append(t.strftime("%Y%m%d%H%M%S"))
        t += timedelta(minutes=15)
    return stamps


def gdelt(state: dict) -> list[dict]:
    """Événements de contestation (codes CAMEO 14x) hors pays exclus, agrégés par lieu et jour."""
    stamps = _gdelt_stamps(state.get("gdelt_last"))
    agg: dict[tuple, dict] = {}
    for stamp in stamps:
        try:
            r = SESSION.get(f"{GDELT_BASE}{stamp}.export.CSV.zip", timeout=60)
            if r.status_code == 404:
                continue
            r.raise_for_status()
        except requests.RequestException as e:
            log.warning("GDELT %s : %s", stamp, e)
            continue
        state["gdelt_last"] = stamp
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            reader = csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]), "utf-8", errors="replace"),
                                delimiter="\t")
            for row in reader:
                if len(row) < 61 or row[28] != "14":
                    continue
                geo_type, place, country = row[51], row[52], row[53]
                # 3/4 = ville ; 1/2/5 = pays ou région entière, trop imprécis pour une carte.
                if geo_type not in ("3", "4") or country in config.GDELT_EXCLUDE_COUNTRIES:
                    continue
                try:
                    lat, lon = float(row[56]), float(row[57])
                except ValueError:
                    continue
                day = f"{row[1][:4]}-{row[1][4:6]}-{row[1][6:8]}"
                key = (row[58] or place, day)
                a = agg.setdefault(key, {
                    "place": place, "country": country, "lat": lat, "lon": lon, "date": day,
                    "articles": 0, "sources": 0, "codes": {}, "urls": [],
                })
                a["articles"] += int(row[33] or 0)
                a["sources"] += int(row[32] or 0)
                label = CAMEO_PROTEST.get(row[26], "Manifestation")
                a["codes"][label] = a["codes"].get(label, 0) + 1
                if row[60] and row[60] not in a["urls"] and len(a["urls"]) < 5:
                    a["urls"].append(row[60])
        time.sleep(0.3)

    now = datetime.now(timezone.utc).isoformat()
    items = []
    for (fid, day), a in agg.items():
        items.append({
            "id": _id(f"gdelt:{fid}:{day}"), "kind": "gdelt", "outlet": "GDELT",
            "title": a["place"], "text": "", "url": a["urls"][0] if a["urls"] else "",
            "published": now, **a,
        })
    return items
