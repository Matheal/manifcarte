"""Récupération des sources. Chaque fonction renvoie une liste d'« items » (dict).

Format d'un item :
    id, kind ("presse" | "agenda" | "social" | "gdelt"), outlet, title, text, url, published (ISO UTC)
Les items GDELT portent en plus les champs déjà géolocalisés (lat, lon, place, country…).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import pathlib
import time
import urllib.parse
import zipfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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


def _google_news_search(query: str, window: str) -> list[dict]:
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": f"{query} when:{window}", "hl": "fr", "gl": "FR", "ceid": "FR:fr"})
    r = SESSION.get(url, timeout=config.HTTP_TIMEOUT)
    r.raise_for_status()
    time.sleep(1)  # politesse
    return _feed_items(r.content, "Google News")


def _rotating_cities(state: dict) -> list[str]:
    """Les plus grandes communes, par tranches qui tournent d'un passage à l'autre."""
    rows = json.loads((pathlib.Path(__file__).resolve().parent.parent / "data" / "communes.json")
                      .read_text(encoding="utf-8"))
    cities = [r[0] for r in rows[: config.GOOGLE_NEWS_CITY_COUNT]]
    start = state.get("gnews_cursor", 0) % len(cities)
    batch = (cities + cities)[start:start + config.GOOGLE_NEWS_CITIES_PER_RUN]
    state["gnews_cursor"] = start + len(batch)
    focus = config.FOCUS_CITY["name"]
    return [focus] + [c for c in batch if c != focus]


def google_news(state: dict | None = None) -> list[dict]:
    items: list[dict] = []
    for q in config.GOOGLE_NEWS_QUERIES:
        items += _google_news_search(q, "7d")
    for city in _rotating_cities(state if state is not None else {}):
        try:
            items += _google_news_search(config.GOOGLE_NEWS_CITY_QUERY.format(city=city), "3d")
        except requests.RequestException as e:
            log.warning("Google News « %s » : %s", city, e)
    return items


def rss_feeds() -> list[dict]:
    items: list[dict] = []
    for outlet, (url, kind) in config.RSS_FEEDS.items():
        try:
            r = SESSION.get(url, timeout=config.HTTP_TIMEOUT)
            r.raise_for_status()
            items += _feed_items(r.content, outlet, kind)
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


# --- Agendas (Démosphère, Mobilizon) ---------------------------------------------------

_FR_WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_FR_MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
              "octobre", "novembre", "décembre"]


def _fr_datetime(dt: datetime) -> str:
    """« samedi 17 octobre 2026 à 15h00 » : lisible par les règles d'extraction et par l'IA."""
    local = dt.astimezone(ZoneInfo(config.TIMEZONE))
    return (f"{_FR_WEEKDAYS[local.weekday()]} {local.day} {_FR_MONTHS[local.month - 1]} {local.year} "
            f"à {local.hour}h{local.minute:02d}")


def demosphere() -> list[dict]:
    """Agendas Démosphère : titres du type « mardi 13 octobre 2026 - Rennes - Manifestation… »."""
    items: list[dict] = []
    for city in config.DEMOSPHERE_CITIES:
        try:
            r = SESSION.get(f"https://{city}.demosphere.net/events.xml", timeout=config.HTTP_TIMEOUT)
            r.raise_for_status()
        except requests.RequestException as e:
            log.warning("Démosphère %s indisponible : %s", city, e)
            continue
        items += _feed_items(r.content, f"Démosphère {city.capitalize()}", "agenda")
    return items


_MOBILIZON_QUERY = """query($term: String, $limit: Int) {
  searchEvents(term: $term, limit: $limit) {
    elements { title url beginsOn physicalAddress { description locality } }
  }
}"""


def mobilizon() -> list[dict]:
    """Événements publics Mobilizon à venir (ou des 2 derniers jours)."""
    now = datetime.now(timezone.utc)
    items: dict[str, dict] = {}
    for instance in config.MOBILIZON_INSTANCES:
        for term in config.MOBILIZON_TERMS:
            try:
                r = SESSION.post(f"https://{instance}/api", timeout=config.HTTP_TIMEOUT,
                                 json={"query": _MOBILIZON_QUERY, "variables": {"term": term, "limit": 50}})
                r.raise_for_status()
                elements = r.json()["data"]["searchEvents"]["elements"]
            except (requests.RequestException, KeyError, TypeError, ValueError) as e:
                log.warning("Mobilizon %s « %s » : %s", instance, term, e)
                continue
            for ev in elements:
                try:
                    begins = datetime.fromisoformat(ev["beginsOn"].replace("Z", "+00:00"))
                except (KeyError, TypeError, ValueError):
                    continue
                if not (now - timedelta(days=2) <= begins <= now + timedelta(days=45)) or not ev.get("url"):
                    continue
                addr = ev.get("physicalAddress") or {}
                where = ", ".join(x for x in (addr.get("description"), addr.get("locality")) if x)
                title = clean_text(ev.get("title", ""))
                text = f"{title}. Le {_fr_datetime(begins)}" + (f", {where}." if where else ".")
                items[ev["url"]] = {
                    "id": _id(ev["url"]), "kind": "agenda", "outlet": f"Mobilizon ({instance})",
                    "title": title[:200], "text": text[:600], "url": ev["url"],
                    # Date de « parution » = maintenant : la date de l'événement est dans le texte.
                    "published": now.isoformat(),
                }
            time.sleep(0.5)
    return list(items.values())


# --- Bluesky -----------------------------------------------------------------------

def bluesky(state: dict) -> list[dict] | None:
    """Recherche de publications publiques en français (compte robot requis, sinon None)."""
    # Tolère les erreurs de saisie courantes : « @ » devant l'identifiant, espaces, retour à la ligne.
    handle = (os.environ.get("BSKY_HANDLE") or "").strip().lstrip("@").strip()
    password = (os.environ.get("BSKY_APP_PASSWORD") or "").strip()
    if not handle or not password:
        return None
    r = SESSION.post("https://bsky.social/xrpc/com.atproto.server.createSession",
                     json={"identifier": handle, "password": password}, timeout=config.HTTP_TIMEOUT)
    if r.status_code == 401:
        raise RuntimeError("Bluesky refuse la connexion : vérifie BSKY_HANDLE (sans @) "
                           "et BSKY_APP_PASSWORD (mot de passe d'application, pas celui du compte)")
    r.raise_for_status()
    token = r.json()["accessJwt"]
    since = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    items: dict[str, dict] = {}
    for q in config.BLUESKY_QUERIES:
        try:
            r = SESSION.get("https://bsky.social/xrpc/app.bsky.feed.searchPosts", timeout=config.HTTP_TIMEOUT,
                            headers={"Authorization": f"Bearer {token}"},
                            params={"q": q, "lang": "fr", "since": since, "limit": 100, "sort": "latest"})
            r.raise_for_status()
        except requests.RequestException as e:
            log.warning("Bluesky « %s » : %s", q, e)
            continue
        for post in r.json().get("posts", []):
            text = clean_text((post.get("record") or {}).get("text", ""))
            uri, author = post.get("uri", ""), (post.get("author") or {}).get("handle", "")
            if not text or not uri.startswith("at://") or not author:
                continue
            # Lien public vers la publication ; on ne conserve ni pseudo ni avatar dans le texte.
            url = f"https://bsky.app/profile/{author}/post/{uri.rsplit('/', 1)[-1]}"
            items[url] = {
                "id": _id(url), "kind": "social", "outlet": "Bluesky", "title": text[:140], "text": text[:600],
                "url": url, "published": (post.get("indexedAt") or datetime.now(timezone.utc).isoformat())
                .replace("Z", "+00:00"),
            }
        time.sleep(1)
    return list(items.values())


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
