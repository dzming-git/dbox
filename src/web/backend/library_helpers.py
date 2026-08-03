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
    """
    if not runtime.app_config.get('library_watch_enabled', True):
        log.debug('INFO', '资源库文件夹自动感知已通过配置禁用')
        return
    try:
        from library_watcher import start_library_watchers as _sw
        _sw(app=runtime.app, resource_bus=runtime.resource_bus, app_config=runtime.app_config,
            thumbnail_bus=runtime.thumbnail_bus, log=log)
    except Exception as e:
        log.debug('ERROR', f'启动资源库文件夹监控失败: {e}')
