@echo off
title EcoSim — Simulateur d'ecosysteme
echo ============================================================
echo   EcoSim — Lancement de la simulation
echo ============================================================
echo.

cd /d "%~dp0"

echo Installation des dependances (si necessaire)...
pip install -e . >NUL 2>&1
echo.

echo ============================================================
echo   Le navigateur va s'ouvrir sur http://localhost:9000
echo   (Fermez cette fenetre pour arreter la simulation)
echo ============================================================
echo.

cd /d "%~dp0ecosim_code\simulation"
python main.py

pause
