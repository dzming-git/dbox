# -*- coding: utf-8 -*-
"""平台系统信息与路径（运行于主 Web 服务 dbox-web 进程）。

这两类数据原先挂在「系统监控」名下（/api/admin/system-monitor/info、/paths），
但它们是**平台安装信息**，不是监控指标。系统监控已作为插件搬出核心
（见 extensions/system-monitor），若继续由插件提供这两个接口，核心仪表板就会
反向依赖一个可卸载单元——按「被核心依赖的不能拆」的判据，它们必须留在核心。

端点：
  GET /api/admin/system-info   安装路径 / 版本 / 机器概要
  GET /api/admin/system-paths  数据 / 日志 / 配置 / 缩略图 / 临时目录
"""
import os
import platform

from flask import Blueprint, jsonify

from backend import paths

try:
    import psutil
except ImportError:
    psutil = None


def _version():
    try:
        from backend import runtime
        return getattr(runtime, 'version', '1.0.0')
    except Exception:
        return '1.0.0'


def create_blueprint(admin_required):
    bp = Blueprint('system_info_local', __name__)

    @bp.route('/api/admin/system-info', methods=['GET'])
    @admin_required
    def system_info():
        return jsonify({'success': True, 'info': {
            # 注：原先这里用 dirname 链推导安装根，少上了一层（得到 <root>/src）。
            # 统一改用 backend.paths 推导，避免各处重复且易错的相对路径计算。
            'install_path': paths.PROJECT_ROOT,
            'version': _version(),
            'python_version': platform.python_version(),
            'platform': platform.system(),
            'platform_version': platform.version(),
            'hostname': platform.node(),
            'cpu_count': psutil.cpu_count(logical=True) if psutil else 0,
            'memory_total': psutil.virtual_memory().total if psutil else 0,
            'disk_total': 0,
            'runtime_dir': paths.PROJECT_ROOT,
            'data_dir': paths.DATA_DIR,
            'logs_dir': os.path.join(paths.DATA_DIR, 'logs'),
        }})

    @bp.route('/api/admin/system-paths', methods=['GET'])
    @admin_required
    def system_paths():
        return jsonify({'success': True, 'paths': {
            'install_path': paths.PROJECT_ROOT,
            'data_dir': paths.DATA_DIR,
            'logs_dir': os.path.join(paths.DATA_DIR, 'logs'),
            'config_dir': paths.USER_CONFIG_DIR,
            'thumbnail_dir': paths.get_thumbnails_dir(),
            'temp_dir': os.path.join(paths.DATA_DIR, 'temp'),
        }})

    return bp
