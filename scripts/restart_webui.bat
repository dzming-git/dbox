@echo off
chcp 65001 >nul
echo ========================================
echo  DPlayer 2.0 WebUI 服务重启脚本
echo ========================================
echo.

REM 停止现有的 node 进程（Vite 开发服务器）
echo [1/4] 停止现有的前端进程...
taskkill /F /IM node.exe 2>nul
taskkill /F /IM npm.exe 2>nul
timeout /t 2 /nobreak >nul
echo      完成
echo.

REM 停止 NSSM 服务（如果正在运行）
echo [2/4] 停止 dplayer-webui 服务...
nssm stop dplayer-webui 2>nul
timeout /t 2 /nobreak >nul
echo      完成
echo.

REM 启动 NSSM 服务
echo [3/4] 启动 dplayer-webui 服务...
nssm start dplayer-webui
timeout /t 3 /nobreak >nul
echo      完成
echo.

REM 检查服务状态
echo [4/4] 检查服务状态...
nssm status dplayer-webui
echo.

REM 检查端口
echo 检查端口 5173...
netstat -ano | findstr :5173
echo.

echo ========================================
echo  WebUI 服务重启完成
echo  访问地址: http://localhost:5173
echo ========================================
