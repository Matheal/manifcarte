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

# Recherches Google News par ville (point 1) : chaque recherche a ses propres 100 résultats,
# donc rien n'est coupé les jours de forte mobilisation. Les villes tournent d'un passage à l'autre.
GOOGLE_NEWS_CITY_QUERY = '(manifestation OR blocus OR rassemblement OR grève OR manifestants) "{city}"'
GOOGLE_NEWS_CITY_COUNT = 120     # les 120 communes les plus peuplées (+ la ville mise en avant)
GOOGLE_NEWS_CITIES_PER_RUN = 40  # 3 passages pour faire le tour

# Flux RSS. "presse" = média ; "agenda" = site militant ou agenda (appels à manifester).
RSS_FEEDS = {
    # Lorraine (ville mise en avant)
    "France 3 Nancy": ("https://france3-regions.franceinfo.fr/grand-est/meurthe-et-moselle/nancy/rss", "presse"),
    "France 3 Grand Est": ("https://france3-regions.franceinfo.fr/grand-est/rss", "presse"),
    "L'Est Républicain": ("https://www.estrepublicain.fr/rss", "presse"),
    "Vosges Matin": ("https://www.vosgesmatin.fr/rss", "presse"),
    "Le Républicain Lorrain": ("https://www.republicain-lorrain.fr/rss", "presse"),
    "ici Sud Lorraine": ("https://www.francebleu.fr/rss/sud-lorraine/a-la-une.xml", "presse"),
    "Manif'Est": ("https://manif-est.info/spip.php?page=backend", "agenda"),
    # Presse régionale (point 2)
    "Ouest-France": ("https://www.ouest-france.fr/rss/une", "presse"),
    "Le Télégramme": ("https://www.letelegramme.fr/rss.xml", "presse"),
    "La Dépêche": ("https://www.ladepeche.fr/rss.xml", "presse"),
    "Midi Libre": ("https://www.midilibre.fr/rss.xml", "presse"),
    "Sud Ouest": ("https://www.sudouest.fr/rss.xml", "presse"),
    "Le Progrès": ("https://www.leprogres.fr/rss", "presse"),
    "Le Dauphiné libéré": ("https://www.ledauphine.com/rss", "presse"),
    "Le Bien Public": ("https://www.bienpublic.com/rss", "presse"),
    "Le JSL": ("https://www.lejsl.com/rss", "presse"),
    "DNA": ("https://www.dna.fr/rss", "presse"),
    "L'Alsace": ("https://www.lalsace.fr/rss", "presse"),
    "Le Parisien": ("https://feeds.leparisien.fr/leparisien/rss", "presse"),
    "Nice-Matin": ("https://www.nicematin.com/rss", "presse"),
    **{f"France 3 {name}": (f"https://france3-regions.franceinfo.fr/{slug}/rss", "presse") for name, slug in [
        ("Bretagne", "bretagne"), ("Occitanie", "occitanie"), ("Auvergne-Rhône-Alpes", "auvergne-rhone-alpes"),
        ("Hauts-de-France", "hauts-de-france"), ("Paris Île-de-France", "paris-ile-de-france"),
        ("Nouvelle-Aquitaine", "nouvelle-aquitaine"), ("Normandie", "normandie"),
        ("Pays de la Loire", "pays-de-la-loire"), ("Provence-Alpes-Côte d'Azur", "provence-alpes-cote-d-azur"),
        ("Bourgogne-Franche-Comté", "bourgogne-franche-comte"), ("Centre-Val de Loire", "centre-val-de-loire"),
        ("Corse", "corse")]},
    # Presse nationale
    "Le Monde Société": ("https://www.lemonde.fr/societe/rss_full.xml", "presse"),
    "Le Monde Éducation": ("https://www.lemonde.fr/education/rss_full.xml", "presse"),
    "franceinfo Société": ("https://www.francetvinfo.fr/societe.rss", "presse"),
    "franceinfo Éducation": ("https://www.francetvinfo.fr/societe/education.rss", "presse"),
    "Libération": ("https://www.liberation.fr/arc/outboundfeeds/rss-all/?outputType=xml", "presse"),
    "L'Humanité": ("https://www.humanite.fr/feed", "presse"),
    "Reporterre": ("https://reporterre.net/spip.php?page=backend", "presse"),
    "Rapports de Force": ("https://rapportsdeforce.fr/feed", "presse"),
    # Sites d'information militants locaux (point 3)
    "Paris-luttes.info": ("https://paris-luttes.info/spip.php?page=backend", "agenda"),
    "Rebellyon (Lyon)": ("https://rebellyon.info/spip.php?page=backend", "agenda"),
}

# Agendas Démosphère (événements datés et localisés) — point 3.
DEMOSPHERE_CITIES = ["paris", "toulouse", "lille", "rennes", "strasbourg"]

# Agendas Mobilizon (recherche d'événements publics, fédérés entre instances) — point 3.
MOBILIZON_INSTANCES = ["mobilizon.fr", "keskonfai.fr"]
MOBILIZON_TERMS = ["manifestation", "rassemblement", "blocus", "grève", "marche", "mobilisation"]

# Bluesky (point 4) : nécessite un compte dédié au robot (secrets BSKY_HANDLE et BSKY_APP_PASSWORD).
BLUESKY_QUERIES = ["manif", "manifestation", "blocus", "rassemblement", "lycéens", "grève"]

# Mastodon : hashtags publics lus sans compte, sur des instances francophones.
MASTODON_INSTANCES = ["mastodon.social", "piaille.fr"]
MASTODON_TAGS = ["manif", "manifestation", "greve", "blocus", "mobilisation", "lyceens"]

# GDELT (événements mondiaux géolocalisés, mis à jour toutes les 15 min).
GDELT_ENABLED = True
GDELT_MAX_FILES_PER_RUN = 12        # 12 fichiers = 3 h de rattrapage maximum par passage
GDELT_BACKFILL_FILES = 48           # premier passage : 12 h d'historique
GDELT_MIN_ARTICLES = 3              # nombre minimal d'articles pour retenir un lieu/jour
GDELT_EXCLUDE_COUNTRIES: set[str] = set()
# France (point 6) : GDELT renforce les mobilisations déjà repérées ; seul, il ne crée un point
# que si au moins ce nombre d'articles en parle (filet de sécurité contre le bruit).
GDELT_FR_MIN_ARTICLES_ALONE = 8

# --- Analyse par IA (Gemini, offre gratuite) -------------------------------------
# Activée seulement si le secret GEMINI_API_KEY est défini dans le dépôt GitHub.

AI_ENABLED = True
# Essayés dans l'ordre (si un modèle est retiré par Google, on passe au suivant).
AI_MODELS = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3.1-flash-lite"]
AI_BATCH_SIZE = 10                  # articles envoyés par requête
AI_MAX_CALLS_PER_RUN = 30           # au plus 300 articles analysés par passage (~3 min)
AI_MAX_CALLS_PER_DAY = 400          # ~4 000 articles/jour, garde-fou sous les quotas gratuits
AI_MIN_SECONDS_BETWEEN_CALLS = 6    # ≤ 10 requêtes par minute
AI_MAX_AGE_DAYS = 21                # inutile d'analyser les vieux articles

# --- Conservation ------------------------------------------------------------

KEEP_DAYS_FR = 60       # articles français conservés
KEEP_DAYS_WORLD = 14    # événements mondiaux conservés
MAX_GEOCODE_PER_RUN = 40  # Nominatim : 1 requête/seconde maximum

HTTP_TIMEOUT = 25
