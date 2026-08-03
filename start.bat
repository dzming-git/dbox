@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo 启动 Dbox（绿色模式，开发/热重载）...
echo 按 Ctrl+C 停止。日志位于 data\logs\
python scripts\launcher.py
pause
