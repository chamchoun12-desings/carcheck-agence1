# Car Check · application Android (agence)

- **Premier écran** (une seule fois) : adresse du serveur, identifiant et mot de passe de l’employé.
- Ensuite l’application s’ouvre sur l’accueil agence : la page `assets/agence.html`, copie de `server/carcheck/static/agence.html` (gardez les deux identiques).
- `AgenceActivity` donne à la page un pont natif `CC` : requêtes au serveur avec l’identifiant (dernières données gardées pour le hors ligne), tournage guidé (`RecorderActivity`, sans son), photos du compteur et du permis gardées dans l’application (jamais dans la galerie), envoi des sorties et retours par la file d’attente (`Uploader`, `QueueActivity`).
- **Démo sans serveur** : `assets/demo.html`, avec des données d’exemple.

## Fabriquer

GitHub le fait tout seul (voir le README principal). Avec Android Studio : **File → Open** → dossier `android` → **Build → Build APK(s)**.

## Remarques

- APK de test (clé `debug.keystore`). Pour Google Play, il faut une vraie clé de publication.
- Android peut afficher un avertissement « Play Protect » pour une application inconnue : *Installer quand même*.
