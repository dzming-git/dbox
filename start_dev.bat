@echo off
set DPLAYER_DEV_MODE=1
cd /d "%~dp0"
venv\Scripts\python.exe src\web\main.py