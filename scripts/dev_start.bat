@echo off
REM DPlayer 开发模式快速启动脚本
REM 用法：双击运行或在命令行执行 dev_start.bat

echo ============================================================
echo   DPlayer 开发模式启动
echo ============================================================
echo.

REM 设置开发模式环境变量
set DPLAYER_DEV_MODE=1

REM 切换到源码目录
cd /d "%~dp0.."

echo [启动参数]
echo   模式: 开发模式（热加载）
echo   源码目录: %CD%
echo   Python: %~dp0..\venv\Scripts\python.exe
echo.

REM 检查虚拟环境
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] 虚拟环境不存在，请先运行: python -m venv venv
    pause
    exit /b 1
)

REM 检查是否安装 NSSM
where nssm >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [INFO] 检测到 NSSM，可以注册为 Windows 服务
    echo   注册服务: python scripts\install.py --dev
    echo.
)

echo [启动服务]
echo   前端: http://localhost:5173
echo   后端: http://localhost:8080
echo.
echo 按 Ctrl+C 停止服务
echo ============================================================
echo.

REM 启动后端服务（Flask）
echo [1/2] 启动 Flask 后端服务...
start "DPlayer Web Backend" cmd /k "venv\Scripts\python.exe src\web\main.py"

REM 等待后端启动
timeout /t 3 /nobreak >nul

REM 启动前端服务（Vue）
echo [2/2] 启动 Vue 前端服务...
cd src\webui
start "DPlayer WebUI Frontend" cmd /k "npm run dev"

echo.
echo ============================================================
echo   [OK] 开发环境已启动
echo ============================================================
echo.
echo   前端地址: http://localhost:5173
echo   后端地址: http://localhost:8080
echo.
echo   提示: 修改代码会自动重载，无需重启服务
echo ============================================================
echo.

REM 打开浏览器
timeout /t 2 /nobreak >nul
start http://localhost:5173

pause
