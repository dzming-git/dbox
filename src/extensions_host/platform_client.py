# -*- coding: utf-8 -*-
"""IPlatformAPI 契约的 HTTP 客户端实现（扩展宿主侧调用主 Web 服务）。

扩展宿主（extensions_host）不直接 import 主模块的任何业务逻辑，
仅通过本客户端以 HTTP 调用主服务暴露的 IPlatformAPI 内部接口
（/internal/*，仅本机 127.0.0.1 可达）。

这是扩展宿主与主模块之间唯一的「反向调用」通道，方向单向、契约稳定。
"""
import os
import json
import logging
import urllib.request

logger = logging.getLogger('dbox-ext-platform')

# 主服务内部契约接口地址（默认本机 8080）
_PLATFORM_HOST = os.environ.get('DBOX_WEB_HOST', '127.0.0.1')
_PLATFORM_PORT = int(os.environ.get('DBOX_WEB_PORT', '8080'))
# 用于本机内部调用的服务间共享密钥（与 JWT 默认一致，生产应独立配置）
_INTERNAL_SECRET = os.environ.get('DBOX_INTERNAL_SECRET',
                                  'dbox-jwt-secret-key-change-in-production-2024')


def _post(path: str, payload: dict) -> dict:
    url = f'http://{_PLATFORM_HOST}:{_PLATFORM_PORT}/internal{path}'
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        url, data=data, method='POST',
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'X-Dbox-Internal': _INTERNAL_SECRET,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode('utf-8')
            return json.loads(body) if body else {}
    except Exception as e:
        logger.error('调用主服务 IPlatformAPI 失败 %s: %s', path, e)
        return {'success': False, 'message': f'平台调用失败: {e}'}


def ingest_file(library_id, path, kind=None, modes=('video',),
                collection_id=None, meta=None, user_id=None, hidden=False) -> dict:
    """请求主服务把文件/目录登记入库，并按 modes 归属模式。"""
    return _post('/ingest', {
        'library_id': library_id,
        'path': path,
        'kind': kind,
        'modes': list(modes),
        'collection_id': collection_id,
        'meta': meta,
        'user_id': user_id,
        'hidden': bool(hidden),
    })


def get_allowed_library_ids(user_id: int) -> list:
    """获取指定用户被允许写入的资源库 ID 列表。"""
    r = _post('/allowed-libraries', {'user_id': user_id})
    return r.get('library_ids', []) if isinstance(r, dict) else []


def notify_job_done(job_id, result: dict) -> dict:
    """通知主服务某个脚本任务已完成（用于联动业务逻辑，如清理临时态）。"""
    return _post('/job-done', {'job_id': job_id, 'result': result or {}})
