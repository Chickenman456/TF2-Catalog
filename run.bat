@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py -3 tf2_catalog.py %*) else (python tf2_catalog.py %*)
if errorlevel 1 pause
