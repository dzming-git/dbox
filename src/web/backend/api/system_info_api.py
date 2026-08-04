"""系统信息类接口（/api/system/*）。

原 src/web/api/system_api.py 的 system_bp 迁移而来，统一到 backend/api 体系：
使用 backend.access 的鉴权、backend.helpers 的响应封装、backend.runtime 的单例。

提供：系统信息、路径、统计、健康、同步状态/触发、资源监控指标。
"""
import os
import sys
import json
import threading
import subprocess
from pathlib import Path
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app

from backend.runtime import runtime
from backend.access import admin_required
from backend.helpers import success_response, error_response
from backend.paths import DATA_DIR

try:
    from liblog import get_service_logger as _get_service_logger

    def get_service_logger(name=''):
        return _get_service_logger(name)
except Exception:  # pragma: no cover - 运行时由 main 注入
    from logging import getLogger as _getLogger

    def get_service_logger(name=''):  # type: ignore
        return _getLogger(name)


# 统一使用标准 logging 语义（log.error(msg)），避免 ServiceLogger.error 签名
# 不兼容标准 logging 导致 /api/system/metrics 等接口 500（TypeError）。
import logging as _logging

_log = get_service_logger('dbox-web')
if not isinstance(_log, _logging.Logger):
    _log = _logging.getLogger('dbox-web')
    if not _log.handlers:
        _log.addHandler(_logging.NullHandler())
log = _log

# 后台指标采集缓存（带锁）
_metrics_cache = {
    'cpu': None,
    'memory': None,
    'disk': None,
    'timestamp': 0
}
_metrics_lock = threading.Lock()


def get_runtime_dir():
    """获取运行时目录（exe 同目录优先，否则项目根目录）。

    项目根的 data/ 为唯一权威数据存储位置。若代码位于 src/ 子目录下，
    向上多走一层确保命中项目根而非 src/data（避免重构后路径错位丢数据）。
    """
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    # 防止命中 src/data：当 base 解析到 src 目录时，再向上一层到项目根
    if os.path.basename(base) == 'src':
        base = os.path.dirname(base)
    candidates = [
        os.path.join(base, 'data'),
        os.path.join(base, 'runtime'),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return candidates[0]


def get_version():
    version_file = os.path.join(get_runtime_dir(), 'VERSION')
    if os.path.exists(version_file):
        try:
            with open(version_file, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except Exception:
            pass
    return '1.0.0'


def get_install_info():
    """获取安装信息。"""
    try:
        info = {
            'install_path': get_runtime_dir(),
            'version': get_version(),
            'python_version': sys.version,
            'platform': sys.platform,
        }
        return info
    except Exception as e:
        log.error(f"获取安装信息失败: {e}")
        return {'error': str(e)}


def _get_system_monitor():
    """延迟导入 SystemMonitor（top-level 模块，运行时 src 已在 path）。"""
    src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    try:
        from system.monitor import SystemMonitor
        return SystemMonitor
    except Exception as e:  # pragma: no cover
        log.error(f"导入 SystemMonitor 失败: {e}")
        return None


def collect_cpu_metrics():
    """采集 CPU 使用率（使用 psutil，兼容各平台）。"""
    try:
        import psutil
        per_core = psutil.cpu_percent(interval=0.3, percpu=True)
        freq = psutil.cpu_freq()
        # 直接复用刚采集到的每核心值求平均，避免紧接 interval=None 取 0 间隔增量导致恒为 0
        usage_percent = round(sum(per_core) / len(per_core), 1) if per_core else 0.0
        return {
            'usage_percent': usage_percent,
            'count': psutil.cpu_count(logical=True) or 0,
            'per_core_usage': per_core,
            'freq_current': getattr(freq, 'current', None),
        }
    except Exception as e:
        log.error(f"采集 CPU 指标失败: {e}")
        return None


def collect_memory_metrics():
    """采集内存使用率（使用 psutil）。"""
    try:
        import psutil
        vm = psutil.virtual_memory()
        return {
            'usage_percent': vm.percent,
            'used': vm.used,
            'total': vm.total,
            'available': vm.available,
        }
    except Exception as e:
        log.error(f"采集内存指标失败: {e}")
        return None


def collect_disk_metrics():
    """采集磁盘使用率（使用 psutil）。"""
    try:
        import psutil
        disks = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except Exception:
                continue
            disks.append({
                'device': part.device,
                'mount_point': part.mountpoint,
                'fs_type': part.fstype,
                'usage_percent': usage.percent,
                'used': usage.used,
                'total': usage.total,
                'free': usage.free,
            })
        return disks
    except Exception as e:
        log.error(f"采集磁盘指标失败: {e}")
        return None


def collect_metrics():
    """采集系统资源信息（CPU/内存/磁盘）。"""
    return {
        'cpu': collect_cpu_metrics(),
        'memory': collect_memory_metrics(),
        'disks': collect_disk_metrics() or [],
    }


def get_metrics_history():
    """获取指标历史（尝试读取监控日志）。"""
    from backend.runtime import runtime as _runtime
    try:
        history_file = os.path.join(get_runtime_dir(), 'data', 'metrics_history.json')
        if os.path.exists(history_file):
            with open(history_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:  # pragma: no cover
        log.error(f"读取指标历史失败: {e}")
    return []


system_info_bp = Blueprint('system_info_api', __name__, url_prefix='/api/system')


@system_info_bp.route('/info', methods=['GET'])
@admin_required
def system_info():
    """获取系统信息。"""
    try:
        import psutil
        info = {
            'install_path': get_runtime_dir(),
            'version': get_version(),
            'python_version': sys.version.split()[0],
            'platform': sys.platform,
            'cpu_count': psutil.cpu_count(),
            'memory_total': psutil.virtual_memory().total,
            'disk_total': psutil.disk_usage('/').total if sys.platform != 'win32' else psutil.disk_usage('C:\\').total,
            'runtime_dir': get_runtime_dir(),
            'data_dir': str(DATA_DIR),
            'logs_dir': os.path.join(str(DATA_DIR), 'logs'),
        }
        return success_response(info)
    except Exception as e:
        log.error(f"获取系统信息失败: {e}")
        return error_response(f"获取系统信息失败: {e}")


@system_info_bp.route('/paths', methods=['GET'])
@admin_required
def system_paths():
    """获取系统路径。"""
    try:
        paths = {
            'install_path': get_runtime_dir(),
            'data_dir': str(DATA_DIR),
            'logs_dir': os.path.join(str(DATA_DIR), 'logs'),
            'config_dir': os.path.join(str(DATA_DIR), '..', 'config'),
            'thumbnail_dir': os.path.join(str(DATA_DIR), 'thumbnails'),
            'temp_dir': os.path.join(str(DATA_DIR), 'temp'),
        }
        return success_response(paths)
    except Exception as e:
        log.error(f"获取系统路径失败: {e}")
        return error_response(f"获取系统路径失败: {e}")


@system_info_bp.route('/stats', methods=['GET'])
@admin_required
def system_stats():
    """获取系统统计信息。"""
    try:
        import psutil
        stats = {
            'cpu_percent': psutil.cpu_percent(interval=0.1),
            'memory_percent': psutil.virtual_memory().percent,
            'disk_percent': psutil.disk_usage('/').percent if sys.platform != 'win32' else psutil.disk_usage('C:\\').percent,
            'process_count': len(psutil.pids()),
            'boot_time': psutil.boot_time(),
            'uptime': datetime.now().timestamp() - psutil.boot_time(),
        }
        return success_response(stats)
    except Exception as e:
        log.error(f"获取系统统计失败: {e}")
        return error_response(f"获取系统统计失败: {e}")


@system_info_bp.route('/health', methods=['GET'])
def system_health():
    """系统健康检查。"""
    try:
        import psutil
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/') if sys.platform != 'win32' else psutil.disk_usage('C:\\')
        health = {
            'status': 'ok',
            'cpu_percent': psutil.cpu_percent(interval=0.1),
            'memory_percent': memory.percent,
            'disk_percent': disk.percent,
            'timestamp': datetime.now().isoformat(),
        }
        return success_response(health)
    except Exception as e:  # pragma: no cover
        log.error(f"健康检查失败: {e}")
        return error_response(f"健康检查失败: {e}")


@system_info_bp.route('/metrics', methods=['GET'])
@admin_required
def get_metrics():
    """获取系统资源指标。"""
    try:
        metrics = collect_metrics()
        return success_response(metrics)
    except Exception as e:  # pragma: no cover
        log.error(f"获取指标失败: {e}")
        return error_response(f"获取指标失败: {e}")


@system_info_bp.route('/metrics/cpu', methods=['GET'])
@admin_required
def get_cpu_metrics():
    """获取 CPU 指标。"""
    try:
        metrics = collect_cpu_metrics()
        return success_response(metrics)
    except Exception as e:  # pragma: no cover
        log.error(f"获取 CPU 指标失败: {e}")
        return error_response(f"获取 CPU 指标失败: {e}")


@system_info_bp.route('/metrics/memory', methods=['GET'])
@admin_required
def get_memory_metrics_route():
    """获取内存指标。"""
    try:
        metrics = collect_memory_metrics()
        return success_response(metrics)
    except Exception as e:  # pragma: no cover
        log.error(f"获取内存指标失败: {e}")
        return error_response(f"获取内存指标失败: {e}")


@system_info_bp.route('/metrics/disk', methods=['GET'])
@admin_required
def get_disk_metrics_route():
    """获取磁盘指标。"""
    try:
        metrics = collect_disk_metrics()
        return success_response(metrics)
    except Exception as e:  # pragma: no cover
        log.error(f"获取磁盘指标失败: {e}")
        return error_response(f"获取磁盘指标失败: {e}")


@system_info_bp.route('/metrics/history', methods=['GET'])
@admin_required
def get_metrics_history_route():
    """获取指标历史。"""
    try:
        history = get_metrics_history()
        return success_response(history)
    except Exception as e:  # pragma: no cover
        log.error(f"获取指标历史失败: {e}")
        return error_response(f"获取指标历史失败: {e}")
