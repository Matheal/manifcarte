"""Analyse des articles par une IA (API Gemini, offre gratuite).

Pour chaque article, l'IA détermine :
  - sa nature : annonce d'une mobilisation à venir, compte rendu, simple rappel d'un fait
    ancien, article de contexte, hors sujet ;
  - son degré de certitude : fait établi, information non vérifiée, rumeur, démenti ;
  - les mobilisations précises dont il parle (ville, date, heure, lieu, annulation) ;
  - les causes, le nombre de participants cité et un résumé neutre.

L'IA ne voit que le titre et le résumé publiés par le média (pas l'article complet).
Chaque article n'est analysé qu'une fois : le résultat est stocké dans item["ai"].
Sans clé (GEMINI_API_KEY absente), ou si le quota gratuit est atteint, le collecteur
continue avec les règles classiques de extract.py.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from . import config
from .extract import CAUSES, WEEKDAYS

log = logging.getLogger(__name__)
TZ = ZoneInfo(config.TIMEZONE)
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# À changer si on modifie la consigne : les articles déjà analysés seront ré-analysés.
PROMPT_VERSION = 2

NATURES = ["annonce", "en_cours", "compte_rendu", "rappel_ancien", "contexte", "hors_sujet"]
VERACITES = ["etabli", "non_verifie", "rumeur", "dementi"]
PERTURBATION_TYPES = ["transport", "circulation", "etablissement", "arrete", "commerce", "autre"]

INSTRUCTIONS = f"""Tu es un assistant de veille qui recense les mobilisations (manifestations, blocus,
rassemblements, grèves avec cortège, marches) pour une carte publique. Tu reçois des articles
(titre + résumé, date de parution). Pour CHAQUE article, renvoie un objet JSON :

- "i" : le numéro de l'article.
- "nature" :
    "annonce"        = une mobilisation FUTURE est annoncée ou appelée (« appellent à manifester jeudi »).
    "en_cours"       = une mobilisation se déroule au moment de la parution (« blocus en cours »).
    "compte_rendu"   = récit d'une mobilisation qui a eu lieu récemment (« 2 000 manifestants mardi »).
    "rappel_ancien"  = l'article évoque seulement une mobilisation passée depuis plus de 7 jours.
    "contexte"       = l'article parle du mouvement sans décrire une mobilisation précise
                       (réactions, analyse, arrêté préfectoral, conséquences pour les commerçants…).
    "hors_sujet"     = pas une mobilisation sociale (défilé de mode, manifestation sportive…).
- "veracite" :
    "etabli"         = fait rapporté par le média comme certain.
    "non_verifie"    = conditionnel, « selon des messages sur les réseaux », appel non confirmé.
    "rumeur"         = l'article traite d'une rumeur ou d'une vidéo douteuse non confirmée.
    "dementi"        = l'article dément ou vérifie comme fausse une information.
- "evenements" : liste des mobilisations PRÉCISES décrites (vide si nature = contexte/hors_sujet).
  Pour chacune : "ville" (nom officiel de la commune, ex. « Nancy », « Vandœuvre-lès-Nancy »),
  "pays" (ex. « France »), "date" au format AAAA-MM-JJ (déduis-la de la date de parution :
  « ce jeudi », « demain », « hier »… ; null si impossible), "heure" HH:MM ou null,
  "lieu" (lieu précis : « place Stanislas », « lycée Henri-Loritz » ; null sinon),
  "annule" (true si annulée, reportée ou interdite et donc n'ayant pas lieu).
- "causes" : parmi {", ".join(CAUSES)}.
- "participants" : nombre de participants cité (le plus élevé), ou null.
- "resume" : une phrase neutre et factuelle en français (140 caractères max), sans nom de personne.
- "perturbations" : restrictions ou perturbations CONCRÈTES liées aux mobilisations et décrites
  dans l'article (liste vide sinon). Pour chacune :
  "type" : "transport" (bus/tram/train déviés, arrêts non desservis, gare fermée),
           "circulation" (rues ou routes fermées, stationnement interdit),
           "etablissement" (lycée, fac, école fermés ou perturbés),
           "arrete" (arrêté préfectoral ou municipal : interdiction de manifester, d'artifices, périmètre),
           "commerce" (commerces, services publics fermés), "autre" ;
  "ville", "lieu" (précis ou null), "lignes" (lignes de transport citées, ex. ["T1", "Corol"], sinon []),
  "debut" et "fin" au format AAAA-MM-JJ (null si inconnu),
  "description" : courte phrase factuelle (110 caractères max).

Règles : ne devine pas, n'invente aucun lieu ni aucune date. Ne cite jamais de nom de personne
privée ni de mineur. Réponds uniquement avec le tableau JSON."""

_S = {"type": "STRING"}
_NS = {"type": "STRING", "nullable": True}
SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "i": {"type": "INTEGER"},
            "nature": {"type": "STRING", "enum": NATURES},
            "veracite": {"type": "STRING", "enum": VERACITES},
            "evenements": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "ville": _S, "pays": _S, "date": _NS, "heure": _NS, "lieu": _NS,
                        "annule": {"type": "BOOLEAN"},
                    },
                    "required": ["ville", "annule"],
                },
            },
            "causes": {"type": "ARRAY", "items": {"type": "STRING", "enum": list(CAUSES)}},
            "participants": {"type": "INTEGER", "nullable": True},
            "resume": _S,
            "perturbations": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "type": {"type": "STRING", "enum": PERTURBATION_TYPES},
                        "ville": _S, "lieu": _NS,
                        "lignes": {"type": "ARRAY", "items": _S},
                        "debut": _NS, "fin": _NS, "description": _S,
                    },
                    "required": ["type", "ville", "description"],
                },
            },
        },
        "required": ["i", "nature", "veracite", "evenements", "causes", "resume"],
    },
}


class QuotaReached(Exception):
    pass


def _describe(i: int, it: dict) -> str:
    pub = datetime.fromisoformat(it["published"]).astimezone(TZ)
    day = WEEKDAYS[pub.weekday()]
    text = it.get("text", "")[:500]
    return (f"[{i}] Parution : {day} {pub:%Y-%m-%d %H:%M} — {it['outlet']}\n"
            f"Titre : {it['title']}\n" + (f"Résumé : {text}\n" if text else ""))


def _clean(res: dict) -> dict:
    """Valide la réponse de l'IA (formats de date, valeurs autorisées)."""
    events = []
    for ev in res.get("evenements") or []:
        ville = (ev.get("ville") or "").strip()
        if not ville:
            continue
        date = ev.get("date")
        heure = ev.get("heure")
        events.append({
            "ville": ville[:80],
            "pays": (ev.get("pays") or "France").strip()[:60],
            "date": _iso_date(date),
            "heure": heure if isinstance(heure, str) and re.fullmatch(r"[0-2]\d:[0-5]\d", heure) else None,
            "lieu": (ev.get("lieu") or None) and str(ev["lieu"]).strip()[:80],
            "annule": bool(ev.get("annule")),
        })
    perturbations = []
    for pt in res.get("perturbations") or []:
        ville = (pt.get("ville") or "").strip()
        desc = (pt.get("description") or "").strip()
        if not ville or not desc:
            continue
        perturbations.append({
            "type": pt.get("type") if pt.get("type") in PERTURBATION_TYPES else "autre",
            "ville": ville[:80],
            "lieu": (pt.get("lieu") or None) and str(pt["lieu"]).strip()[:80],
            "lignes": [str(x).strip()[:20] for x in (pt.get("lignes") or []) if str(x).strip()][:8],
            "debut": _iso_date(pt.get("debut")),
            "fin": _iso_date(pt.get("fin")),
            "description": desc[:140],
        })
    participants = res.get("participants")
    return {
        "nature": res.get("nature") if res.get("nature") in NATURES else "contexte",
        "veracite": res.get("veracite") if res.get("veracite") in VERACITES else "non_verifie",
        "evenements": events[:6],
        "causes": [c for c in (res.get("causes") or []) if c in CAUSES][:3],
        "participants": participants if isinstance(participants, int) and 0 < participants < 5_000_000 else None,
        "resume": str(res.get("resume") or "")[:160],
        "perturbations": perturbations[:5],
    }


def _iso_date(value) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"20\d\d-\d\d-\d\d", value) else None


class Analyzer:
    def __init__(self, state: dict, session: requests.Session | None = None) -> None:
        self.key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.models = [m for m in [os.environ.get("GEMINI_MODEL"), *config.AI_MODELS] if m]
        self.state = state.setdefault("ai", {})
        self.session = session or requests.Session()
        self.calls = 0
        self._last = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.key) and config.AI_ENABLED

    def _budget_left(self) -> int:
        today = datetime.now(TZ).date().isoformat()
        if self.state.get("day") != today:
            self.state["day"], self.state["calls_today"] = today, 0
        return min(config.AI_MAX_CALLS_PER_RUN - self.calls,
                   config.AI_MAX_CALLS_PER_DAY - self.state["calls_today"])

    def _call(self, prompt: str) -> list:
        wait = config.AI_MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        body = {
            "systemInstruction": {"parts": [{"text": INSTRUCTIONS}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json",
                                 "responseSchema": SCHEMA},
        }
        last_error = None
        for model in list(self.models):
            for attempt in range(2):
                self._last = time.monotonic()
                r = self.session.post(API.format(model=model), json=body, timeout=90,
                                      headers={"x-goog-api-key": self.key})
                if r.status_code == 404:  # modèle retiré : on essaie le suivant
                    log.warning("Modèle %s indisponible, essai du suivant", model)
                    self.models.remove(model)
                    break
                if r.status_code == 400 and "responseSchema" in body["generationConfig"]:
                    # Schéma refusé par ce modèle : on garde seulement le mode JSON.
                    body["generationConfig"].pop("responseSchema")
                    continue
                if r.status_code == 429:
                    raise QuotaReached(r.text[:200])
                if r.status_code >= 500 and attempt == 0:
                    time.sleep(5)
                    continue
                r.raise_for_status()
                data = r.json()
                self.calls += 1
                self.state["calls_today"] = self.state.get("calls_today", 0) + 1
                self.state["model"] = model
                parts = data["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                return json.loads(text)
            last_error = f"{model} indisponible"
        raise RuntimeError(last_error or "aucun modèle disponible")

    def analyze(self, items: list[dict]) -> dict:
        """Analyse les items qui ne l'ont pas encore été. Renvoie un bilan pour l'état des sources."""
        if not self.enabled:
            return {"ok": True, "disabled": True}
        todo = [it for it in items
                if it["kind"] != "gdelt" and (it.get("ai") or {}).get("v") != PROMPT_VERSION]
        # Les plus récents d'abord : ce sont eux qui comptent pour les manifs à venir.
        todo.sort(key=lambda it: it["published"], reverse=True)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=config.AI_MAX_AGE_DAYS)).isoformat()
        todo = [it for it in todo if it["published"] >= cutoff]
        done = 0
        size = config.AI_BATCH_SIZE
        try:
            for start in range(0, len(todo), size):
                if self._budget_left() <= 0:
                    break
                batch = todo[start:start + size]
                prompt = "\n".join(_describe(i, it) for i, it in enumerate(batch))
                results = self._call(prompt)
                by_index = {r.get("i"): r for r in results if isinstance(r, dict)}
                for i, it in enumerate(batch):
                    if i in by_index:
                        it["ai"] = {**_clean(by_index[i]), "v": PROMPT_VERSION,
                                    "model": self.state.get("model")}
                        done += 1
        except QuotaReached as e:
            log.warning("Quota Gemini atteint : %s", e)
            return {"ok": True, "analyzed": done, "pending": len(todo) - done, "quota": True}
        return {"ok": True, "analyzed": done, "pending": len(todo) - done}
