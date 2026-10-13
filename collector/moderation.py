"""Contributions et modération via les « issues » GitHub du dépôt.

Trois formulaires (.github/ISSUE_TEMPLATE/) :
  - « ajout-manif »  : ajouter une mobilisation qu'aucun article ne mentionne ;
  - « restriction »  : signaler une restriction (bus déviés, rue fermée, arrêté…) ;
  - « suppression »  : retirer une fiche ou un article erroné.

Une contribution est appliquée si elle vient du propriétaire du dépôt (ou d'un
collaborateur), ou si le propriétaire lui a mis l'étiquette « approuvé ».
L'étiquette « annulé » la désactive. Rien n'est publié sans cette validation.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

from . import config
from .extract import CAUSE_LABELS, find_dates

log = logging.getLogger(__name__)
TZ = ZoneInfo(config.TIMEZONE)

LABEL_ADD, LABEL_RESTRICTION, LABEL_REMOVE = "ajout-manif", "restriction", "suppression"
LABEL_POST = "publication"
LABEL_APPROVED, LABEL_CANCELLED = "approuvé", "annulé"
# Envoyé depuis le formulaire sans compte du site : jamais approuvé automatiquement,
# même si le ticket est techniquement créé par le compte du propriétaire.
LABEL_ANONYMOUS = "anonyme"
CONTRIBUTION_LABELS = {LABEL_ADD, LABEL_RESTRICTION, LABEL_REMOVE, LABEL_POST}
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}

# Intitulés des champs des formulaires -> clés internes (doivent correspondre aux .yml).
FIELDS = {
    "Ville": "ville",
    "Date": "date",
    "Heure de début": "heure",
    "Lieu précis": "lieu",
    "Type de mobilisation": "type",
    "Cause principale": "cause",
    "Description": "description",
    "Source (lien)": "source",
    "Type de restriction": "rtype",
    "Lignes de transport concernées": "lignes",
    "Date de début": "debut",
    "Date de fin": "fin",
    "Lien de la fiche ou de l'article": "lien",
    "Motif": "motif",
    "Précisions": "details",
    "Lien de la publication": "lien",
    "Plateforme": "plateforme",
    "Texte de la publication": "texte",
}
KINDS = {"Manifestation", "Rassemblement", "Blocus", "Grève", "Marche", "Autre"}
RESTRICTION_TYPES = {
    "Transports (bus, tram, train)": "transport",
    "Circulation / route fermée": "circulation",
    "Établissement fermé ou perturbé": "etablissement",
    "Arrêté / interdiction": "arrete",
    "Commerces / services fermés": "commerce",
    "Autre": "autre",
}
CAUSE_BY_LABEL = {v: k for k, v in CAUSE_LABELS.items()}


@dataclass
class Moderation:
    removed_events: set[str] = field(default_factory=set)
    removed_restrictions: set[str] = field(default_factory=set)
    removed_urls: set[str] = field(default_factory=set)
    manual_events: list[dict] = field(default_factory=list)
    manual_restrictions: list[dict] = field(default_factory=list)
    posts: list[dict] = field(default_factory=list)
    pending: int = 0
    # numéro d'issue -> ("applied" | "pending" | "error", message)
    statuses: dict[int, tuple[str, str]] = field(default_factory=dict)


# --- Lecture des formulaires ------------------------------------------------------------

def parse_form(body: str) -> dict[str, str]:
    """Transforme le corps d'une issue de formulaire (« ### Intitulé » + valeur) en dict."""
    out: dict[str, str] = {}
    for block in re.split(r"^###\s+", body or "", flags=re.M)[1:]:
        heading, _, value = block.partition("\n")
        key = FIELDS.get(heading.strip())
        value = value.strip()
        if key and value and value != "_No response_":
            out[key] = value
    return out


def parse_date(text: str, ref: date) -> date | None:
    """Accepte 2026-10-13, 13/10/2026, 13/10, « 13 octobre », « mardi 13 octobre »."""
    text = text.strip()
    m = re.fullmatch(r"(20\d\d)-(\d{1,2})-(\d{1,2})", text)
    if m:
        return _safe(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?", text)
    if m:
        year = int(m[3]) if m[3] else ref.year
        year = year + 2000 if year < 100 else year
        d = _safe(year, int(m[2]), int(m[1]))
        if d and not m[3] and (d - ref).days < -180:
            d = _safe(year + 1, int(m[2]), int(m[1]))
        return d
    found = [d for d, precision in find_dates(text, ref) if precision == "explicite"]
    return found[0] if found else None


def _safe(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_time(text: str) -> str | None:
    m = re.search(r"\b([01]?\d|2[0-3])\s*(?:h|:|heures?)\s*([0-5]\d)?", text or "")
    return f"{int(m[1]):02d}:{m[2] or '00'}" if m else None


def _url(text: str | None) -> str:
    m = re.search(r"https?://\S+", text or "")
    return m.group(0).rstrip(").,;") if m else ""


def interpret(issue: dict) -> tuple[str, dict | str]:
    """Analyse une issue. Renvoie (type, données) ou ("error", message lisible)."""
    labels = {lab["name"] for lab in issue.get("labels", [])}
    form = parse_form(issue.get("body") or "")
    ref = datetime.fromisoformat(issue["created_at"].replace("Z", "+00:00")).astimezone(TZ).date()

    if LABEL_POST in labels:
        url = _url(form.get("lien"))
        texte = (form.get("texte") or "").strip()
        if not url or not texte:
            return "error", "Le lien et le texte de la publication sont obligatoires."
        extra = ". ".join(f"{k} : {form[k.lower()]}" for k in ("Ville", "Date") if form.get(k.lower()))
        return "add_post", {
            "issue": issue["number"], "url": url, "platform": form.get("plateforme", "Réseau social"),
            "text": (texte + (f". {extra}" if extra else ""))[:900],
            "published": issue["created_at"].replace("Z", "+00:00"),
        }

    if LABEL_REMOVE in labels:
        lien = form.get("lien", "")
        m = re.search(r"/manif/([\w-]+)", lien)
        if m:
            return "remove_event", {"id": m.group(1)}
        m = re.search(r"#(r-[\w-]+)", lien)
        if m:
            return "remove_restriction", {"id": m.group(1)}
        if _url(lien):
            return "remove_url", {"url": _url(lien)}
        return "error", "Le lien est vide ou n'est pas une adresse web (https://…)."

    if LABEL_ADD in labels:
        if not form.get("ville"):
            return "error", "La ville est manquante."
        d = parse_date(form.get("date", ""), ref)
        if not d:
            return "error", "Date illisible. Utilise par exemple 13/10/2026."
        kind = form.get("type", "Manifestation")
        return "add_event", {
            "issue": issue["number"], "ville": form["ville"].strip(), "date": d,
            "heure": parse_time(form.get("heure", "")), "lieu": form.get("lieu"),
            "kind": kind if kind in KINDS and kind != "Autre" else "Mobilisation",
            "cause": CAUSE_BY_LABEL.get(form.get("cause", ""), "autre"),
            "description": (form.get("description") or "").strip()[:300],
            "source": _url(form.get("source")), "created": ref,
        }

    if LABEL_RESTRICTION in labels:
        if not form.get("ville") or not form.get("description"):
            return "error", "La ville et la description sont obligatoires."
        start = parse_date(form.get("debut", ""), ref) or ref
        end = parse_date(form.get("fin", ""), ref) if form.get("fin") else None
        if end and end < start:
            return "error", "La date de fin est avant la date de début."
        return "add_restriction", {
            "issue": issue["number"], "ville": form["ville"].strip(), "lieu": form.get("lieu"),
            "type": RESTRICTION_TYPES.get(form.get("rtype", ""), "autre"),
            "lignes": [x.strip() for x in re.split(r"[,;/]", form.get("lignes", "")) if x.strip()][:10],
            "debut": start, "fin": end or start,
            "description": form["description"].strip()[:300], "source": _url(form.get("source")),
        }
    return "ignore", {}


# --- Récupération et application ----------------------------------------------------------

def fetch_issues(session: requests.Session, repo: str) -> list[dict]:
    issues, page = [], 1
    while True:
        r = session.get(f"https://api.github.com/repos/{repo}/issues",
                        params={"state": "all", "per_page": 100, "page": page}, timeout=30)
        r.raise_for_status()
        batch = r.json()
        issues += [i for i in batch if "pull_request" not in i]
        if len(batch) < 100 or page >= 10:
            return issues
        page += 1


def collect(issues: list[dict]) -> Moderation:
    mod = Moderation()
    for issue in sorted(issues, key=lambda i: i["number"]):
        labels = {lab["name"] for lab in issue.get("labels", [])}
        if not labels & CONTRIBUTION_LABELS:
            continue
        num = issue["number"]
        if LABEL_CANCELLED in labels:
            mod.statuses[num] = ("cancelled", "")
            continue
        trusted_author = issue.get("author_association") in TRUSTED and LABEL_ANONYMOUS not in labels
        approved = trusted_author or LABEL_APPROVED in labels
        if not approved:
            if issue["state"] == "open":
                mod.pending += 1
                mod.statuses[num] = ("pending", "")
            continue
        kind, data = interpret(issue)
        if kind == "error":
            mod.statuses[num] = ("error", data)
            continue
        if kind == "remove_event":
            mod.removed_events.add(data["id"])
        elif kind == "remove_restriction":
            mod.removed_restrictions.add(data["id"])
        elif kind == "remove_url":
            mod.removed_urls.add(data["url"])
        elif kind == "add_event":
            mod.manual_events.append(data)
        elif kind == "add_restriction":
            mod.manual_restrictions.append(data)
        elif kind == "add_post":
            mod.posts.append(data)
        else:
            continue
        mod.statuses[num] = ("applied", kind)
    return mod


def load() -> tuple[Moderation, requests.Session | None]:
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        return Moderation(), None
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                            "User-Agent": config.USER_AGENT})
    return collect(fetch_issues(session, repo)), session


# --- Réponses automatiques sur les issues ---------------------------------------------------

MESSAGES = {
    "pending": "Merci ! Ta proposition est **en attente de validation** par l'équipe. "
               "Elle apparaîtra sur la carte une fois approuvée.",
    "add_event": "✅ Mobilisation ajoutée. Elle sera visible sur la carte d'ici 2 à 3 minutes : {site}",
    "add_restriction": "✅ Restriction ajoutée. Elle sera visible d'ici 2 à 3 minutes : {site}perturbations/",
    "add_post": "✅ Publication prise en compte : l'IA va l'analyser comme un article (visible d'ici 2 à 3 "
                "minutes si elle décrit une mobilisation précise) : {site}",
    "remove_event": "🗑️ Fiche retirée de la carte (visible d'ici 2 à 3 minutes). "
                    "Pour annuler, ajoute l'étiquette « annulé » à ce ticket.",
    "remove_restriction": "🗑️ Restriction retirée de la carte. Pour annuler, ajoute l'étiquette « annulé ».",
    "remove_url": "🗑️ Article écarté : il ne sera plus pris en compte. "
                  "Pour annuler, ajoute l'étiquette « annulé » à ce ticket.",
    "cancelled": "↩️ Contribution annulée : elle n'est plus appliquée.",
    "error": "⚠️ Je n'ai pas pu appliquer cette contribution : {msg} "
             "Modifie le ticket (bouton « … » > Edit) pour corriger, il sera relu automatiquement.",
}


def notify(mod: Moderation, session: requests.Session | None, state: dict) -> None:
    """Commente chaque issue une fois par changement de statut (en production seulement)."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not session or not repo or os.environ.get("MANIFCARTE_NOTIFY") != "1":
        return
    site = os.environ.get("MANIFCARTE_SITE", "")
    done = state.setdefault("notified", {})
    for num, (status, detail) in mod.statuses.items():
        key = status if status != "applied" else detail
        if key == "error":
            key = f"error:{detail}"
        if done.get(str(num)) == key:
            continue
        template = MESSAGES["error" if key.startswith("error") else key]
        body = template.format(site=site, msg=detail)
        try:
            r = session.post(f"https://api.github.com/repos/{repo}/issues/{num}/comments",
                             json={"body": body}, timeout=30)
            r.raise_for_status()
            done[str(num)] = key
        except requests.RequestException as e:
            log.warning("Commentaire impossible sur #%s : %s", num, e)



def post_items(mod: Moderation) -> list[dict]:
    """Publications validées -> items « social » analysés comme des articles."""
    return [{
        "id": f"post-{p['issue']}", "kind": "social", "outlet": f"{p['platform']} (signalée)",
        "title": p["text"][:140], "text": p["text"], "url": p["url"], "published": p["published"],
    } for p in mod.posts]
