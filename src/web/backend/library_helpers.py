# -*- coding: utf-8 -*-
"""资源库 / 扫描辅助函数。

从 main.py 下沉而来，供 library_api 蓝图直接 import。

需要运行时单例（app / app_config / buses）的地方，统一从
backend.runtime 读取。
"""
import os
import re as _re
import threading
import time

from liblog import get_service_logger

log = get_service_logger('dbox-web')
from backend.runtime import runtime
from unified_tasks import (
    init_task_manager, create_task, update_task, finish_task, mark_started,
    is_cancel_requested, STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED,
    STATUS_CANCELLED,
)


# ============ 资源库扫描进度（web 侧，驱动 Video 表作为唯一索引源） ============
# 说明：这两个结构供既有 /scan-status、/scan-all/status 轮询接口读取（保持形状不变，
# 前端无需改动），同时扫描过程会登记进统一任务表（/api/tasks），从而具备进度、
# 取消、重试与历史记录。二者一律「原地更新」，不用 `=` 重新绑定全局，
# 否则其它模块 import 进来的引用会指向旧对象。
_library_scan_progress = {}
_library_scan_all_progress = {'status': 'idle', 'total': 0, 'done': 0, 'message': ''}

SCAN_MODES = ('incremental', 'verify', 'full')
_SCAN_MODE_LABEL = {'incremental': '增量同步', 'verify': '校验清理', 'full': '全量重建'}


class _ScanCancelled(Exception):
    """扫描在开始前就收到取消请求（内部信号）。"""


def _init_task_store():
    """初始化统一任务表（幂等）。失败不影响扫描本身，只损失任务可见性。"""
    try:
        from backend.paths import DATA_DIR
        init_task_manager(DATA_DIR)
        return True
    except Exception as e:
        log.debug('WARN', f'统一任务表初始化失败，本次扫描不登记任务: {e}')
        return False


def _finish_task_quiet(task_id, status, **kwargs):
    """结束任务但不让异常影响扫描结果。

    收尾失败只影响任务可见性（任务会一直显示为进行中），不能因此判定扫描失败，
    但要记 ERROR 级日志——这类失败是静默的，不记下来没人会发现。
    """
    try:
        finish_task(task_id, status, **kwargs)
    except Exception as e:
        log.debug('ERROR', f'更新任务状态失败({task_id}): {type(e).__name__}: {e}')


def _update_task_quiet(task_id, **kwargs):
    try:
        update_task(task_id, **kwargs)
    except Exception:
        pass


def _cancel_watcher(task_id, min_interval=1.0):
    """构造「是否收到取消请求」回调。

    扫描循环里可能每处理一个文件就问一次，直接查库会放大 IO，因此按
    min_interval 节流（默认最多每秒查一次），命中后结果缓存不再回源。
    """
    state = {'at': 0.0, 'stop': False}

    def _should_stop():
        if state['stop']:
            return True
        now = time.time()
        if now - state['at'] < min_interval:
            return False
        state['at'] = now
        try:
            state['stop'] = is_cancel_requested(task_id)
        except Exception:
            state['stop'] = False
        return state['stop']

    return _should_stop


def start_library_scan(library_id, owner_id=None, mode='incremental'):
    """启动单个资源库的扫描（异步，立即返回）。

    返回 (ok, message)：ok=False 表示未启动（监控器未就绪 / 已有扫描在跑）。
    扫描进度同步写入统一任务表（task_id = `scan:<library_id>`）。
    """
    from library_watcher import get_watcher
    watcher = get_watcher()
    if not watcher:
        return False, '资源库监控器未初始化'
    if _library_scan_progress.get(library_id, {}).get('status') == 'scanning':
        return False, '扫描已在进行中，请稍候...'
    if mode not in SCAN_MODES:
        mode = 'incremental'

    task_id = f'scan:{library_id}'
    if _init_task_store():
        try:
            create_task(
                task_id, 'scan', f'扫描资源库 #{library_id}',
                owner_id=owner_id, library_id=library_id,
                status=STATUS_RUNNING, progress=0,
                stage='准备中', detail='正在收集监控目录',
                params={'scope': 'library', 'library_id': library_id, 'mode': mode},
            )
            mark_started(task_id)
        except Exception as e:
            log.debug('ERROR', f'登记扫描任务失败: {e}')

    _library_scan_progress[library_id] = {
        'status': 'scanning', 'current': 0, 'total': 0, 'message': '扫描中...'
    }

    def _run():
        should_stop = _cancel_watcher(task_id)
        try:
            if should_stop():
                raise _ScanCancelled()
            # 后台线程没有请求上下文，用全局 runtime.app（不能用 current_app：
            # 应用上下文是线程局部的，新线程里解析不到，会直接抛运行时错误）
            with runtime.app.app_context():
                added, _updated, removed, cancelled = watcher.scan_library(
                    library_id, mode=mode, should_stop=should_stop
                )
            if cancelled or should_stop():
                _library_scan_progress[library_id] = {
                    'status': 'cancelled', 'message': '扫描已取消（已处理的部分保留）'
                }
                _finish_task_quiet(task_id, STATUS_CANCELLED,
                                   detail='用户取消，已处理的部分保留')
                return
            msg = f'扫描完成：新增 {added}，移除 {removed}'
            _library_scan_progress[library_id] = {
                'status': 'done', 'message': msg, 'added': added, 'removed': removed
            }
            _finish_task_quiet(task_id, STATUS_COMPLETED, progress=100,
                               stage='完成', detail=msg)
        except _ScanCancelled:
            _library_scan_progress[library_id] = {'status': 'cancelled', 'message': '扫描已取消'}
            _finish_task_quiet(task_id, STATUS_CANCELLED, detail='用户取消')
        except Exception as e:
            msg = f'扫描失败: {e}'
            _library_scan_progress[library_id] = {
                'status': 'error', 'error': str(e), 'message': msg
            }
            _finish_task_quiet(task_id, STATUS_FAILED, detail=msg, error_code='scan_failed')

    threading.Thread(target=_run, daemon=True,
                     name=f'scan-library-{library_id}').start()
    return True, '扫描已启动'


def start_scan_all(mode='incremental', owner_id=None):
    """一键同步所有启用中的资源库（异步，立即返回）。

    返回 (ok, message)。进度写入统一任务表（task_id = `scan:all`），
    并在每个库之间检查取消请求。
    """
    from library_watcher import get_watcher
    watcher = get_watcher()
    if not watcher:
        return False, '资源库监控器未初始化'
    if _library_scan_all_progress.get('status') == 'scanning':
        return False, '同步已在进行中，请稍候...'
    if mode not in SCAN_MODES:
        mode = 'incremental'

    label = _SCAN_MODE_LABEL[mode]
    task_id = 'scan:all'
    if _init_task_store():
        try:
            create_task(
                task_id, 'scan', f'{label}所有资源库',
                owner_id=owner_id, status=STATUS_RUNNING, progress=0,
                stage='准备中', detail='正在统计资源库',
                params={'scope': 'all', 'mode': mode},
            )
            mark_started(task_id)
        except Exception as e:
            log.debug('ERROR', f'登记同步任务失败: {e}')

    _library_scan_all_progress.clear()
    _library_scan_all_progress.update({
        'status': 'scanning', 'total': 0, 'done': 0, 'mode': mode,
        'message': f'正在{label}所有资源库...',
    })

    def _run_all():
        should_stop = _cancel_watcher(task_id)
        try:
            from core.models import ResourceLibrary
            with runtime.app.app_context():
                libs = ResourceLibrary.query.filter_by(is_active=True).all()
            total = len(libs)
            _library_scan_all_progress['total'] = total
            for i, lib in enumerate(libs, 1):
                if should_stop():
                    _library_scan_all_progress.update({
                        'status': 'cancelled',
                        'message': f'{label}已取消（已完成 {i - 1}/{total} 个资源库）',
                    })
                    _finish_task_quiet(task_id, STATUS_CANCELLED,
                                       detail=f'用户取消，已完成 {i - 1}/{total} 个资源库')
                    return
                try:
                    watcher.scan_library(lib.id, mode=mode, should_stop=should_stop)
                except Exception as e:
                    log.debug('ERROR', f'扫描库 {lib.id} 失败: {e}')
                progress = int(i / total * 100) if total else 100
                _library_scan_all_progress['done'] = i
                _library_scan_all_progress['message'] = f'已同步 {i}/{total} 个资源库'
                _update_task_quiet(task_id, progress=progress, stage=f'{i}/{total}',
                                   detail=f'已同步 {i}/{total} 个资源库')
            done_msg = f'{label}完成，共处理 {total} 个资源库'
            _library_scan_all_progress.update({'status': 'done', 'message': done_msg})
            _finish_task_quiet(task_id, STATUS_COMPLETED, progress=100,
                               stage='完成', detail=done_msg)
        except Exception as e:
            msg = f'同步失败: {e}'
            _library_scan_all_progress.update({
                'status': 'error', 'error': str(e), 'message': msg
            })
            _finish_task_quiet(task_id, STATUS_FAILED, detail=msg, error_code='scan_failed')

    threading.Thread(target=_run_all, daemon=True, name='scan-all').start()
    return True, f'{label}已启动'


def restart_scan_from_params(params, owner_id=None):
    """按任务登记的参数重放一次扫描（供统一任务的重试入口使用）。"""
    params = params or {}
    scope = params.get('scope', 'library')
    mode = params.get('mode', 'incremental')
    if scope == 'all':
        return start_scan_all(mode=mode, owner_id=owner_id)
    library_id = params.get('library_id')
    if library_id is None:
        return False, '任务缺少资源库标识，无法重试'
    return start_library_scan(int(library_id), owner_id=owner_id, mode=mode)

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
