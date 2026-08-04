# -*- coding: utf-8 -*-
"""资源库 / 扫描辅助函数。

从 main.py 下沉而来，供 library_api 蓝图直接 import。

需要运行时单例（app / app_config / buses）的地方，统一从
backend.runtime 读取。
"""
import os
import re as _re

from liblog import get_service_logger

log = get_service_logger('dbox-web')
from backend.runtime import runtime


# ============ 资源库扫描进度（web 侧，驱动 Video 表作为唯一索引源） ============
_library_scan_progress = {}
_library_scan_all_progress = {'status': 'idle', 'total': 0, 'done': 0, 'message': ''}

# 非法库名字符
_INVALID_NAME_RE = _re.compile(r'[\\/:*?"<>|]')


def _list_system_drives():
    """返回 Windows 盘符列表；其他平台返回 ['/']。"""
    try:
        import ctypes as _ctypes
        if os.name == 'nt' and _ctypes is not None:
            bitmask = _ctypes.windll.kernel32.GetLogicalDrives()
            drives = []
            for i in range(26):
                if bitmask & (1 << i):
                    drives.append(chr(65 + i) + ':\\')
            if drives:
                return drives
    except Exception:
        pass
    return ['C:\\'] if os.name == 'nt' else ['/']


def _restart_library_watchers():
    """（重新）启动资源库文件夹监控，供服务启动 / 新增文件夹后调用。

    监控路径优先从 resourced 查询（资源库/文件夹的磁盘路径），回退到现有 Video.local_path。
    文件的新增/删除/重命名会实时同步到 Video 表，无需手动扫描。

    受配置 ``library_watch_enabled`` 控制：关闭后只停止监控、不执行全量扫描
    （全量扫描由独立的 ``auto_scan_on_startup`` 开关决定）。
    """
    if not runtime.app_config.get('library_watch_enabled', True):
        log.debug('INFO', '资源库文件夹自动感知已通过配置禁用')
        # 关闭监控：先停掉已有监控器，避免后台继续感知文件变化
        try:
            from library_watcher import get_watcher
            _w = get_watcher()
            if _w is not None:
                _w.stop_all()
        except Exception:
            pass
        return
    try:
        from library_watcher import start_library_watchers as _sw
        _sw(app=runtime.app, resource_bus=runtime.resource_bus, app_config=runtime.app_config,
            thumbnail_bus=runtime.thumbnail_bus, log=log)
    except Exception as e:
        log.debug('ERROR', f'启动资源库文件夹监控失败: {e}')


def _initial_library_scan():
    """启动时全量扫描（受 ``auto_scan_on_startup`` 控制，独立于文件夹实时监控）。

    对配置中的 ``scan_directories`` 与各资源库监控目标执行一次 diff 同步，
    使 Video 表与磁盘保持一致。即使关闭了实时文件夹监控，也可单独开启此项。
    """
    if not runtime.app_config.get('auto_scan_on_startup', True):
        log.debug('INFO', '启动时自动扫描已通过配置禁用')
        return
    try:
        from library_watcher import start_library_watchers as _sw, get_watcher
        # 复用 watcher 的 diff 逻辑：若监控已启用则直接取实例，否则临时构建一个
        _w = get_watcher()
        if _w is None:
            _w = _sw(app=runtime.app, resource_bus=runtime.resource_bus,
                     app_config=runtime.app_config, thumbnail_bus=runtime.thumbnail_bus, log=log)
        _w.full_scan_once()
        log.maintenance('INFO', '启动全量扫描已完成')
    except Exception as e:
        log.debug('ERROR', f'启动全量扫描失败: {e}')
