@echo off
rem Altes Verhalten (v9): Vorlage in 00_Vorlage, PDFs in 01_Klassenbuch, Ergebnis in 02_Ausgabe.
cd /d "%~dp0"
echo Installiere/pruefe benoetigte Python-Pakete...
py -3.12 -m pip install -r requirements.txt
echo.
echo Starte Berichtsheft-Automation...
py -3.12 cli.py --overwrite %*
echo.
pause
