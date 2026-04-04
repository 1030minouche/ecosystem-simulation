@echo off
title EcoSim — Simulateur d'ecosysteme
echo ============================================================
echo   EcoSim — Lancement de la simulation
echo ============================================================
echo.

cd /d "%~dp0ecosim_code\simulation"

echo Installation des dependances (si necessaire)...
pip install -r requirements.txt
echo.

echo ============================================================
echo   ETAPE 1 : L'editeur de terrain va s'ouvrir.
echo             Configurez votre terrain puis cliquez Confirmer.
echo.
echo   ETAPE 2 : Le viewer 2D s'ouvre automatiquement.
echo             Cliquez Play pour demarrer la simulation.
echo.
echo   (Fermez cette fenetre pour arreter la simulation)
echo ============================================================
echo.

python main.py

pause
