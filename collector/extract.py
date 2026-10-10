"""Extraction d'informations à partir de textes de presse en français.

Tout est fait par règles (expressions régulières + dictionnaires) : c'est
gratuit, rapide, déterministe et ça tourne partout sans modèle à télécharger.
"""
from __future__ import annotations

import html
import json
import pathlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent

# --- Normalisation -------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def clean_text(raw: str) -> str:
    """Retire le HTML, décode les entités, uniformise apostrophes et espaces."""
    text = _TAG_RE.sub(" ", raw or "")
    text = html.unescape(text)
    text = text.replace("’", "'").replace(" ", " ").replace(" ", " ")
    return _SPACE_RE.sub(" ", text).strip()


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def slugify(s: str) -> str:
    s = strip_accents(s).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


# --- Pertinence ----------------------------------------------------------------

_PROTEST_RE = re.compile(
    r"\b(manifs?|manifestations?|manifestant(?:e|s|es)?|manifester|rassemblements?|"
    r"mobilisations?|mobilisés?|blocus|bloqués?|grèves?|grévistes?|cortèges?|"
    r"défilés?|défiler|sit-in|piquets? de grève|intersyndicale|marches? (?:blanche|pour|contre|des|du)|"
    r"die-in|occupation)\b",
    re.IGNORECASE,
)
_NOT_PROTEST_RE = re.compile(
    r"manifestations? (?:culturelles?|sportives?|festives?|commerciales?|nautiques?|"
    r"équestres?|d'intérêt|aériennes?|scientifiques?)|défilés? de mode|"
    r"manifestations? (?:cliniques?|cutanées?|allergiques?)|grève de la faim",
    re.IGNORECASE,
)


def is_relevant(text: str) -> bool:
    """Vrai si le texte parle d'une mobilisation (et pas d'un « défilé de mode »…)."""
    return bool(_PROTEST_RE.search(_NOT_PROTEST_RE.sub(" ", text)))


# --- Communes ------------------------------------------------------------------

@dataclass(frozen=True)
class Commune:
    name: str
    insee: str
    dep: str
    lon: float
    lat: float
    population: int


# Gentilés courants -> commune (titres du type « les lycéens nancéiens »).
DEMONYMS = {
    "nancéien": "Nancy", "messin": "Metz", "spinalien": "Épinal", "lunévillois": "Lunéville",
    "parisien": "Paris", "lyonnais": "Lyon", "marseillais": "Marseille", "lillois": "Lille",
    "toulousain": "Toulouse", "bordelais": "Bordeaux", "nantais": "Nantes",
    "strasbourgeois": "Strasbourg", "rennais": "Rennes", "grenoblois": "Grenoble",
    "montpelliérain": "Montpellier", "niçois": "Nice", "rouennais": "Rouen",
    "dijonnais": "Dijon", "rémois": "Reims", "brestois": "Brest", "havrais": "Le Havre",
    "stéphanois": "Saint-Étienne", "clermontois": "Clermont-Ferrand", "angevin": "Angers",
    "tourangeau": "Tours", "caennais": "Caen", "orléanais": "Orléans", "toulonnais": "Toulon",
    "thionvillois": "Thionville", "bisontin": "Besançon", "mulhousien": "Mulhouse",
    "limougeaud": "Limoges", "amiénois": "Amiens", "palois": "Pau", "poitevin": "Poitiers",
}
# Mots qui suivent un nom de ville sans désigner un lieu de manifestation.
_FALSE_CITY_FOLLOWERS = re.compile(
    r"^\s*(?:Saint-Germain|SG\b|FC\b|Basket|Handball|Rugby|Volley|Olympique)", re.IGNORECASE
)


class Gazetteer:
    def __init__(self, path: pathlib.Path | None = None) -> None:
        path = path or ROOT / "data" / "communes.json"
        rows = json.loads(path.read_text(encoding="utf-8"))
        self.by_name = {r[0]: Commune(*r) for r in rows}
        self.by_insee = {c.insee: c for c in self.by_name.values()}
        names = sorted(self.by_name, key=len, reverse=True)
        alt = "|".join(re.escape(n) for n in names)
        # Majuscule obligatoire (pas d'IGNORECASE) pour éviter « tours », « metz »…
        self._re = re.compile(rf"(?<![\w-])({alt})(?![\w-])")
        dem = "|".join(sorted(DEMONYMS, key=len, reverse=True))
        self._dem_re = re.compile(rf"\b({dem})(?:ne|e)?s?\b", re.IGNORECASE)

    def find(self, text: str, limit: int = 6) -> list[Commune]:
        found: list[Commune] = []
        for m in self._re.finditer(text):
            if _FALSE_CITY_FOLLOWERS.match(text[m.end():]):
                continue
            c = self.by_name[m.group(1)]
            if c not in found:
                found.append(c)
        for m in self._dem_re.finditer(text):
            c = self.by_name.get(DEMONYMS[m.group(1).lower()])
            if c and c not in found:
                found.append(c)
        return found[:limit]


# --- Dates ---------------------------------------------------------------------

WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]
_MONTH_ALIASES = {strip_accents(m): i + 1 for i, m in enumerate(MONTHS)}

_EXPLICIT_RE = re.compile(
    rf"\b(?:(?:{'|'.join(WEEKDAYS)})\s+)?(1er|[0-3]?\d)\s+({'|'.join(MONTHS + ['fevrier', 'aout', 'decembre'])})"
    r"(?:\s+(20\d\d))?\b",
    re.IGNORECASE,
)
_NUMERIC_RE = re.compile(
    rf"\b(?:le|(?:{'|'.join(WEEKDAYS)}))\s+([0-3]?\d)/([01]?\d)(?:/(20\d\d|\d\d))?\b", re.IGNORECASE
)
_WEEKDAY_RE = re.compile(
    rf"\b(ce|cette|le|dès|depuis|jusqu'à)?\s*({'|'.join(WEEKDAYS)})\b"
    r"(\s+(?:prochain|dernier))?(?!\s+(?:1er|[0-3]?\d)\b)",
    re.IGNORECASE,
)
_RELATIVE = [
    (re.compile(r"\baprès-demain\b", re.I), 2),
    (re.compile(r"\bavant-hier\b", re.I), -2),
    (re.compile(r"\bdemain\b", re.I), 1),
    (re.compile(r"\bhier\b", re.I), -1),
    (re.compile(r"\b(?:aujourd'hui|ce matin|cet après-midi|ce soir|en ce moment|actuellement|en cours)\b", re.I), 0),
]


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _year_for(ref: date, month: int, day: int) -> date | None:
    """Une date sans année est rattachée à l'occurrence la plus proche de ref."""
    candidates = [_safe_date(ref.year + k, month, day) for k in (-1, 0, 1)]
    candidates = [c for c in candidates if c]
    return min(candidates, key=lambda c: abs((c - ref).days)) if candidates else None


def find_dates(text: str, ref: date) -> list[tuple[date, str]]:
    """Renvoie [(date, précision)] trouvées dans le texte, relatives à `ref`.

    précision : "explicite" (15 octobre), "relative" (jeudi, demain).
    """
    out: list[tuple[date, str]] = []

    def add(d: date | None, precision: str) -> None:
        if d and all(d != x for x, _ in out) and abs((d - ref).days) <= 60:
            out.append((d, precision))

    for m in _EXPLICIT_RE.finditer(text):
        day = 1 if m.group(1).lower() == "1er" else int(m.group(1))
        month = _MONTH_ALIASES[strip_accents(m.group(2).lower())]
        if m.group(3):
            add(_safe_date(int(m.group(3)), month, day), "explicite")
        else:
            add(_year_for(ref, month, day), "explicite")

    for m in _NUMERIC_RE.finditer(text):
        day, month = int(m.group(1)), int(m.group(2))
        if m.group(3):
            year = int(m.group(3))
            add(_safe_date(year + 2000 if year < 100 else year, month, day), "explicite")
        else:
            add(_year_for(ref, month, day), "explicite")

    for rx, delta in _RELATIVE:
        if rx.search(text):
            add(ref + timedelta(days=delta), "relative")
            if delta in (2, -2):  # « après-demain » contient « demain »
                text = rx.sub(" ", text)

    for m in _WEEKDAY_RE.finditer(text):
        target = WEEKDAYS.index(m.group(2).lower())
        diff = (target - ref.weekday()) % 7          # 0..6 jours dans le futur
        suffix = (m.group(3) or "").strip().lower()
        prefix = (m.group(1) or "").lower()
        if suffix == "prochain" or "prochain" in prefix:
            delta = diff or 7
        elif suffix == "dernier" or prefix == "depuis":
            delta = diff - 7 if diff else -7
        else:
            # « ce jeudi » / « jeudi » : jour le plus proche, l'avenir l'emporte à égalité.
            delta = diff if diff <= 3 else diff - 7
        add(ref + timedelta(days=delta), "relative")

    return out


_TIME_RE = re.compile(r"\b(?:à|dès|vers|de|rendez-vous|rdv)\s+([01]?\d|2[0-3])\s?(?:h|heures?)\s?([0-5]\d)?\b", re.I)


def find_time(text: str) -> str | None:
    m = _TIME_RE.search(text)
    if not m:
        return None
    hour = int(m.group(1))
    if hour < 6:
        return None
    return f"{hour:02d}:{m.group(2) or '00'}"


# --- Lieux précis ----------------------------------------------------------------

_NAME = r"[A-ZÉÈÊÀÂÎÔÛÇ][\w'éèêëàâäîïôöûüç]+"
_PLACE_RE = re.compile(
    r"\b((?:place|parc|cours|avenue|boulevard|quai|esplanade|pont|porte|square)\s+"
    rf"(?:de la |du |des |de l'|d'|de |)(?:{_NAME})(?:[\s-](?:de |du |la |)?{_NAME}){{0,3}}"
    r"|(?:lycée|collège|université|faculté|campus|IUT|école)\s+"
    rf"(?:professionnel(?:le)?\s+|polyvalent\s+|agricole\s+|de la |du |des |de l'|d'|)?(?:{_NAME})(?:[\s-]{_NAME}){{0,3}}"
    r"|(?:devant|à|vers|depuis) (?:la |le |l')(gare|préfecture|rectorat|mairie|hôtel de ville|"
    r"inspection académique|conseil départemental|conseil régional|assemblée nationale))",
)
_GENERIC_PLACES = {"gare", "préfecture", "rectorat", "mairie", "hôtel de ville",
                   "inspection académique", "conseil départemental", "conseil régional",
                   "assemblée nationale"}


def find_places(text: str) -> list[str]:
    places: list[str] = []
    for m in _PLACE_RE.finditer(text):
        p = m.group(2) or m.group(1)
        p = p.strip(" -'")
        if p.lower() in _GENERIC_PLACES:
            p = p.capitalize() if p != "rectorat" else "Rectorat"
        if p not in places:
            places.append(p)
    return places


# --- Causes, signaux, participants -------------------------------------------

CAUSES = {
    "education": ("Éducation & lycéens", r"lycé|étudiant|blocus|\bbac\b|parcoursup|enseignant|\bprofs?\b|"
                  r"école|universit|\bfac\b|éducation|collège|rectorat|\bunl\b|\bfidl\b|jeunesse"),
    "retraites": ("Retraites", r"retraite"),
    "travail": ("Travail & syndicats", r"grève|syndica|\bcgt\b|\bcfdt\b|\bfo\b|\bsud\b|salari|salaire|"
                r"licenci|emploi|cheminot|\bsncf\b|intersyndicale|chômage"),
    "climat": ("Climat & environnement", r"climat|écolo|extinction rebellion|bassine|pesticide|\ba69\b|"
               r"environnement|nucléaire|biodiversité"),
    "international": ("International & paix", r"palestin|gaza|israël|ukrain|guerre|\bpaix\b|iran|kurde|"
                      r"soudan|congo|liban|arménie"),
    "droits": ("Droits & égalité", r"féminis|féminicide|droits des femmes|\bivg\b|lgbt|fiertés|"
               r"racisme|antiracis|discrimination|sans-papiers|migrant|immigration|handicap"),
    "police": ("Police & justice", r"violences policières|justice pour|bavure|police"),
    "agriculture": ("Agriculture", r"agricult|paysan|fnsea|éleveur|coordination rurale"),
    "sante": ("Santé & hôpital", r"hôpital|soignant|santé|infirmi|urgences|ehpad"),
    "services": ("Services publics & pouvoir d'achat", r"service public|pouvoir d'achat|budget|"
                 r"impôt|taxe|logement|loyer|transport|vie chère|inflation"),
    "politique": ("Politique & institutions", r"gouvernement|président|élection|démocratie|"
                  r"49\.3|assemblée|ministre|réforme"),
}
_CAUSE_RES = {k: re.compile(v[1], re.IGNORECASE) for k, v in CAUSES.items()}
CAUSE_LABELS = {k: v[0] for k, v in CAUSES.items()} | {"autre": "Autre"}


def find_causes(text: str) -> list[str]:
    scored = []
    for key, rx in _CAUSE_RES.items():
        n = len(rx.findall(text))
        if n:
            scored.append((n, key))
    scored.sort(key=lambda x: (-x[0], list(CAUSES).index(x[1])))
    causes = [k for _, k in scored]
    # « politique » est très générique : seulement si rien d'autre.
    if len(causes) > 1 and "politique" in causes:
        causes.remove("politique")
    return causes[:3] or ["autre"]


_SIGNALS = {
    "annulee": re.compile(r"\b(?:annulée?s?|reportée?s?)\b", re.I),
    "interdite": re.compile(r"\binterdite?s?\b|arrêté préfectoral", re.I),
    "tensions": re.compile(r"tensions?|incidents?|heurts?|affrontements?|interpell|gaz lacrymogène|"
                           r"échauffourée|dégradation|incendi|violences?", re.I),
    "blocus": re.compile(r"\bblocus\b|\bbloqués?\b", re.I),
    "annonce": re.compile(r"\bappel(?:lent|le)? à\b|\bprévue?s?\b|\bdonnent rendez-vous\b|\brendez-vous\b|"
                          r"\brdv\b|\baura lieu\b|\bva (?:se )?(?:manifester|rassembler|défiler)\b|"
                          r"\bnouvelle journée\b|\bce qui est prévu\b|\bappel\b", re.I),
}


def find_signals(text: str) -> list[str]:
    return [k for k, rx in _SIGNALS.items() if rx.search(text)]


_NUM_RE = re.compile(
    r"\b(\d{1,3}(?:[ .]\d{3})+|\d{2,6})\s+(?:manifestants?|personnes|lycéens|participants|"
    r"étudiants|grévistes|jeunes|élèves)\b",
    re.I,
)
_WORD_NUM = {"centaine": 100, "centaines": 200, "millier": 1000, "milliers": 2000, "dizaine de milliers": 10000,
             "dizaines de milliers": 20000}
_WORD_NUM_RE = re.compile(
    r"\b(?:une |des |plusieurs )?(dizaines? de milliers|milliers?|centaines?)\s+(?:de |d')"
    r"(?:manifestants|personnes|lycéens|participants|étudiants|jeunes|élèves)",
    re.I,
)


def find_participants(text: str) -> int | None:
    values = []
    for m in _NUM_RE.finditer(text):
        n = int(re.sub(r"[ .]", "", m.group(1)))
        if 10 <= n <= 2_000_000 and not (1900 <= n <= 2100):
            values.append(n)
    for m in _WORD_NUM_RE.finditer(text):
        values.append(_WORD_NUM[m.group(1).lower()])
    return max(values) if values else None


# --- Point d'entrée ---------------------------------------------------------------

@dataclass
class Extraction:
    communes: list[Commune] = field(default_factory=list)
    dates: list[tuple[date, str]] = field(default_factory=list)
    time: str | None = None
    places: list[str] = field(default_factory=list)
    causes: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    participants: int | None = None


def extract(title: str, body: str, ref: date, gaz: Gazetteer) -> Extraction | None:
    """Analyse un article. Renvoie None s'il ne parle pas d'une mobilisation localisable."""
    full = f"{title}. {body}"
    if not is_relevant(full):
        return None
    # Les villes du titre sont les plus fiables ; on ne complète avec le corps que si besoin.
    communes = gaz.find(title) or gaz.find(body, limit=3)
    if not communes:
        return None
    dates = find_dates(title, ref) or find_dates(body, ref)
    return Extraction(
        communes=communes,
        dates=dates[:3],
        time=find_time(full),
        places=find_places(full)[:3],
        causes=find_causes(full),
        signals=find_signals(full),
        participants=find_participants(full),
    )
