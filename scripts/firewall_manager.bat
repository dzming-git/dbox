@echo off
setlocal enabledelayedexpansion

REM 检查管理员权限
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo 错误: 此脚本需要管理员权限运行!
    echo 请右键点击此脚本，选择"以管理员身份运行"。
    pause
    exit /b 1
)

if "%~1"=="" goto help

set PORT=%~1
set ACTION=add
if not "%~2"=="" set ACTION=%~2

REM 验证端口号
echo %PORT%| findstr /r "^[0-9][0-9]*$" >nul
if %errorLevel% neq 0 (
    echo 错误: 端口号必须是数字
    goto help
)

if %PORT% lss 1 (
    echo 错误: 端口号必须大于 0
    goto help
)

if %PORT% gtr 65535 (
    echo 错误: 端口号必须小于 65536
    goto help
)

REM 执行操作
if "%ACTION%"=="add" goto do_add
if "%ACTION%"=="remove" goto do_remove
if "%ACTION%"=="list" goto do_list
echo 错误: 无效的操作 "%ACTION%"
goto help

:do_add
call :add_rules
pause
exit /b 0

:do_remove
call :remove_rules
pause
exit /b 0

:do_list
call :list_rules
pause
exit /b 0

:add_rules
echo.
echo 正在为端口 %PORT% 添加防火墙规则...
echo.

set INBOUND_RULE=dplayer_%PORT%_inbound
set OUTBOUND_RULE=dplayer_%PORT%_outbound

REM 检查规则是否已存在
netsh advfirewall firewall show rule name="%INBOUND_RULE%" >nul 2>&1
if %errorLevel% equ 0 (
    echo 警告: 端口 %PORT% 的规则已存在!
    echo 将删除旧规则并重新创建...
    call :remove_rules
)

REM 添加入站规则
netsh advfirewall firewall add rule name="%INBOUND_RULE%" dir=in action=allow protocol=TCP localport=%PORT% profile=any >nul
if %errorLevel% equ 0 (
    echo [OK] 入站规则已添加: %INBOUND_RULE%
) else (
    echo [FAIL] 添加入站规则失败
    exit /b 1
)

REM 添加出站规则
netsh advfirewall firewall add rule name="%OUTBOUND_RULE%" dir=out action=allow protocol=TCP localport=%PORT% profile=any >nul
if %errorLevel% equ 0 (
    echo [OK] 出站规则已添加: %OUTBOUND_RULE%
) else (
    echo [FAIL] 添加出站规则失败
    exit /b 1
)

echo.
echo 端口 %PORT% 的防火墙规则配置完成!
exit /b 0

:remove_rules
echo.
echo 正在删除端口 %PORT% 的防火墙规则...
echo.

set INBOUND_RULE=dplayer_%PORT%_inbound
set OUTBOUND_RULE=dplayer_%PORT%_outbound

set REMOVED_COUNT=0

REM 删除入站规则
netsh advfirewall firewall show rule name="%INBOUND_RULE%" >nul 2>&1
if %errorLevel% equ 0 (
    netsh advfirewall firewall delete rule name="%INBOUND_RULE%" >nul
    if %errorLevel% equ 0 (
        echo [OK] 入站规则已删除: %INBOUND_RULE%
        set /a REMOVED_COUNT+=1
    ) else (
        echo [FAIL] 删除入站规则失败
    )
) else (
    echo [-] 入站规则不存在: %INBOUND_RULE%
)

REM 删除出站规则
netsh advfirewall firewall show rule name="%OUTBOUND_RULE%" >nul 2>&1
if %errorLevel% equ 0 (
    netsh advfirewall firewall delete rule name="%OUTBOUND_RULE%" >nul
    if %errorLevel% equ 0 (
        echo [OK] 出站规则已删除: %OUTBOUND_RULE%
        set /a REMOVED_COUNT+=1
    ) else (
        echo [FAIL] 删除出站规则失败
    )
) else (
    echo [-] 出站规则不存在: %OUTBOUND_RULE%
)

if %REMOVED_COUNT% gtr 0 (
    echo.
    echo 成功删除 %REMOVED_COUNT% 条规则!
) else (
    echo.
    echo 没有找到需要删除的规则
)
exit /b 0

:list_rules
echo.
echo 正在查询端口 %PORT% 的防火墙规则...
echo.

set INBOUND_RULE=dplayer_%PORT%_inbound
set OUTBOUND_RULE=dplayer_%PORT%_outbound

set FOUND=0

REM 查询入站规则
echo 入站规则:
netsh advfirewall firewall show rule name="%INBOUND_RULE%" 2>nul | findstr /i /c:"规则名称:" /c:"方向:" /c:"协议:" /c:"本地端口:" /c:"操作:"
if %errorLevel% neq 0 (
    echo   (不存在)
) else (
    set /a FOUND+=1
)

echo.
echo 出站规则:
netsh advfirewall firewall show rule name="%OUTBOUND_RULE%" 2>nul | findstr /i /c:"规则名称:" /c:"方向:" /c:"协议:" /c:"本地端口:" /c:"操作:"
if %errorLevel% neq 0 (
    echo   (不存在)
) else (
    set /a FOUND+=1
)

echo.
if %FOUND% equ 0 echo 没有找到端口 %PORT% 的任何防火墙规则
exit /b 0

:help
echo.
echo Dplayer 防火墙规则管理脚本
echo.
echo 用法:
echo     firewall_manager.bat PORT [ACTION]
echo.
echo 参数:
echo     PORT    - 端口号 (1-65535)
echo     ACTION  - 操作类型，可选值:
echo               add    - 添加规则 (默认)
echo               remove - 删除规则
echo               list   - 查看规则
echo.
echo 示例:
echo     firewall_manager.bat 8080              # 添加端口 8080 的规则
echo     firewall_manager.bat 8080 add          # 添加端口 8080 的规则
echo     firewall_manager.bat 8080 remove       # 删除端口 8080 的规则
echo     firewall_manager.bat 8080 list         # 查看端口 8080 的规则
echo.
echo 注意:
echo     - 脚本需要管理员权限运行
echo     - 规则命名格式: dplayer_PORT_inbound/outbound
echo     - 会同时创建入站和出站规则
echo.
pause
exit /b 0
