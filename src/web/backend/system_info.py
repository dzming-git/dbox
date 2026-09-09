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
import json
import os
import platform
from datetime import datetime

from flask import Blueprint, jsonify

from backend import paths

try:
    import psutil
except ImportError:
    psutil = None


def _version():
    """版本号：唯一真源是项目根的 VERSION 文件（与 scripts/install.py 同读一处）。

    此前这里只取 runtime.version（拿不到就兜底 '1.0.0'），而安装脚本按 VERSION 文件
    （2.0.0）记录安装版本——两处版本不一致会让「升级状态」凭空为真。
    """
    try:
        ver_file = os.path.join(paths.PROJECT_ROOT, 'VERSION')
        if os.path.isfile(ver_file):
            with open(ver_file, 'r', encoding='utf-8') as f:
                v = (f.read() or '').strip()
            if v:
                return v
    except Exception:
        pass
    try:
        from backend import runtime
        return getattr(runtime, 'version', '1.0.0')
    except Exception:
        return '1.0.0'


def _install_info():
    """安装信息：安装时间 / 来源目录 / 升级状态。

    数据由 scripts/install.py 在安装（或升级）时写入 <配置区>/install_info.json，
    落在用户配置区而非源码目录，故换目录/重装仍保留「首次安装时间」。

    老安装没有这份记录（文件不存在）时做只读兜底，不臆造来源目录：
      - install_time：取主数据库文件的创建时间（≈ 首次运行时间）
      - source_dir  ：源码模式下服务就是从这个目录跑起来的，即当前运行目录
    """
    info = {
        'install_time': None,
        'source_dir': paths.PROJECT_ROOT,
        'version': _version(),
        'is_update': False,
        'previous_version': None,
        'updated_at': None,
        'update_count': 0,
        'estimated': True,  # 非安装脚本写入，而是推断出来的
    }
    try:
        cfg = paths.USER_CONFIG_DIR
        f = os.path.join(cfg, 'install_info.json')
        if os.path.isfile(f):
            with open(f, 'r', encoding='utf-8') as fp:
                saved = json.load(fp) or {}
            info.update({k: v for k, v in saved.items() if v is not None})
            info['estimated'] = False
    except Exception:
        pass

    if not info.get('install_time'):
        try:
            db = os.path.join(paths.get_databases_dir(), 'dbox.db')
            if os.path.isfile(db):
                info['install_time'] = datetime.fromtimestamp(
                    os.path.getctime(db)).replace(microsecond=0).isoformat()
        except Exception:
            pass
    if not info.get('source_dir'):
        info['source_dir'] = paths.PROJECT_ROOT
    return info


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
            # 「版本信息」卡片的 安装时间 / 来源目录 / 升级状态 读这里
            'install': _install_info(),
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
