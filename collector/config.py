"""Réglages du collecteur. C'est le seul fichier à modifier pour adapter le projet."""
from __future__ import annotations

import os

# Ville mise en avant sur la carte (vue par défaut, requêtes de presse dédiées).
FOCUS_CITY = {
    "name": "Nancy",
    "insee": "54395",
    "lat": 48.6921,
    "lon": 6.1844,
    "zoom": 12,
}

# Identifiant envoyé aux services gratuits (exigé par la politique d'usage de Nominatim).
# Le workflow GitHub y met automatiquement l'adresse de ton dépôt.
CONTACT = os.environ.get("MANIFCARTE_CONTACT", "https://github.com/manifcarte")
USER_AGENT = f"ManifCarte/1.0 (+{CONTACT})"

TIMEZONE = "Europe/Paris"

# --- Sources -----------------------------------------------------------------

# Recherches Google News (flux RSS publics). "when:7d" limite aux 7 derniers jours.
GOOGLE_NEWS_QUERIES = [
    f"manifestation {FOCUS_CITY['name']}",
    f"rassemblement {FOCUS_CITY['name']}",
    f"lycéens {FOCUS_CITY['name']}",
    f"blocus lycée {FOCUS_CITY['name']}",
    f"grève {FOCUS_CITY['name']}",
    "mobilisation lycéenne",
    "manifestation lycéens",
    "blocus lycée",
    "appel à manifester",
    "manifestation prévue",
    "rassemblement prévu",
    "journée de mobilisation",
    "intersyndicale manifestation",
]

# Flux RSS de presse (régionale autour de la ville + nationale éducation/société).
RSS_FEEDS = {
    "France 3 Nancy": "https://france3-regions.franceinfo.fr/grand-est/meurthe-et-moselle/nancy/rss",
    "France 3 Grand Est": "https://france3-regions.franceinfo.fr/grand-est/rss",
    "L'Est Républicain": "https://www.estrepublicain.fr/rss",
    "Vosges Matin": "https://www.vosgesmatin.fr/rss",
    "Le Républicain Lorrain": "https://www.republicain-lorrain.fr/rss",
    "ici Sud Lorraine": "https://www.francebleu.fr/rss/sud-lorraine/a-la-une.xml",
    "Le Monde Éducation": "https://www.lemonde.fr/education/rss_full.xml",
    "franceinfo Éducation": "https://www.francetvinfo.fr/societe/education.rss",
    "Libération": "https://www.liberation.fr/arc/outboundfeeds/rss-all/?outputType=xml",
}

# Mastodon : hashtags publics lus sans compte, sur des instances francophones.
MASTODON_INSTANCES = ["mastodon.social", "piaille.fr"]
MASTODON_TAGS = ["manif", "manifestation", "greve", "blocus", "mobilisation", "lyceens"]

# GDELT (événements mondiaux géolocalisés, mis à jour toutes les 15 min).
GDELT_ENABLED = True
GDELT_MAX_FILES_PER_RUN = 12        # 12 fichiers = 3 h de rattrapage maximum par passage
GDELT_BACKFILL_FILES = 48           # premier passage : 12 h d'historique
GDELT_MIN_ARTICLES = 3              # nombre minimal d'articles pour retenir un lieu/jour
GDELT_EXCLUDE_COUNTRIES = {"FR"}    # la France est couverte par la presse française

# --- Analyse par IA (Gemini, offre gratuite) -------------------------------------
# Activée seulement si le secret GEMINI_API_KEY est défini dans le dépôt GitHub.

AI_ENABLED = True
# Essayés dans l'ordre (si un modèle est retiré par Google, on passe au suivant).
AI_MODELS = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3.1-flash-lite"]
AI_BATCH_SIZE = 10                  # articles envoyés par requête
AI_MAX_CALLS_PER_RUN = 8            # au plus 80 articles analysés par passage
AI_MAX_CALLS_PER_DAY = 200          # garde-fou, bien en dessous des quotas gratuits
AI_MIN_SECONDS_BETWEEN_CALLS = 6    # ≤ 10 requêtes par minute
AI_MAX_AGE_DAYS = 21                # inutile d'analyser les vieux articles

# --- Conservation ------------------------------------------------------------

KEEP_DAYS_FR = 60       # articles français conservés
KEEP_DAYS_WORLD = 14    # événements mondiaux conservés
MAX_GEOCODE_PER_RUN = 40  # Nominatim : 1 requête/seconde maximum

HTTP_TIMEOUT = 25
