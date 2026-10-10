# ManifCarte

Carte interactive des manifestations, blocus et rassemblements : **Nancy** d'abord, puis la France et le monde.
Les données sont collectées **automatiquement** toutes les 20 minutes. Le site est **100 % gratuit** à héberger
(GitHub Actions + GitHub Pages), sans serveur, sans base de données, sans cookie.

## Comment ça marche

```
          toutes les 20 min (GitHub Actions)
┌──────────────────────────────────────────────────────────┐
│ 1. collector/ (Python)                                   │
│    Google News · RSS presse · Mastodon · GDELT           │
│        ↓ tri + extraction (ville, date, lieu, cause)     │
│        ↓ regroupement « 1 ville + 1 jour = 1 manif »     │
│    → events.json            (historique : branche data)  │
│ 2. site/ (Astro + MapLibre)                              │
│    → carte, liste, fiches, stats (pages statiques)       │
│ 3. Publication sur GitHub Pages                          │
└──────────────────────────────────────────────────────────┘
```

| Dossier | Contenu |
|---|---|
| `collector/config.py` | **Le seul fichier à modifier** : ville mise en avant, recherches, flux RSS… |
| `collector/extract.py` | Détection des villes, dates, lieux, causes dans les textes (règles, sans IA) |
| `collector/sources.py` | Connecteurs : Google News, RSS, Mastodon, GDELT |
| `collector/events.py` | Regroupement des articles en manifestations + fiabilité |
| `collector/tests/` | Tests automatiques de l'extraction |
| `data/communes.json` | Les 1 300+ villes françaises reconnues (généré par `build_gazetteer.py`) |
| `site/src/pages/` | Les pages : carte (`index`), `liste`, `manif/[id]`, `stats`, `securite`, `a-propos` |
| `.github/workflows/update.yml` | Le robot : collecte → construction → publication |

## Mettre le site en ligne (une seule fois)

1. Pousse ce dossier dans un dépôt GitHub **public** (les minutes d'Actions sont illimitées pour un dépôt public).
2. Sur GitHub : **Settings → Pages → Build and deployment → Source : GitHub Actions**.
3. Onglet **Actions** → « Mise à jour de la carte » → **Run workflow**.
4. Après 2 à 3 minutes, le site est en ligne sur `https://<ton-pseudo>.github.io/<nom-du-dépôt>/`.

Ensuite, tout est automatique. Les données s'accumulent sur la branche `data` : n'y touche pas.

> ⚠️ GitHub met en pause les tâches planifiées d'un dépôt resté **60 jours sans aucun commit**. Si la carte ne se
> met plus à jour, va dans **Actions** et clique sur **Enable workflow**.

## Analyse par IA (facultative, gratuite)

Une IA (Gemini) lit le titre et le résumé de chaque nouvel article et indique s'il **annonce** une
mobilisation, en fait le **compte rendu**, ne fait que **rappeler** un fait ancien, est un simple article
de **contexte**, ou relaie une **rumeur** / un **démenti**. Elle extrait aussi la date, l'heure et le lieu.

1. Crée une clé gratuite sur [aistudio.google.com](https://aistudio.google.com) (**Get API key**).
   N'active **pas** la facturation : tu restes dans l'offre gratuite, sans aucun frais possible.
2. Dans le dépôt GitHub : **Settings → Secrets and variables → Actions → New repository secret**,
   nom `GEMINI_API_KEY`, valeur = ta clé.

Sans clé, ou si le quota gratuit du jour est atteint, le collecteur continue avec les règles classiques.
Réglages (modèle, nombre d'appels par jour…) dans `collector/config.py`, section « Analyse par IA ».

## Travailler en local (Mac)

```bash
# Collecteur (Python 3.9+)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m collector.main          # collecte réelle → site/public/data/events.json
.venv/bin/python -m pytest -q collector/tests

# Site (Node.js 22+)
cd site
npm install
npm run dev                                 # http://localhost:4321
```

## Changer de ville

Dans `collector/config.py`, modifie `FOCUS_CITY` (nom, code INSEE, coordonnées) et les recherches
`GOOGLE_NEWS_QUERIES` / `RSS_FEEDS`. Pousse : le site se reconstruit tout seul.

## Limites

- L'extraction se fait par **règles** : elle peut se tromper de date ou de lieu. Chaque fiche affiche ses sources.
- Les manifs annoncées uniquement sur Instagram, TikTok ou dans des groupes privés ne sont pas visibles.
- Les points « Monde » (GDELT) sont une détection automatique à grande échelle, moins précise.

## Crédits

Fond de carte © contributeurs OpenStreetMap / OpenFreeMap · MapLibre GL JS · GDELT Project ·
API Découpage administratif (geo.api.gouv.fr) · Nominatim.
