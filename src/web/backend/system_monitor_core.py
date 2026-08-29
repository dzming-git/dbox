"""系统资源监控核心逻辑（运行于主 Web 服务 dbox-web 进程，端口 8080）。

原 extensions/system-monitor 插件已并入核心：系统资源监控是平台系统功能，
不应寄宿在被它管理的 dbox-extensions 进程。指标采集基于 psutil，
不依赖任何业务模块。鉴权由 local 蓝图层的 admin_required 统一处理。

提供：CPU/内存/磁盘/网络实时指标、系统信息、进程数、开机时长、历史曲线。
"""
import os
import sys
import time
import platform
import threading
import logging

logger = logging.getLogger('system_monitor')

# dbox 安装根目录（本文件位于 <root>/src/web/backend/）
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import psutil
except ImportError:
    psutil = None
    logger.warning('psutil 未安装，系统监控将返回占位数据')

try:
    _BOOT_TIME = psutil.boot_time() if psutil else time.time()
except Exception:
    _BOOT_TIME = time.time()

_HISTORY = {'cpu': [], 'mem': [], 'net_up': [], 'net_down': []}
_HISTORY_MAX = 60
_HISTORY_LOCK = threading.Lock()

try:
    _last_net = (psutil.net_io_counters().bytes_sent, psutil.net_io_counters().bytes_recv) if psutil else (0, 0)
except Exception:
    _last_net = (0, 0)


def _safe_net_io():
    if not psutil:
        return 0, 0
    try:
        io = psutil.net_io_counters()
        return io.bytes_sent, io.bytes_recv
    except Exception:
        return 0, 0


def _sample():
    global _last_net
    if not psutil:
        return
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory()
    sent, recv = _safe_net_io()
    up = max(0, sent - _last_net[0])
    down = max(0, recv - _last_net[1])
    _last_net = (sent, recv)
    with _HISTORY_LOCK:
        h = _HISTORY
        h['cpu'].append(round(cpu, 1))
        h['mem'].append(round(mem.percent, 1))
        h['net_up'].append(round(up / 1024, 1))
        h['net_down'].append(round(down / 1024, 1))
        for k in h:
            if len(h[k]) > _HISTORY_MAX:
                h[k] = h[k][-_HISTORY_MAX:]


def _sample_loop():
    while True:
        _sample()
        time.sleep(2)


_started = False


def _ensure_sampler():
    global _started
    if not _started and psutil:
        _started = True
        threading.Thread(target=_sample_loop, daemon=True).start()


def _cpu_info():
    if not psutil:
        return {'percent': 0, 'cores': 0, 'per_cpu': []}
    return {
        'percent': round(psutil.cpu_percent(interval=None), 1),
        'cores': psutil.cpu_count(logical=True) or 0,
        'per_cpu': [round(x, 1) for x in psutil.cpu_percent(interval=None, percpu=True)],
    }


def _mem_info():
    if not psutil:
        return {'total': 0, 'available': 0, 'used': 0, 'percent': 0}
    m = psutil.virtual_memory()
    return {'total': m.total, 'available': m.available, 'used': m.used, 'percent': round(m.percent, 1)}


def _disk_info():
    if not psutil:
        return []
    out = []
    for p in psutil.disk_partitions():
        if 'cdrom' in p.opts or p.fstype == '':
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
        except Exception:
            continue
        out.append({
            'mountpoint': p.mountpoint, 'fstype': p.fstype,
            'total': u.total, 'used': u.used, 'free': u.free,
            'percent': round(u.percent, 1),
        })
    return out


def _system_info():
    return {
        'platform': platform.system(),
        'platform_version': platform.version(),
        'hostname': platform.node(),
        'python_version': platform.python_version(),
        'cpu_count': psutil.cpu_count(logical=True) if psutil else 0,
        'mem_total': psutil.virtual_memory().total if psutil else 0,
        'boot_time': _BOOT_TIME,
    }


def _stats():
    proc_count = len(psutil.pids()) if psutil else 0
    uptime = int(time.time() - _BOOT_TIME) if _BOOT_TIME else 0
    return {'process_count': proc_count, 'uptime_seconds': uptime}


def _version():
    try:
        from backend import runtime
        return getattr(runtime, 'version', '1.0.0')
    except Exception:
        return '1.0.0'


def create_blueprint(admin_required):
    from flask import Blueprint, jsonify, request
    bp = Blueprint('system_monitor_local', __name__, url_prefix='/api/admin/system-monitor')
    _ensure_sampler()

    @bp.route('/metrics/current', methods=['GET'])
    @admin_required
    def metrics_current():
        cpu = _cpu_info()
        mem = _mem_info()
        disks = _disk_info()
        payload = {
            'success': True,
            'cpu': {
                'usage_percent': cpu['percent'],
                'count': cpu['cores'],
                'per_core_usage': cpu['per_cpu'],
                'freq_current': None,
            },
            'memory': {
                'usage_percent': mem['percent'],
                'used': mem['used'],
                'total': mem['total'],
                'available': mem['available'],
            },
            'disks': [{
                'device': d['mountpoint'],
                'mount_point': d['mountpoint'],
                'fs_type': d['fstype'],
                'usage_percent': d['percent'],
                'used': d['used'],
                'total': d['total'],
                'free': d['free'],
            } for d in disks],
            'uptime': int(time.time() - _BOOT_TIME) if _BOOT_TIME else 0,
        }
        return jsonify({'success': True, 'data': payload})

    @bp.route('/metrics/history', methods=['GET'])
    @admin_required
    def metrics_history():
        with _HISTORY_LOCK:
            return jsonify({'success': True, 'history': dict(_HISTORY)})

    @bp.route('/info', methods=['GET'])
    @admin_required
    def info():
        si = _system_info()
        info = {
            'install_path': _ROOT,
            'version': _version(),
            'python_version': si.get('python_version', platform.python_version()),
            'platform': si.get('platform', platform.system()),
            'cpu_count': si.get('cpu_count', 0),
            'memory_total': si.get('mem_total', 0),
            'disk_total': 0,
            'runtime_dir': _ROOT,
            'data_dir': os.path.join(_ROOT, 'data'),
            'logs_dir': os.path.join(_ROOT, 'data', 'logs'),
        }
        return jsonify({'success': True, 'info': info})

    @bp.route('/stats', methods=['GET'])
    @admin_required
    def stats():
        return jsonify({'success': True, **_stats()})

    @bp.route('/paths', methods=['GET'])
    @admin_required
    def paths():
        data_dir = os.path.join(_ROOT, 'data')
        paths = {
            'install_path': _ROOT,
            'data_dir': data_dir,
            'logs_dir': os.path.join(data_dir, 'logs'),
            'config_dir': os.path.join(data_dir, '..', 'config'),
            'thumbnail_dir': os.path.join(data_dir, 'thumbnails'),
            'temp_dir': os.path.join(data_dir, 'temp'),
        }
        return jsonify({'success': True, 'paths': paths})

    return bp
