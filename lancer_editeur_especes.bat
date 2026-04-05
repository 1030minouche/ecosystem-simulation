@echo off
title EcoSim — Editeur d'especes
cd /d "%~dp0ecosim_code\simulation"
python gui\species_editor.py
pause
