"""Construit data/communes.json à partir de l'API Découpage administratif (geo.api.gouv.fr).

À lancer une seule fois (ou de temps en temps) : le fichier généré est versionné.
    python collector/build_gazetteer.py
"""
from __future__ import annotations

import json
import pathlib

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "communes.json"
MIN_POPULATION = 8000
# Petites préfectures conservées malgré leur population.
ALWAYS_KEEP = {"Privas", "Guéret", "Foix", "Mende", "Digne-les-Bains"}

# Noms de communes qui sont aussi des mots courants ou des noms trop ambigus
# dans un texte de presse : on ne les détecte pas automatiquement.
STOPLIST = {
    "Paris-l'Hôpital", "Grève", "Fontaine", "Montagne", "Mer", "Ville", "Gare",
    "Plaisance", "Bar", "Sauve", "Marché", "Port", "Château", "Saint-Étienne-du-Bois",
    "Lucé", "Fort", "Pont", "Vertou", "Bourg", "Ris", "Cité", "Vire", "Bois",
    "Moissy", "Orange", "Albert", "Sens", "Croix", "Avion", "Cours", "Monts",
    "Brie", "Indre", "Isle", "Anse", "Gorges", "Rives", "Monnaie", "Charmes",
    "Salles", "Contes", "Fleury", "Lorette", "Falaise", "Thiers", "Passy",
    "Plaisir", "Marly", "Lisses", "Villars", "Fosses", "Crest", "Moulins",
    "Saintes", "Revel", "Gray", "Lure", "Dole", "Sedan", "Grenade", "Baden",
    "Vif", "Die", "Eu", "Ham", "Pia", "Drap", "Gan", "Mana", "Sada", "Arues",
    "Charly", "Seclin", "Loos", "Lens-Lestang",
    # Homonymes étrangers fréquents dans l'actualité internationale
    "Valence", "Vienne", "Bruges", "Saint-Louis",
}


def main() -> None:
    r = requests.get(
        "https://geo.api.gouv.fr/communes",
        params={"fields": "nom,code,centre,population,codeDepartement", "format": "json"},
        timeout=120,
    )
    r.raise_for_status()
    best: dict[str, list] = {}
    for c in r.json():
        pop = c.get("population") or 0
        if (pop < MIN_POPULATION and c["nom"] not in ALWAYS_KEEP) or not c.get("centre") or c["nom"] in STOPLIST:
            continue
        lon, lat = c["centre"]["coordinates"]
        row = [c["nom"], c["code"], c["codeDepartement"], round(lon, 5), round(lat, 5), pop]
        # Homonymes : on garde la commune la plus peuplée.
        if c["nom"] not in best or best[c["nom"]][5] < pop:
            best[c["nom"]] = row
    rows = sorted(best.values(), key=lambda x: -x[5])
    OUT.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(rows)} communes -> {OUT}")


if __name__ == "__main__":
    main()
