@echo off
REM Car Check : démarre le serveur sur ce PC Windows pour un test avec le téléphone (même Wi-Fi).
cd /d %~dp0
set CARCHECK_VAULT=%~dp0vault
set CARCHECK_DB=%~dp0vault\carcheck.db

where python >nul 2>nul || (echo Python introuvable : installez Python 3.12 depuis python.org en cochant "Add python.exe to PATH". & pause & exit /b)
where ffmpeg >nul 2>nul || (echo ffmpeg introuvable : tapez  winget install --id Gyan.FFmpeg -e  puis relancez ce fichier. & pause & exit /b)

if not exist .env (
  copy .env.example .env >nul
  echo Premier lancement : choisissez le mot de passe employe (STAFF_PASSWORD) puis enregistrez et fermez le Bloc-notes.
  notepad .env
)

python -m pip install -q -r requirements.txt

echo.
echo ================================================================
echo  Dans l'application Car Check, "Ouvrir mon serveur", tapez :
echo     http://ADRESSE-IPv4:8000
echo  Adresse(s) IPv4 de ce PC :
ipconfig | findstr /c:"IPv4"
echo  Si Windows demande l'acces reseau : autorisez "Reseaux prives".
echo  Pour arreter le serveur : fermez cette fenetre.
echo ================================================================
echo.
python -m uvicorn carcheck.app:app --host 0.0.0.0 --port 8000
pause
