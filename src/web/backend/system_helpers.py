# -*- coding: utf-8 -*-
"""系统 / 服务管理 / 关机控制 辅助函数。

从 main.py 下沉而来，供 system_api 蓝图直接 import。

需要运行时单例（app / app_config / buses）的地方，统一从
backend.runtime 读取。
"""
import os
import json
import time
import threading as _shutdown_threading
import urllib.request
import subprocess

from liblog import get_service_logger

log = get_service_logger('dbox-web')
from backend.runtime import runtime


# ============ 分层设置（用户 / 全局 / 浏览器） ============
# 合并优先级（高 -> 低）：browser > user > global > defaults
SETTINGS_DEFAULTS = {
    # 播放
    'autoplay': False,
    'defaultQuality': 'auto',
    'subtitleLanguage': 'off',
    'autoContinue': True,
    'volume': 80,
    'loop': False,
    'playbackRate': 1.0,
    'subtitleFontSize': 24,
    'subtitleColor': '#ffffff',
    # 外观
    'theme': 'sunset-dark',
    'language': 'zh-CN',
    # 列表与展示
    'blockDisliked': False,
    'defaultSort': 'recommended',
    'defaultOrder': 'desc',
    # 弹幕（后端保留，前端暂未开放编辑）
    'danmakuOpacity': 1.0,
    'danmakuSpeed': 1.0,
    'danmakuFont': 24,
    'danmakuColor': '#ffffff',
    'danmakuArea': 1.0,
}


def _apply_setting(scope, key, value):
    """将设置应用到对应范围（global/user/browser）。

    - global: 写入 AppSetting（全用户共享）
    - user:   写入当前登录用户的 UserPreference（key 前缀 'setting.'）
    - browser: 由前端 localStorage 维护，后端仅透传默认值，此处不落库
    """
    from core.models import AppSetting
    if scope == 'global':
        rec = AppSetting.query.filter_by(key=key).first()
        if not rec:
            rec = AppSetting(key=key, value=json.dumps(value, ensure_ascii=False))
            runtime.db.session.add(rec)
        else:
            rec.value = json.dumps(value, ensure_ascii=False)
        runtime.db.session.commit()
    elif scope == 'user':
        from flask import g
        from core.models import UserPreference
        uid = getattr(g, 'user_id', None)
        if not uid:
            return False
        pref_key = f'setting.{key}'
        pref = UserPreference.query.filter_by(user_id=uid, pref_key=pref_key).first()
        if not pref:
            pref = UserPreference(user_id=uid, pref_key=pref_key,
                                  pref_value=json.dumps(value, ensure_ascii=False))
            runtime.db.session.add(pref)
        else:
            pref.pref_value = json.dumps(value, ensure_ascii=False)
        runtime.db.session.commit()
    # browser 范围不落库，由前端负责
    return True


# ============ 配置管理 ============
# 默认配置（不含任何个人路径）。首次启动时由代码生成到系统数据区的用户配置文件中，
# 项目目录不再存放用户运行时配置（避免个人路径污染仓库、被他人拉取后不可用）。
def _default_config():
    return {
        "scan_directories": [],  # 由用户在界面中添加，不预置个人路径
        "auto_scan_on_startup": False,
        "library_watch_enabled": True,
        "supported_formats": [".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"],
        "default_tags": [],
        "default_priority": 0,
        "watch_poll_interval": 5,
        "scan_interval_minutes": 60,
        "host": "0.0.0.0",
        "auto_start": True,
        "ports": {
            "web": 8080,
            "main_app": 8080,
            "admin_app": 8081,
            "thumbnail": 5001
        },
        # HTTPS / TLS 支持（呼应反馈 202608090002：禁用 http、使用 https、可配置）。
        # 默认不启用，保持向后兼容；启用后优先使用 cert_file/key_file，
        # 缺失时自动生成自签名证书（默认 10 年，CN=localhost）一次。
        "tls": {
            "enabled": False,
            "cert_file": "",
            "key_file": "",
            "port": 8443,
            # 为 True 且 TLS 正常启用后，仅监听 HTTPS、不再提供明文 HTTP；
            # 为 False 时同时提供 HTTPS(tls.port) 与 HTTP(ports.web) 便于过渡。
            "disable_http": False
        }
    }


def load_config():
    """加载用户运行时配置。

    配置存放在系统数据区的用户配置文件（默认 %LOCALAPPDATA%/Dbox/config/web_config.json），
    不纳入 git。若文件不存在，则用默认配置生成并写入（首次启动自动初始化）。

    合并策略：默认配置为底座，用户文件覆盖同名键，保证新增键有默认值兜底。
    """
    from backend.paths import CONFIG_FILE, USER_CONFIG_DIR, _ensure_user_dirs
    _ensure_user_dirs()
    default = _default_config()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                user_cfg = json.load(f)
            return {**default, **user_cfg}
        except Exception:
            pass
    # 首次启动：生成默认配置文件
    try:
        os.makedirs(USER_CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default, f, indent=4, ensure_ascii=False)
    except Exception:
        pass
    return default


def save_config(cfg):
    from backend.paths import CONFIG_FILE, USER_CONFIG_DIR, _ensure_user_dirs
    _ensure_user_dirs()
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        log.debug('ERROR', f'保存配置失败: {e}')
        return False


# ============ 日志查看 ============
def parse_log_line(line: str, log_type: str) -> dict | None:
    """解析单行日志。

    格式:
    - maintenance/runtime/debug: [时间] | [等级] | [服务] | [内容]
    - operation: [时间] | [IP] | [服务] | [内容]
    """
    import re

    match = re.match(r'^\[([^\]]+)\]\s*\|\s*\[([^\]]+)\]\s*\|\s*\[([^\]]+)\]\s*\|\s*\[(.+)\]$', line)
    if not match:
        return None

    timestamp = match.group(1).strip()
    field2 = match.group(2).strip()
    service = match.group(3).strip()
    content = match.group(4).strip()

    result = {
        'timestamp': timestamp,
        'level': field2 if log_type != 'operation' else '',
        'source': field2 if log_type == 'operation' else '',
        'service': service,
        'content': content,
        'type': log_type,
        'user': ''
    }

    if log_type == 'operation':
        user_match = re.search(r'(?:用户|user)=([^|]+)', content)
        if user_match:
            result['user'] = user_match.group(1).strip()

    return result


# ============ 电脑关机控制（系统级，仅管理员） ============
_SHUTDOWN_CANCEL = {'after_tasks': False}
_SHUTDOWN_LOCK = _shutdown_threading.Lock()


def _count_active_tasks():
    """统计当前活跃任务数：转码/缩略图(ffmpeg) 进程 + 下载器活跃任务(best-effort)。"""
    count = 0
    try:
        import psutil
        for p in psutil.process_iter(['name', 'cmdline']):
            try:
                info = p.info
                name = (info.get('name') or '').lower()
                cmd = ' '.join(info.get('cmdline') or []).lower()
                if 'ffmpeg' in name or 'ffmpeg' in cmd:
                    if any(k in cmd for k in ('thumb', 'transcode', 'encode', 'scale', 'thumbnail')):
                        count += 1
            except Exception:
                continue
    except Exception:
        pass
    try:
        try:
            with urllib.request.urlopen('http://127.0.0.1:8092/api/tasks/active', timeout=1.5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    count += int(data.get('count', 0) or 0)
        except Exception:
            pass
    except Exception:
        pass
    return count


def _do_windows_shutdown(seconds=0):
    subprocess.run(f'shutdown /s /t {max(0, int(seconds))} /f', shell=True)


# ============ 服务管理 ============
# 服务元信息映射（nssm service name -> 服务描述）
_SERVICE_META = {
    'dbox-web': {
        'display_name': 'Dbox Web服务',
        'description': 'Web API 服务 - 视频管理、用户认证等',
        'health_url': None,
        'port': 8080,
    },
    'dbox-bus': {
        'display_name': 'Dbox 服务总线',
        'description': '服务总线代理，所有内部服务通信中枢',
        'health_url': None,
        'port': None,
    },
    'dbox-servicemgr': {
        'display_name': 'Dbox 服务管理',
        'description': '服务管理守护进程，定期扫描 dbox-* 服务状态',
        'health_url': None,
        'port': None,
    },
    'dbox-thumbnail': {
        'display_name': 'Dbox 缩略图服务',
        'description': '视频缩略图生成微服务（通过服务总线）',
        'health_url': None,
        'port': None,
    },
    'dbox-webui': {
        'display_name': 'Dbox WebUI服务',
        'description': 'Vue3 前端界面',
        'health_url': 'http://localhost:5173',
        'port': 5173,
        'health_check_json': False,
    },
    'dbox-downloader': {
        'display_name': 'Dbox 资源下载器',
        'description': '独立进程：外部脚本 / 下载器服务（与主服务解耦，崩溃不影响主服务）',
        'health_url': 'http://127.0.0.1:8092/api/health',
        'port': 8092,
    },
    'dbox-watchdog': {
        'display_name': 'Dbox 服务看门狗',
        'description': '服务看门狗 - 定时 ping 各服务总线，不可达则自动重启，多次失败告警',
        'health_url': None,
        'port': None,
    },
    'dbox-resource': {
        'display_name': 'Dbox 资源管理服务',
        'description': '资源管理微服务 - 资源库扫描、文件监控、索引管理',
        'health_url': None,
        'port': None,
    },
    'dbox-userd': {
        'display_name': 'Dbox 用户管理服务',
        'description': '用户管理微服务 - 用户增删改查与认证',
        'health_url': None,
        'port': None,
    },
    'dbox-systemd': {
        'display_name': 'Dbox 系统监控服务',
        'description': '系统监控微服务 - 监控 CPU、内存、磁盘等系统资源',
        'health_url': None,
        'port': None,
    },
    'dbox-historyd': {
        'display_name': 'Dbox 播放历史服务',
        'description': '播放历史微服务 - 记录播放进度、支持断点续播',
        'health_url': None,
        'port': None,
    },
    'dbox-collectiond': {
        'display_name': 'Dbox 收藏夹服务',
        'description': '收藏夹微服务 - 收藏视频、组织播放列表',
        'health_url': None,
        'port': None,
    },
    'dbox-searchd': {
        'display_name': 'Dbox 搜索服务',
        'description': '搜索微服务 - 全文搜索、视频标签和描述检索',
        'health_url': None,
        'port': None,
    },
    'dbox-scheduler': {
        'display_name': 'Dbox 定时任务服务',
        'description': '通用脚本轮询调度器 - 按各脚本 manifest 声明的 interval 周期执行',
        'health_url': None,
        'port': None,
    },
}

# 即使未注册为 Windows 服务也要出现在服务列表中的服务
# （如以独立进程方式运行的下载器）；其余服务仍以实际扫描结果为准。
_ALWAYS_LIST_SERVICES = ('dbox-downloader',)

# Windows 服务状态码映射
_WIN32_SVC_STATUS = {
    1: 'STOPPED',
    2: 'START_PENDING',
    3: 'STOP_PENDING',
    4: 'RUNNING',
    5: 'CONTINUE_PENDING',
    6: 'PAUSE_PENDING',
    7: 'PAUSED',
}

# 控制服务操作的锁（防止并发操作同一服务）
_svc_control_locks = {}


def _open_scm():
    """打开服务控制管理器 (SCM)"""
    import win32service
    return win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)


def _scan_services() -> list:
    """扫描 dbox- 前缀的 Windows 服务。"""
    try:
        import win32service

        scm = _open_scm()
        try:
            services = win32service.EnumServicesStatus(
                scm, win32service.SERVICE_WIN32, win32service.SERVICE_STATE_ALL
            )
            return [s[0] for s in services if s[0].startswith('dbox-')]
        finally:
            win32service.CloseServiceHandle(scm)
    except Exception as e:
        log.debug('DEBUG', f'[服务管理] win32service 扫描失败: {type(e).__name__}: {e}')

    try:
        result = subprocess.run(
            'sc query type= service state= all',
            capture_output=True, text=True, timeout=30, shell=True
        )
        if result.returncode == 0:
            dbox_svcs = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith('SERVICE_NAME:'):
                    svc_name = line.split(':', 1)[1].strip()
                    if svc_name.startswith('dbox-'):
                        dbox_svcs.append(svc_name)
            if dbox_svcs:
                return dbox_svcs
    except Exception as e2:
        log.debug('DEBUG', f'[服务管理] sc query fallback 也失败: {type(e2).__name__}: {e2}')

    known_services = [
        'dbox-web', 'dbox-bus', 'dbox-servicemgr', 'dbox-thumbnail',
        'dbox-webui', 'dbox-resource', 'dbox-userd', 'dbox-systemd',
        'dbox-historyd', 'dbox-collectiond', 'dbox-searchd',
        'dbox-downloader', 'dbox-watchdog',
    ]
    verified = []
    try:
        import win32service
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        for svc_name in known_services:
            try:
                hs = win32service.OpenService(scm, svc_name, win32service.SERVICE_QUERY_STATUS)
                win32service.CloseServiceHandle(hs)
                verified.append(svc_name)
            except Exception:
                pass
        win32service.CloseServiceHandle(scm)
    except Exception:
        pass

    merged = list(verified)
    for name in _ALWAYS_LIST_SERVICES:
        if name not in merged:
            merged.append(name)

    if merged:
        log.debug('DEBUG', f'[服务管理] 探测/合并找到 {len(merged)} 个服务: {merged}')
        return merged

    log.debug('DEBUG', '[服务管理] 扫描服务失败: 所有方法均无法获取服务列表')
    return []


def _get_service_status(service_name: str) -> dict:
    info = {'status': 'unknown', 'pid': None, 'memory_mb': None, 'cpu_percent': None}

    try:
        import win32service

        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        svc = win32service.OpenService(scm, service_name, win32service.SERVICE_QUERY_STATUS)
        status_info = win32service.QueryServiceStatus(svc)
        win32service.CloseServiceHandle(svc)
        win32service.CloseServiceHandle(scm)

        state_code = status_info[1]
        info['status'] = _WIN32_SVC_STATUS.get(state_code, f'UNKNOWN({state_code})')
    except Exception as e:
        log.debug('DEBUG', f'[服务管理] 获取服务状态异常 {service_name}: {type(e).__name__}: {e}')
        info['status'] = 'unknown'
        return info

    if info['status'] not in ('RUNNING', 'PAUSED'):
        return info

    try:
        import psutil

        meta = _SERVICE_META.get(service_name, {})
        port = meta.get('port')
        if port:
            for conn in psutil.net_connections(kind='inet'):
                if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                    info['pid'] = conn.pid
                    break

        if not info['pid']:
            app_name = 'python.exe'
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['name'] and proc.info['name'].lower() == app_name.lower():
                        cmdline = proc.info.get('cmdline') or []
                        cmdline_str = ' '.join(cmdline).lower()
                        if 'dbox' in cmdline_str and service_name.replace('dbox-', '') in cmdline_str:
                            info['pid'] = proc.info['pid']
                            break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        if info['pid']:
            try:
                proc = psutil.Process(info['pid'])
                mem_info = proc.memory_info()
                info['memory_mb'] = round(mem_info.rss / (1024 * 1024), 1)
                try:
                    info['cpu_percent'] = proc.cpu_percent(interval=None)
                except Exception:
                    info['cpu_percent'] = None
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                info['pid'] = None
    except ImportError:
        pass

    return info


def _check_service_health(service_name: str) -> dict:
    meta = _SERVICE_META.get(service_name, {})
    health_url = meta.get('health_url')

    result = {'status': 'unknown', 'latency_ms': None, 'detail': ''}

    if not health_url:
        result['status'] = 'healthy'
        result['detail'] = '自身服务'
        return result

    try:
        import requests
        start = time.time()
        resp = requests.get(health_url, timeout=1.5)
        latency = (time.time() - start) * 1000

        result['latency_ms'] = round(latency, 1)

        if resp.status_code == 200:
            if meta.get('health_check_json', True):
                try:
                    data = resp.json()
                    if data.get('status') == 'healthy':
                        result['status'] = 'healthy'
                        result['detail'] = '正常'
                    else:
                        result['status'] = 'unhealthy'
                        result['detail'] = f"状态异常: {data.get('status', 'unknown')}"
                except (ValueError, KeyError):
                    result['status'] = 'unhealthy'
                    result['detail'] = '响应格式异常'
            else:
                result['status'] = 'healthy'
                result['detail'] = '正常'
        else:
            result['status'] = 'unhealthy'
            result['detail'] = f"HTTP {resp.status_code}"
    except requests.exceptions.Timeout:
        result['status'] = 'unhealthy'
        result['detail'] = '超时（>1.5s）'
    except requests.exceptions.ConnectionError:
        result['status'] = 'unhealthy'
        result['detail'] = '连接失败'
    except Exception as e:
        result['status'] = 'unknown'
        result['detail'] = str(e)[:100]

    return result
