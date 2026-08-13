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
from urllib.parse import urlencode

logger = logging.getLogger('dbox-ext-platform')

# 主服务内部契约接口地址（默认本机 8080）
_PLATFORM_HOST = os.environ.get('DBOX_WEB_HOST', '127.0.0.1')
_PLATFORM_PORT = int(os.environ.get('DBOX_WEB_PORT', '8080'))


def _internal_key_path():
    env = os.environ.get('DBOX_DATA_DIR')
    if env:
        return os.path.join(env, '.dbox_internal_key')
    # 本包在 src/extensions_host，向上两级为项目根 (dbox)
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    return os.path.join(root, 'data', '.dbox_internal_key')


def _internal_secret() -> str:
    """读取主服务写入的进程间共享内部密钥（与 internal_api 同文件）。"""
    try:
        with open(_internal_key_path(), 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        # 兜底：若密钥文件尚未生成（主服务未启动），用空串，请求会被 401 拒绝
        return ''


def _post(path: str, payload: dict) -> dict:
    url = f'http://{_PLATFORM_HOST}:{_PLATFORM_PORT}/internal{path}'
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        url, data=data, method='POST',
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'X-Dbox-Internal': _internal_secret(),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode('utf-8')
            return json.loads(body) if body else {}
    except Exception as e:
        logger.error('调用主服务 IPlatformAPI 失败 %s: %s', path, e)
        return {'success': False, 'message': f'平台调用失败: {e}'}


def _get(path: str, params: dict = None) -> dict:
    url = f'http://{_PLATFORM_HOST}:{_PLATFORM_PORT}/internal{path}'
    if params:
        url += '?' + urlencode(params)
    req = urllib.request.Request(
        url, method='GET',
        headers={'X-Dbox-Internal': _internal_secret()},
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
    r = _get('/allowed-libraries', {'user_id': user_id})
    return r.get('library_ids', []) if isinstance(r, dict) else []


def notify_job_done(job_id, result: dict) -> dict:
    """通知主服务某个脚本任务已完成（用于联动业务逻辑，如清理临时态）。"""
    return _post('/job-done', {'job_id': job_id, 'result': result or {}})


def library_disk_targets(library_id: int) -> list:
    """获取某资源库在磁盘上的监控根目录列表（供脚本 run 时确定落盘位置）。"""
    r = _get('/library-targets', {'library_id': library_id})
    return r.get('targets', []) if isinstance(r, dict) else []


def upsert_post_by_group(group_key, title=None, content='', resource_index_ids=None,
                         user_id=None, display_modes=None, author_name=None,
                         author_url=None, source_url=None) -> dict:
    """按 group_key 创建/更新帖子（供 X 下载脚本在入库后生成帖子）。"""
    return _post('/upsert-post', {
        'group_key': group_key,
        'title': title,
        'content': content,
        'resource_index_ids': resource_index_ids or [],
        'user_id': user_id,
        'display_modes': display_modes,
        'author_name': author_name,
        'author_url': author_url,
        'source_url': source_url,
    })


def resource_resolve(type_: str, ref: str) -> dict:
    """解析 AI 回复中的资源引用（type, ref）为可跳转详情页路径与封面。"""
    return _post('/resource-resolve', {'type': type_, 'ref': ref})


def file_feedback(ftype: str, title: str, content: str, extra: dict = None,
                  status: str = 'open'):
    """在反馈中心建一条反馈单，返回新单号；失败返回 None。

    extra / status 用于 AI 助手处理完成后的「跟踪单」：传入提交哈希与
    pending_verification 状态，便于反馈中心展示「待验证」并关联处理动作。
    """
    payload = {'type': ftype, 'title': title, 'content': content,
               'extra': extra, 'status': status}
    r = _post('/feedback', payload)
    return r.get('issue_id') if isinstance(r, dict) else None


def allowed_libraries(user_id: int = None) -> list:
    """返回某用户可写入的资源库 ID 列表。"""
    r = _get('/allowed-libraries', {'user_id': user_id})
    return r.get('library_ids', []) if isinstance(r, dict) else []
