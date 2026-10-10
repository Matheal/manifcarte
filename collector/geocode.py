"""Géocodage de lieux précis (« lycée Henri-Loritz », « place Stanislas ») avec cache.

Service utilisé : Nominatim (OpenStreetMap), gratuit, limité à 1 requête par seconde.
La recherche est restreinte à un carré autour de la commune pour éviter les homonymes.
"""
from __future__ import annotations

import json
import logging
import pathlib
import time

import requests

from . import config

log = logging.getLogger(__name__)
NOMINATIM = "https://nominatim.openstreetmap.org/search"
BOX = 0.12  # demi-côté du carré de recherche, en degrés (~10 km)


class Geocoder:
    def __init__(self, cache_path: pathlib.Path) -> None:
        self.path = cache_path
        self.cache: dict[str, list | None] = {}
        if cache_path.exists():
            self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
        self.calls = 0
        self._last = 0.0
        self.session = requests.Session()
        self.session.headers["User-Agent"] = config.USER_AGENT

    def locate(self, place: str, city: str, lat: float, lon: float) -> tuple[float, float] | None:
        key = f"{place}|{city}"
        if key in self.cache:
            hit = self.cache[key]
            return (hit[0], hit[1]) if hit else None
        if self.calls >= config.MAX_GEOCODE_PER_RUN:
            return None  # sera géocodé au prochain passage
        wait = 1.1 - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self.calls += 1
        self._last = time.monotonic()
        params = {
            "q": f"{place}, {city}", "format": "jsonv2", "limit": 1, "countrycodes": "fr",
            "viewbox": f"{lon - BOX},{lat + BOX},{lon + BOX},{lat - BOX}", "bounded": 1,
        }
        try:
            r = self.session.get(NOMINATIM, params=params, timeout=config.HTTP_TIMEOUT)
            r.raise_for_status()
            res = r.json()
        except (requests.RequestException, ValueError) as e:
            log.warning("Géocodage impossible pour %s : %s", key, e)
            return None
        hit = [round(float(res[0]["lat"]), 5), round(float(res[0]["lon"]), 5)] if res else None
        self.cache[key] = hit
        return (hit[0], hit[1]) if hit else None

    def save(self) -> None:
        self.path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=0, sort_keys=True),
                             encoding="utf-8")
