"""服务运维核心逻辑（运行于主 Web 服务 dbox-web 进程，端口 8080）。

本模块是原 extensions/service-ops 插件的纯函数实现「下沉」到核心后的唯一副本。
服务管理是平台系统控制面，必须常驻、独立于被它管理的 dbox-extensions 进程——
停掉 dbox-extensions 后，管理页仍能列出所有服务（含其自身为 STOPPED）并把它重新拉起。

执行层（实际启停）统一走 servicemgr（服务总线，常驻、不被重启、看门狗自愈依赖它）；
本模块只做扫描/状态/控制转发/日志解析，保持全局唯一执行源，避免多份实现漂移。
"""
import os
import re
import sys
import json
import time
import threading
import logging

logger = logging.getLogger('service_ops')

# dbox 安装根目录（本文件位于 <root>/src/web/backend/）
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 尝试导入可选依赖（与 dbox 主服务同环境时可用）
try:
    import win32service  # noqa: F401
except Exception:
    win32service = None
try:
    import psutil  # noqa: F401
except Exception:
    psutil = None

# ---------------------------------------------------------------------------
# 服务元信息（静态配置，等价于 service_mgr_adapter._SERVICE_META）
# ---------------------------------------------------------------------------
_SERVICE_META = {
    'dbox-web': {
        'display_name': 'Dbox Web服务',
        'description': 'Web API 服务 - 视频管理、用户认证等',
        'port': 8080,
    },
    'dbox-bus': {
        'display_name': 'Dbox 服务总线',
        'description': '服务总线代理，所有内部服务通信中枢',
        'port': None,
    },
    'dbox-servicemgr': {
        'display_name': 'Dbox 服务管理',
        'description': '服务管理守护进程，定期扫描 dbox-* 服务状态',
        'port': None,
    },
    'dbox-thumbnail': {
        'display_name': 'Dbox 缩略图服务',
        'description': '视频缩略图生成微服务（通过服务总线）',
        'port': None,
    },
    'dbox-webui': {
        'display_name': 'Dbox WebUI服务',
        'description': 'Vue3 前端界面（纯前端静态站点，由 web 服务托管，无后端健康端点）',
        'port': 5173,
    },
    'dbox-downloader': {
        'display_name': 'Dbox 资源下载器',
        'description': '独立进程：外部脚本 / 下载器服务',
        'port': 8092,
    },
    'dbox-watchdog': {
        'display_name': 'Dbox 服务看门狗',
        'description': '服务看门狗 - 定时 ping 各服务总线，不可达则自动重启',
        'port': None,
    },
    'dbox-resource': {
        'display_name': 'Dbox 资源管理服务',
        'description': '资源管理微服务 - 资源库扫描、文件监控、索引管理',
        'port': None,
    },
    'dbox-userd': {
        'display_name': 'Dbox 用户管理服务',
        'description': '用户管理微服务 - 用户增删改查与认证',
        'port': None,
    },
    'dbox-systemd': {
        'display_name': 'Dbox 系统监控服务',
        'description': '系统监控微服务 - 监控 CPU、内存、磁盘等系统资源',
        'port': None,
    },
    'dbox-historyd': {
        'display_name': 'Dbox 播放历史服务',
        'description': '播放历史微服务 - 记录播放进度、支持断点续播',
        'port': None,
    },
    'dbox-collectiond': {
        'display_name': 'Dbox 收藏夹服务',
        'description': '收藏夹微服务 - 收藏视频、组织播放列表',
        'port': None,
    },
    'dbox-searchd': {
        'display_name': 'Dbox 搜索服务',
        'description': '搜索微服务 - 全文搜索、视频标签和描述检索',
        'port': None,
    },
    'dbox-scheduler': {
        'display_name': 'Dbox 定时任务服务',
        'description': '通用脚本轮询调度器 - 按各脚本 manifest 声明的 interval 周期执行',
        'port': None,
    },
}

# 即使未注册为 Windows 服务也要出现在服务列表中的服务
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

# 状态 -> 是否视为“健康在线”
_ONLINE_STATES = ('RUNNING', 'PAUSED')


# ---------------------------------------------------------------------------
# 服务发现 / 状态 / 控制（等价于 BusServiceMgrAdapter）
# ---------------------------------------------------------------------------
def _scan_nssm_services():
    """扫描所有 dbox- 前缀的 Windows 服务。"""
    if win32service:
        try:
            scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
            try:
                services = win32service.EnumServicesStatus(
                    scm, win32service.SERVICE_WIN32, win32service.SERVICE_STATE_ALL
                )
                result = [s[0] for s in services if s[0].startswith('dbox-')]
                if result:
                    return result
            finally:
                win32service.CloseServiceHandle(scm)
        except Exception:
            pass

    try:
        import subprocess
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
    except Exception:
        pass

    known_services = list(_SERVICE_META.keys())
    verified = []
    if win32service:
        try:
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
    if verified:
        return verified

    return list(_SERVICE_META.keys())


def _query_windows_status(service_name):
    """返回 (state_str, None) 或 (None, 'not_found')。"""
    if not win32service:
        return None, 'no_api'
    try:
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        try:
            svc = win32service.OpenService(scm, service_name, win32service.SERVICE_QUERY_STATUS)
            status_info = win32service.QueryServiceStatus(svc)
            win32service.CloseServiceHandle(svc)
            return _WIN32_SVC_STATUS.get(status_info[1], 'UNKNOWN'), None
        finally:
            win32service.CloseServiceHandle(scm)
    except Exception:
        return None, 'not_found'


def _find_pid(service_name, port):
    """通过监听端口或命令行匹配定位服务进程 PID。"""
    if not psutil:
        return None
    if port:
        try:
            for conn in psutil.net_connections(kind='inet'):
                if (conn.laddr and conn.laddr.port == port
                        and conn.status == psutil.CONN_LISTEN):
                    return conn.pid
        except Exception:
            pass
    try:
        svc_key = service_name.replace('dbox-', '')
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['name'] and proc.info['name'].lower() in ('python.exe', 'pythonw.exe'):
                    cmdline_str = ' '.join(proc.info.get('cmdline') or []).lower()
                    if 'dbox' in cmdline_str and svc_key in cmdline_str:
                        return proc.info['pid']
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return None


def _get_service_info(service_name):
    """获取单个服务的详细信息。"""
    meta = _SERVICE_META.get(service_name, {})
    info = {
        'name': service_name,
        'service_name': service_name,
        'display_name': meta.get('display_name', service_name),
        'description': meta.get('description', ''),
        'status': 'unknown',
        'system_status': 'unknown',
        'pid': None,
        'memory_mb': None,
        'cpu_percent': None,
        'port': meta.get('port'),
        'health_status': 'unknown',
    }

    def _done():
        info['system_status'] = info['status']
        return info

    state, err = _query_windows_status(service_name)
    if state is None:
        info['status'] = 'not_found' if err == 'not_found' else 'unknown'
        return _done()
    info['status'] = state

    if info['status'] not in _ONLINE_STATES:
        return _done()

    port = info['port']
    pid = _find_pid(service_name, port)
    info['pid'] = pid

    if pid:
        try:
            proc = psutil.Process(pid)
            mem_info = proc.memory_info()
            info['memory_mb'] = round(mem_info.rss / (1024 * 1024), 1)
            try:
                info['cpu_percent'] = proc.cpu_percent(interval=None)
            except Exception:
                info['cpu_percent'] = None
        except Exception:
            info['pid'] = None

    info['health_status'] = 'healthy' if info['status'] == 'RUNNING' else 'degraded'
    return _done()


# ---------------------------------------------------------------------------
# 统一执行层：服务启停优先交给 servicemgr（总线）执行
# ---------------------------------------------------------------------------
_BUS_NAME = 'com.dbox.servicemgr'
_BUS_IFACE = 'com.dbox.ServiceMgr'
_BUS_RPC_PORT = 15555
_BUS_PUB_PORT = 15556
_bus_client = None
_bus_failed_at = 0.0
_bus_lock = threading.Lock()
_BUS_COOLDOWN_SEC = 60


def _src_servicebus_dir():
    """定位 src/servicebus 目录。"""
    here = os.path.dirname(os.path.abspath(__file__))          # .../src/web/backend
    app_root = os.path.dirname(os.path.dirname(os.path.dirname(here)))   # dbox 根
    return os.path.join(app_root, 'src', 'servicebus')


def _get_bus():
    """延迟创建总线客户端；连接失败后冷却一段时间再试。"""
    global _bus_client, _bus_failed_at
    now = time.time()
    with _bus_lock:
        if _bus_client is not None:
            return _bus_client
        if now - _bus_failed_at < _BUS_COOLDOWN_SEC:
            return None
        try:
            sb = _src_servicebus_dir()
            if sb not in sys.path:
                sys.path.insert(0, sb)
            from servicebus import BusClient
            _bus_client = BusClient('core-service-ops', host='127.0.0.1',
                                    rpc_port=_BUS_RPC_PORT, pub_port=_BUS_PUB_PORT)
            return _bus_client
        except Exception as e:
            _bus_failed_at = now
            logger.warning('总线客户端创建失败，服务控制将回退本地实现: %s', e)
            return None


def _bus_control(service_name, action, timeout_ms=30000):
    """通过总线让 servicemgr 执行启停重启。"""
    bus = _get_bus()
    if bus is None:
        return False, None
    method = {'start': 'start_service',
              'stop': 'stop_service',
              'restart': 'restart_service'}.get(action)
    if not method:
        return False, None
    try:
        r = bus.call_method(_BUS_NAME, _BUS_IFACE, method,
                            {'name': service_name}, timeout=timeout_ms)
        if isinstance(r, dict):
            return True, r
        return False, None
    except Exception as e:
        global _bus_failed_at
        _bus_failed_at = time.time()
        logger.warning('总线控制服务 %s 失败，回退本地: %s', service_name, e)
        return False, None


# ---------------------------------------------------------------------------
# 人工停止抑制（与看门狗 watchdog_adapter 的跨进程约定）
# ---------------------------------------------------------------------------
_SUPPRESS_TTL_SEC = 2 * 3600
_suppress_file_cache = None


def _suppress_file():
    global _suppress_file_cache
    if _suppress_file_cache:
        return _suppress_file_cache
    app_root = _ROOT
    root = os.environ.get('DBOX_DATA_DIR') or app_root
    _suppress_file_cache = os.path.join(root, 'data', 'service_suppress.json')
    return _suppress_file_cache


def _read_suppress():
    p = _suppress_file()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f) or {}
        now = time.time()
        return {k: v for k, v in data.items()
                if isinstance(v, (int, float)) and v > now}
    except Exception:
        return {}


def _write_suppress(data):
    p = _suppress_file()
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(data, f)


def _set_suppress(service_name, seconds=_SUPPRESS_TTL_SEC):
    try:
        data = _read_suppress()
        data[service_name] = time.time() + seconds
        _write_suppress(data)
    except Exception as e:
        logger.warning('写入服务抑制标记失败: %s', e)


def _clear_suppress(service_name):
    try:
        data = _read_suppress()
        if service_name in data:
            data.pop(service_name)
            _write_suppress(data)
    except Exception as e:
        logger.warning('清除服务抑制标记失败: %s', e)


def _control_service(service_name, action):
    """启动/停止/重启 Windows 服务。

    优先通过总线交给 servicemgr 执行（全局唯一执行层）；总线不可用时
    回退本地 win32service → sc/nssm，保证功能不中断。
    """
    handled, r = _bus_control(service_name, action)
    if handled and r is not None:
        return bool(r.get('success')), r.get('message') or (action + ' 完成')
    return _control_service_local(service_name, action)


def _control_service_local(service_name, action):
    """本地兜底：win32service 优先，sc/nssm 兜底。"""
    if win32service:
        try:
            scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
            try:
                svc = win32service.OpenService(
                    scm, service_name,
                    win32service.SERVICE_START
                    | win32service.SERVICE_STOP
                    | win32service.SERVICE_QUERY_STATUS
                )
                try:
                    status = win32service.QueryServiceStatus(svc)
                    current_state = status[1]

                    if action == 'start':
                        if current_state == win32service.SERVICE_RUNNING:
                            return {'success': True, 'message': '服务已在运行'}
                        win32service.StartService(svc, None)
                        return {'success': True, 'message': '启动命令已发送'}
                    if action == 'stop':
                        if current_state in (win32service.SERVICE_STOPPED, win32service.SERVICE_STOP_PENDING):
                            return {'success': True, 'message': '服务已停止'}
                        win32service.ControlService(svc, win32service.SERVICE_CONTROL_STOP)
                        return {'success': True, 'message': '停止命令已发送'}
                    if action == 'restart':
                        if current_state != win32service.SERVICE_STOPPED:
                            win32service.ControlService(svc, win32service.SERVICE_CONTROL_STOP)
                            time.sleep(0.5)
                        win32service.StartService(svc, None)
                        return {'success': True, 'message': '重启命令已发送'}
                finally:
                    win32service.CloseServiceHandle(svc)
            finally:
                win32service.CloseServiceHandle(scm)
        except Exception as e:
            return {'success': False, 'message': str(e)}

    try:
        import subprocess
        verb = {'start': 'start', 'stop': 'stop', 'restart': 'restart'}.get(action)
        r = subprocess.run(f'sc {verb} {service_name}', shell=True,
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            return {'success': True, 'message': f'{action} 命令已发送'}
        return {'success': False, 'message': (r.stdout + r.stderr).strip() or 'sc 命令失败'}
    except Exception as e:
        return {'success': False, 'message': str(e)}


# 缓存 + 后台扫描（用于 CPU% 时间差计算）
_CACHE = {}
_CACHE_LOCK = threading.Lock()
_SCANNER_STARTED = False


def _do_scan():
    names = _scan_nssm_services()
    merged = list(names)
    for n in _ALWAYS_LIST_SERVICES:
        if n not in merged:
            merged.append(n)
    with _CACHE_LOCK:
        for n in merged:
            try:
                _CACHE[n] = _get_service_info(n)
            except Exception:
                meta = _SERVICE_META.get(n, {})
                _CACHE[n] = {
                    'name': n, 'service_name': n,
                    'display_name': meta.get('display_name', n),
                    'description': meta.get('description', ''),
                    'status': 'unknown', 'system_status': 'unknown',
                    'pid': None, 'memory_mb': None, 'cpu_percent': None,
                    'port': meta.get('port'), 'health_status': 'unknown',
                }


def _scan_loop():
    _do_scan()
    while True:
        time.sleep(5)
        _do_scan()


def _ensure_scanner():
    global _SCANNER_STARTED
    if not _SCANNER_STARTED:
        _SCANNER_STARTED = True
        t = threading.Thread(target=_scan_loop, daemon=True)
        t.start()


def _all_services():
    with _CACHE_LOCK:
        return list(_CACHE.values())


# ---------------------------------------------------------------------------
# 日志解析
# ---------------------------------------------------------------------------
def _parse_log_line(line, log_type):
    line = line.rstrip('\n')
    match = re.match(
        r'^\[([^\]]+)\]\s*\|\s*\[([^\]]+)\]\s*\|\s*\[([^\]]+)\]\s*\|\s*\[(.+)\]$', line)
    if not match:
        return None
    timestamp = match.group(1).strip()
    field2 = match.group(2).strip()
    service = match.group(3).strip()
    content = match.group(4).strip()
    return {
        'timestamp': timestamp,
        'level': field2 if log_type != 'operation' else '',
        'source': field2 if log_type == 'operation' else '',
        'service': service,
        'content': content,
        'user': '',
    }


def _read_log(cat, offset=0, limit=200, module=None, level=None, keyword=None):
    """读取 data/logs 下指定类别的日志，支持过滤与分页。"""
    env = os.environ.get('DBOX_DATA_DIR')
    base = env or os.path.join(_ROOT, 'data')
    paths = {
        'maintenance': os.path.join(base, 'logs', 'maintenance.log'),
        'runtime': os.path.join(base, 'logs', 'runtime.log'),
        'debug': os.path.join(base, 'logs', 'debug.log'),
        'operation': os.path.join(base, 'logs', 'operation.log'),
    }
    p = paths.get(cat)
    if not p or not os.path.exists(p):
        return [], 0, False, []
    try:
        with open(p, 'r', encoding='utf-8', errors='replace') as f:
            raw = f.readlines()
        parsed = []
        for l in raw:
            pl = _parse_log_line(l, cat)
            if not pl:
                continue
            parsed.append({
                'ts': pl['timestamp'],
                'level': pl['level'] or 'INFO',
                'module': pl['service'],
                'msg': pl['content'],
            })
        modules = sorted({pl['module'] for pl in parsed if pl['module']})
        if module:
            parsed = [pl for pl in parsed if pl['module'] == module]
        if level:
            parsed = [pl for pl in parsed if pl['level'] == level.upper()]
        if keyword:
            kw = keyword.lower()
            parsed = [pl for pl in parsed
                      if kw in (pl['msg'] + ' ' + pl['module'] + ' ' + pl['ts']).lower()]
        total = len(parsed)
        ordered = parsed[::-1]
        page = ordered[offset:offset + limit]
        has_more = offset + limit < total
        return page, total, has_more, modules
    except Exception as e:
        return [{'ts': '', 'level': 'ERROR', 'module': '', 'msg': str(e)}], 0, False, []
