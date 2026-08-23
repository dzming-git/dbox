<#
.SYNOPSIS
    Dbox 服务统一启停脚本（单一事实来源）。

.DESCRIPTION
    所有 dbox 组件的启动/停止/重启/状态查询都必须走本脚本，
    禁止手动 `python xxx.py` 或 `Start-Process` 拉进程——否则会与 NSSM
    服务管理的实例冲突（端口打架、双实例抢数据、配置改了不生效）。

    本脚本只是 NSSM 的薄封装：start/stop/restart/status 全部委托给 nssm.exe，
    保证「只有一个受管实例」这一不变量。

.PARAMETER Action
    start | stop | restart | status

.PARAMETER Service
    服务名（不带 dbox- 前缀也可）：extensions, web, webui, downloader,
    thumbnail, collection, history, search, resource, user, system, watchdog, bus, scheduler

.EXAMPLE
    .\scripts\dbox.ps1 restart extensions
    .\scripts\dbox.ps1 status
    .\scripts\dbox.ps1 stop webui
#>
param(
    [Parameter(Position = 0, Mandatory = $true)]
    [ValidateSet('start', 'stop', 'restart', 'status')]
    [string]$Action,

    [Parameter(Position = 1)]
    [string]$Service = ''
)

$ErrorActionPreference = 'Stop'
$nssm = 'C:\Tools\nssm.exe'

if (-not (Test-Path $nssm)) {
    Write-Error "nssm.exe not found at $nssm"
    exit 1
}

# 服务名 -> NSSM 服务键
$ServiceMap = @{
    'extensions' = 'dbox-extensions'
    'web'        = 'dbox-web'
    'webui'      = 'dbox-webui'
    'downloader' = 'dbox-downloader'
    'thumbnail'  = 'dbox-thumbnail'
    'collection' = 'dbox-collectiond'
    'history'    = 'dbox-historyd'
    'search'     = 'dbox-searchd'
    'resource'   = 'dbox-resource'
    'user'       = 'dbox-userd'
    'system'     = 'dbox-systemd'
    'watchdog'   = 'dbox-watchdog'
    'bus'        = 'dbox-bus'
    'scheduler'  = 'dbox-scheduler'
}

function Resolve-Service {
    param([string]$Name)
    if (-not $Name) { return $null }
    if ($Name.StartsWith('dbox-')) { return $Name }
    if ($ServiceMap.ContainsKey($Name)) { return $ServiceMap[$Name] }
    # 允许直接传 dbox-xxx 之外的模糊名
    return "dbox-$Name"
}

if ($Action -eq 'status') {
    if ($Service) {
        $svc = Resolve-Service $Service
        & $nssm status $svc
    } else {
        Write-Host "=== 所有 dbox 服务状态 ==="
        foreach ($key in $ServiceMap.Keys) {
            $svc = $ServiceMap[$key]
            $st = (& $nssm status $svc 2>$null)
            Write-Host ("{0,-12} {1,-22} {2}" -f $key, $svc, $st)
        }
    }
    exit 0
}

if (-not $Service) {
    Write-Error "Action '$Action' requires a Service name. See help."
    exit 1
}

$svc = Resolve-Service $Service
if (-not $svc) {
    Write-Error "Unknown service '$Service'. Valid: $($ServiceMap.Keys -join ', ')"
    exit 1
}

Write-Host "[$Action] $svc ..."
& $nssm $Action $svc
if ($LASTEXITCODE -ne 0) {
    Write-Warning "nssm $Action $svc returned exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}
Start-Sleep -Seconds 2
& $nssm status $svc
