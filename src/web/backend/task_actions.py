# -*- coding: utf-8 -*-
"""内置任务类型向框架注册的**动作实现**（重试 / 继续）。

每种任务只有它自己知道「怎么重放」：扫描要重放 scope 参数、脚本要向下载器
重投、上传则根本无法无感重放。过去这些写在路由里成一串 `if kind == ...`，
每加一种任务就要改框架，任务知识还泄漏到路由层。

现在改为：本模块登记各类型的实现，框架（task_routes）只查表调用。
新增一种可重试任务，在这里加一个函数并注册即可，路由零改动。

实现签名统一为：

    handler(task_dict) -> (ok, message) 或 (ok, message, extra)

extra 可携带响应细节（如 need_reupload 让前端引导用户重新上传、
status 指定 HTTP 状态码、job_id 等）。
"""
import json

from liblog import get_service_logger

log = get_service_logger('dbox-web')


def _retry_scan(task):
    """扫描任务自带完整可重放参数（scope / library_id / mode），直接重放。"""
    try:
        from backend.library_helpers import restart_scan_from_params
    except Exception as e:
        return False, f'扫描模块不可用：{e}'
    return restart_scan_from_params(task.get('params'), owner_id=task.get('owner_id'))


def _retry_thumbnail(task):
    """批量生成缺失缩略图：重新扫一遍缺失项即可，参数可重放。"""
    try:
        from backend.thumbnail_helpers import start_thumbnail_batch
    except Exception as e:
        return False, f'缩略图模块不可用：{e}'
    return start_thumbnail_batch(owner_id=task.get('owner_id'))


def _retry_meta(task):
    """补齐缺失的时长/大小：无额外参数，已补齐的会被跳过。"""
    try:
        from backend.library_helpers import start_metadata_backfill
    except Exception as e:
        return False, f'补齐模块不可用：{e}'
    return start_metadata_backfill(owner_id=task.get('owner_id'))


def _retry_script(task):
    """脚本任务：按登记时的可重放参数向下载器重新提交 run。

    下载器会创建新 job 并同步回统一任务表，用户在任务列表看到的是新任务。
    """
    params = task.get('params') or {}
    script_id = params.get('script_id')
    run_params = params.get('params') or {}
    if not script_id:
        return False, '该任务缺少脚本标识，无法重试'

    from flask import request as _req
    from shared.http_client import HttpClientError, proxy_request

    base = 'http://127.0.0.1:8092'
    # 透传鉴权头：下载器按用户身份判定脚本权限
    skip = {'host', 'content-length', 'connection', 'transfer-encoding'}
    headers = {k: v for k, v in _req.headers.items() if k.lower() not in skip}
    try:
        status, raw = proxy_request(
            'POST', f'{base}/api/scripts/{script_id}/run',
            json_body=run_params, headers=headers,
            cookies=dict(_req.cookies), timeout=30,
        )
        data = json.loads(raw.decode('utf-8')) if raw else {}
    except HttpClientError as e:
        return False, f'资源下载器服务不可用，请检查下载器进程是否运行：{e}', \
            {'status': 503, 'code': 503}
    if data.get('success'):
        return True, '已重新提交，请在任务列表查看新任务', {'job_id': data.get('job_id')}
    return False, (data.get('error') or data.get('message') or '重新提交失败'), \
        {'status': status or 400}


def _retry_upload(task):
    """上传任务无法无感重放：原始文件流不在了，必须用户重新选择文件。

    明确注册，好过被框架当成「未注册」给一句泛泛的提示。
    """
    return False, '上传任务需重新选择文件发起，无法自动重试', {'need_reupload': True}


# kind -> 重试实现。内置类型在这里集中登记；插件类型由插件自己登记。
_BUILTIN_RETRY = {
    'scan': _retry_scan,
    'thumbnail': _retry_thumbnail,
    'meta': _retry_meta,
    'script': _retry_script,
    'upload': _retry_upload,
}


def register_builtin_actions():
    """向框架注册内置任务的重试实现（幂等，可重复调用）。"""
    try:
        from unified_tasks import register_retry_handler
    except Exception as e:
        log.debug('WARN', f'统一任务模块不可用，内置动作未注册: {e}')
        return 0
    n = 0
    for kind, fn in _BUILTIN_RETRY.items():
        try:
            if register_retry_handler(kind, fn):
                n += 1
        except Exception as e:
            log.debug('WARN', f'注册 {kind} 的重试实现失败: {e}')
    return n
