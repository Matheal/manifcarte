# Formulaire « sans compte » (Google Apps Script, gratuit)

Permet à n'importe qui de signaler une manif, une restriction, une erreur ou une publication
(TikTok, Instagram, X…) **sans compte GitHub**. Chaque envoi devient un ticket GitHub avec
l'étiquette `anonyme`, qui attend ta validation (étiquette `approuvé`).

## 1. Créer un jeton GitHub limité
1. https://github.com/settings/personal-access-tokens/new
2. Nom : `ManifCarte formulaire` · Expiration : 1 an (pense à le renouveler).
3. **Repository access** : *Only select repositories* → `manifcarte`.
4. **Permissions → Repository permissions → Issues : Read and write**. Rien d'autre.
5. **Generate token** et copie-le (il ne sera plus affiché).

## 2. Créer le relais Google
1. https://script.google.com → **Nouveau projet**, nomme-le `ManifCarte formulaire`.
2. Remplace tout le contenu de `Code.gs` par le fichier `Code.gs` de ce dossier, enregistre.
3. ⚙️ **Paramètres du projet** → **Propriétés du script** → **Ajouter** :
   nom `GITHUB_TOKEN`, valeur = le jeton de l'étape 1.
4. **Déployer → Nouveau déploiement** → type **Application Web** :
   *Exécuter en tant que* : **Moi** · *Qui a accès* : **Tout le monde**. Autorise l'accès demandé.
5. Copie l'**URL de l'application Web** (elle se termine par `/exec`).

## 3. Brancher le site
Dans le dépôt GitHub : **Settings → Secrets and variables → Actions → Variables** →
**New repository variable** : nom `REPORT_ENDPOINT`, valeur = l'URL `/exec`.

À la prochaine mise à jour, la page « Signaler » du site affiche le formulaire sans compte, et tous les
boutons « Signaler une erreur » / « Compléter » y mènent.
