# Tester Car Check sur une vraie voiture

Deux tests, à faire dans cet ordre.

| Test | Ce qu’il vérifie | Ce qu’il faut | Coût |
|---|---|---|---|
| **A · Test de l’analyse** | L’IA voit-elle les vrais dégâts et lit-elle le vrai compteur ? | Une vidéo + 2 photos, envoyées à Claude dans la conversation | Gratuit |
| **B · Test complet sur le terrain** | Tout le parcours : téléphone → serveur → validation → retour → calcul | Un PC Windows et le téléphone sur le même Wi-Fi | Gratuit (sans IA) ou quelques centimes par contrôle (avec IA) |

---

## Préparer la voiture (pour les deux tests)

1. Choisissez une voiture avec **2 ou 3 petits dégâts que vous connaissez** (rayure, bosse, jante). Notez-les sur un papier : c’est la « bonne réponse ».
2. Garez-la **en plein jour**, avec de l’espace pour tourner autour. Évitez le soleil de face et la pluie.
3. Préparez un **morceau de ruban adhésif de couleur** (5 à 10 cm) : il servira de « faux dégât » au retour.

## Filmer correctement

Dans l’application : **Sortie** (ou **Retour**), étape « Filmez le tour de la voiture ». La flèche et le minuteur indiquent quoi filmer.


- Téléphone **à l’horizontale**, à environ **1,5 m** de la voiture, à hauteur de poitrine.
- Ordre fixe : **avant → côté droit → arrière → côté gauche**, puis l’intérieur.
- **Lentement** : 60 à 120 secondes en tout. Moins de 45 secondes est refusé.
- Ne filmez **ni les visages ni les autres voitures**.
- **Photo du compteur** : contact mis, photo nette du **kilométrage total** (pas le « trip ») et de la **jauge d’essence**.

---

## Test A · Test de l’analyse (dans la conversation avec Claude)

1. **Sortie** : filmez la voiture, puis prenez la photo du compteur.
2. **Retour simulé** : collez le ruban adhésif sur une porte, roulez un peu si possible, refilmez dans le même ordre et reprenez la photo du compteur.
3. Envoyez à Claude, dans la conversation : `sortie.mp4`, `compteur-sortie.jpg`, `retour.mp4`, `compteur-retour.jpg`.
   - Si une vidéo est trop lourde, filmez en **720p**, ou envoyez-la d’abord à vous-même sur WhatsApp pour la compresser.
4. Claude passe vos fichiers dans le vrai code (empreinte, découpage en photos) et analyse les photos comme le ferait l’IA du serveur.

**Réussi si :** les dégâts connus sont trouvés dans la bonne zone, le ruban adhésif ressort comme **NOUVEAU**, et le kilométrage et la jauge sont bien lus.

---

## Test B · Test complet sur le terrain (PC Windows + téléphone)

### 1. Installer (une seule fois, 10 minutes)
1. **Python** : téléchargez Python 3.12 sur python.org. Pendant l’installation, **cochez « Add python.exe to PATH »**.
2. **ffmpeg** : ouvrez « Invite de commandes » et tapez `winget install --id Gyan.FFmpeg -e`, puis fermez cette fenêtre.
3. **Le serveur** : dans **Releases** sur GitHub, téléchargez **carcheck-serveur.zip** et extrayez-le, par exemple dans `Documents\carcheck`.

### 2. Démarrer
1. Double-cliquez sur **demarrer-windows.bat**.
2. Au premier lancement, le Bloc-notes s’ouvre : remplacez `change-me-long-password` par un mot de passe, puis enregistrez et fermez.
3. Si Windows demande l’accès réseau, autorisez **« Réseaux privés »**.
4. La fenêtre affiche l’**adresse IPv4** du PC (par exemple `192.168.1.10`).

### 3. Sur le téléphone (même Wi-Fi que le PC)
1. Ouvrez **Car Check**. Au premier écran, tapez l’adresse `http://192.168.1.10:8000` (avec votre adresse), l’identifiant `staff` et votre mot de passe, puis **Ouvrir l’application**.
2. (Facultatif) Dans **Équipe**, créez un compte pour un employé et testez avec son identifiant.

### 4. Le parcours
0. **Planning → Ajouter une voiture** (patron) : modèle, plaque, km, type de compteur, dates des papiers.
1. **Sortie** : choisissez la voiture, tapez le nom et votre numéro WhatsApp, la date du permis et sa photo, filmez avec le guide, prenez le compteur, **1 jour**, un prix par jour et une caution, puis **Valider la sortie**.
2. **Dégâts** : quand l’IA a fini (environ 1 minute), répondez Oui / Non pour chaque dégât proposé.
3. Collez le **ruban adhésif** sur une porte.
4. **Retour** : choisissez la voiture, filmez dans le même ordre, prenez le compteur, **Valider le retour**.
5. Vérifiez : le ruban est-il proposé comme **nouveau dégât** avec la photo avant/après ? L’essence manquante et la somme à rendre sont-elles justes ? Tapez un montant de dégâts et terminez : la facture est créée.

**Sans clé IA** (mode `mock`), le serveur ne propose pas de dégâts : ajoutez-les avec **« + Ajouter un dégât oublié »**, et tapez le compteur vous-même. Tout le reste fonctionne : vidéo, empreinte, comparaison, calcul, rapport.

**Avec l’IA** : créez une clé sur console.anthropic.com (paiement à l’usage), collez-la dans `.env` sur la ligne `ANTHROPIC_API_KEY=`, puis relancez **demarrer-windows.bat**.

**WhatsApp** : sans `WA_TOKEN`, l’envoi est « ignoré » proprement. Le rapport reste visible dans **Espace patron → Tous les contrôles**.

---

## Fiche de résultats

| Point | Attendu | Résultat |
|---|---|---|
| Vidéo < 45 s refusée | Refus clair | |
| Heure + empreinte affichées | Oui | |
| Dégâts connus trouvés | 2–3 sur 2–3, bonne zone | |
| Fausses alertes (reflets, saleté) | 0 à 1 | |
| Kilométrage lu | Exact | |
| Jauge lue | ± 1/8 | |
| Ruban adhésif = NOUVEAU | Oui, bonne porte | |
| Photo avant/après | Même endroit de la voiture | |
| Calcul km + carburant | Juste | |
| Retour refusé sans durée de location | Oui | |
| Tournage guidé : 5 étapes, Terminer bloqué avant 45 s | Oui | |
| Plaque lue par l’IA (champ vide) | Exacte | |
| Permis expiré bloqué | Oui | |
| Mode avion : contrôle gardé puis envoyé | Oui, empreinte identique | |
| Compteur de la voiture (aiguilles / numérique / écran) bien lu | Oui | |
| Page client : demande avec papiers, prix tapé par l’agence, client voit le prix | Oui | |

Envoyez cette fiche remplie à Claude : chaque erreur sert à régler l’IA (règles dans `server/carcheck/ai.py`).
