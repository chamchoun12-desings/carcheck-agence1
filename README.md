# AI Car Check

Contrôle vidéo des voitures de location : sortie et retour filmés, dégâts proposés par l’IA, compteur (km + essence), caution, facture, rapport WhatsApp au client, planning de la flotte, entretien, équipe.

**Règle n° 1 : l’IA propose, l’employé décide.**

## Deux applications séparées

| Pour qui | Où | Ce qu’on y fait |
|---|---|---|
| **L’agence** (employés et patron) | Application Android **Car Check**, ou l’adresse du serveur dans un navigateur | Sortie, Retour, Planning, Demandes, Voitures ; le patron voit aussi Équipe et Espace patron |
| **Les clients** | Lien web `https://votre-serveur/reserver` (à mettre sur WhatsApp, Facebook, Google) | Voir les voitures libres (sans prix), envoyer CIN/passeport + permis, suivre sa demande |

Les deux sont en **français et en arabe** (bouton en haut à droite). Un écran = une seule action, avec de gros boutons.

### L’application agence

- **Accueil** : 4 gros boutons (Sortie, Retour, Planning, Demandes) + Voitures. Au-dessus, ce qui demande une action : retards, demandes, voitures à surveiller, **dégâts à vérifier**, **retours à terminer**, contrôles pas encore envoyés.
- **Sortie** (7 étapes) : voiture → client → permis (date + photo) → vidéo guidée → photo du compteur (lue par l’IA : aiguilles, numérique ou écran ; sinon on tape les km et on touche le niveau d’essence) → jours + **prix par jour tapé par l’agence** → **caution tapée** → Valider. Une voiture réservée remplit le client, le permis et le prix accepté.
- Après l’envoi, l’IA regarde la vidéo (environ 1 minute) : l’employé répond **Oui / Non** pour chaque dégât proposé, et peut **ajouter un dégât oublié**.
- **Retour** (3 étapes) : voiture → vidéo → compteur → Valider. Puis nouveaux dégâts (photo avant / après), **l’argent** (caution, essence manquante, dégâts à taper, somme à rendre) → facture, rapport WhatsApp, permis et documents du client effacés.
- **Sans réseau** : la sortie ou le retour est gardé dans le téléphone et part tout seul quand le serveur répond (« À envoyer » sur l’accueil). Les écrans affichent les dernières données connues.
- **Planning** : les 7 prochains jours en couleurs (libre, louée, réservée, demande, en retard), recherche d’une voiture libre, **la flotte** : le patron ajoute, modifie ou retire une voiture (km, type de compteur, catégorie, vidange, assurance, visite technique, vignette). Tout se met à jour avec les sorties et les retours.
- **Demandes** : réservations des clients (avec leurs papiers) : l’agence **tape le prix par jour** et accepte ; prolongations demandées sur WhatsApp.
- **Voitures** : état de chaque voiture, km, vidange, papiers (orange bientôt, rouge expiré : la voiture ne peut plus sortir), historique (qui a fait quoi). Bouton « Vidange faite ».
- **Équipe** (patron) : chaque employé avec son identifiant, son WhatsApp et ses tâches (Sorties, Retours, Réservations, Entretien, Caisse) ; **journal** de toutes les actions avec la date et l’heure.
- **Espace patron** : chiffre d’affaires du mois, taux de location, entretien à faire, occupation par voiture, liens vers les pages détaillées (bilan, contrôles, factures PDF).

### Premier réglage du téléphone

1. Installez **CarCheck.apk** (voir plus bas).
2. Ouvrez-le : tapez **l’adresse du serveur**, **votre identifiant** et **votre mot de passe**, puis **Ouvrir l’application**. C’est fait une seule fois.
3. Le patron se connecte avec `STAFF_USER` / `STAFF_PASSWORD` du fichier `.env`, puis crée un compte pour chaque employé dans **Équipe**.

Le bouton **Démo sans serveur** du premier écran montre l’application avec des données d’exemple.

## Données personnelles (INPDP)

- Photos du permis et des papiers envoyés en réservant : visibles par l’agence seulement, jamais envoyées à l’IA, jamais sur un lien public, **effacées à la clôture de la location** (ou si la demande est refusée ou annulée, au plus tard 30 jours après la fin). Aucun numéro de document n’est enregistré.
- Ajoutez une ligne dans vos conditions de location pour informer les clients.

## Contenu du dépôt

| Dossier | Contenu |
|---|---|
| `server/` | Le serveur (Python, FastAPI). L’application agence est la page `server/carcheck/static/agence.html` (servie sur `/`), la page client `static/client.html` (servie sur `/reserver`), l’API dans `carcheck/agence.py`. Voir `server/README.md`. |
| `android/` | L’application Android : une copie de la même page agence (`android/app/src/main/assets/agence.html`) + caméra, envoi et file d’attente hors ligne. |
| `.github/workflows/build-apk.yml` | La fabrication automatique : tests du serveur, APK, publication dans **Releases**. |

## Tester sur une vraie voiture

Voir **TEST-REEL.md** : test de l’analyse (vidéo envoyée à Claude) puis test complet avec un PC Windows (`server/demarrer-windows.bat`) et le téléphone.

## Télécharger l’application

À chaque modification, GitHub fabrique tout seul une nouvelle version (5 à 8 minutes).

1. Sur la page du dépôt, colonne de droite : **Releases** → la version la plus récente.
2. Téléchargez **CarCheck.apk** et envoyez-le sur votre téléphone.
3. Ouvrez-le → autorisez cette source → **Installer**.

Les nouvelles versions s’installent par-dessus l’ancienne. Si une version installée avant le 18/11/2026 bloque l’installation, désinstallez-la une fois.

Le serveur prêt à installer est dans la même Release : **carcheck-serveur.zip**.

## Mettre à jour le code sans perdre les dossiers

L’envoi de dossiers par le site GitHub perd souvent des fichiers. Méthode fiable :

1. Mettez tout le projet dans un fichier nommé exactement **projet.zip**.
2. **Add file → Upload files** → glissez `projet.zip` → **Commit changes**.
3. GitHub déballe le zip, remplace le contenu du dépôt (le dossier `.github` est gardé), puis fabrique l’APK.

## Installer le serveur

Voir `server/README.md` : VPS Ubuntu, `.env`, HTTPS avec Caddy, tâches cron (bilan mensuel, nettoyage, **rappels toutes les 15 minutes**), modèles WhatsApp à faire approuver (`car_return_report` et `rappel_retour`).

Pour tester sur votre PC (Python 3.10 ou plus récent ; sous Windows, double-cliquez sur `server/demarrer-windows.bat`) :

```bash
cd server
pip install -r requirements.txt
cp .env.example .env          # mettez STAFF_PASSWORD et CARCHECK_VAULT=./vault
python3 tests/run_tests.py    # doit afficher "All tests passed."
uvicorn carcheck.app:app --host 0.0.0.0 --port 8000
```

Dans l’application Android, premier écran : adresse `http://IP-du-PC:8000`, identifiant `staff` et le mot de passe choisi.

## Ouvrir avec Android Studio

**File → Open** → choisissez le dossier `android`.

## Limites

- Le floutage des visages n’est pas intégré : ne filmez que la voiture.
- `debug.keystore` est une clé de **test**. Pour le Play Store, il faut une vraie clé de publication, jamais publiée sur GitHub.
- Vérifiez les règles locales sur la vidéo et les données personnelles (en Tunisie : INPDP).
