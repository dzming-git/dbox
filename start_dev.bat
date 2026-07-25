@echo off
set DPLAYER_DEV_MODE=1
cd /d "%~dp0"
REM 先启动独立资源下载器（8092），再前台运行主 Web 服务（8080），避免前端代理 /api/scripts 出现 502
start "" venv\Scripts\python.exe src\downloader\main.py
venv\Scripts\python.exe src\web\main.py