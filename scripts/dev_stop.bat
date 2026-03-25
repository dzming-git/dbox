@echo off
REM DPlayer 开发模式快速停止脚本
REM 用法：双击运行或在命令行执行 dev_stop.bat

echo ============================================================
echo   DPlayer 开发模式停止
echo ============================================================
echo.

echo [停止服务]

REM 停止 Flask 后端（查找 Python 进程）
echo [1/2] 停止 Flask 后端服务...
tasklist /FI "WINDOWTITLE eq DPlayer Web Backend*" 2>NUL | find /I /N "cmd.exe">NUL
if "%ERRORLEVEL%"=="0" (
    taskkill /FI "WINDOWTITLE eq DPlayer Web Backend*" /F >nul 2>&1
    echo   [OK] Flask 后端已停止
) else (
    echo   [SKIP] Flask 后端未运行
)

REM 停止 Vue 前端（查找 Node 进程）
echo [2/2] 停止 Vue 前端服务...
tasklist /FI "WINDOWTITLE eq DPlayer WebUI Frontend*" 2>NUL | find /I /N "cmd.exe">NUL
if "%ERRORLEVEL%"=="0" (
    taskkill /FI "WINDOWTITLE eq DPlayer WebUI Frontend*" /F >nul 2>&1
    echo   [OK] Vue 前端已停止
) else (
    echo   [SKIP] Vue 前端未运行
)

echo.
echo ============================================================
echo   [OK] 开发环境已停止
echo ============================================================
echo.

pause
