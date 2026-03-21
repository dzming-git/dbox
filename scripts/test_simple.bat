@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo 测试开始...

set PORT=5173
set ACTION=add

echo PORT=%PORT%
echo ACTION=%ACTION%

if "%ACTION%"=="add" (
    echo 执行add操作
    goto add_rules
)

goto :eof

:add_rules
echo.
echo 进入add_rules标签
echo 正在为端口 %PORT% 添加防火墙规则...
echo.
pause
