"""主服务内部 API（仅本机可达）。

拓展宿主进程（extensions_host，8093）在独立进程运行，无法直接 import 主服务的
core.models / library_watcher / backend.access 等业务模块。本蓝图把这些业务能力以
HTTP 接口形式暴露给 extensions_host，实现「拓展管理」与主模块的彻底解耦：

  - POST /internal/ingest              入库一个文件（视频/图集/文本）并按 modes 归属
  - GET  /internal/allowed-libraries   返回某用户可写入的资源库 ID 列表
  - POST /internal/resource-resolve    解析资源（供 AI 对话检索）
  - POST /internal/upsert-post         按 group_key 创建/更新帖子
  - GET  /internal/library-targets     返回某资源库的磁盘监控根目录

鉴权：仅接受来自本机（127.0.0.1）且携带 X-Dbox-Internal 内部密钥的请求。
密钥由主服务在启动时生成，并持久化到数据目录下的内部密钥文件
（data/.dbox_internal_key，仅本机可读），extensions_host 经 platform_client
读取同一文件，从而实现跨进程共享。
"""
import os
import secrets
from flask import Blueprint, request, jsonify, g

internal_bp = Blueprint('internal_api', __name__)

# 内部密钥文件路径（与 web 共享同一数据目录）。web 启动时写入，extensions_host 读取。
_INTERNAL_KEY_FILENAME = '.dbox_internal_key'


def _internal_key_path():
    env = os.environ.get('DBOX_DATA_DIR')
    if env:
        return os.path.join(env, _INTERNAL_KEY_FILENAME)
    # 应用目录向上三级为项目根
    here = os.path.dirname(os.path.abspath(__file__))            # src/web/backend
    root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(root, 'data', _INTERNAL_KEY_FILENAME)


def _read_internal_key():
    try:
        with open(_internal_key_path(), 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        return ''


def _check_internal_auth():
    """校验内部接口调用方身份（本机 + 内部密钥）。"""
    if request.remote_addr and request.remote_addr not in ('127.0.0.1', '::1'):
        return jsonify({'success': False, 'message': '内部接口仅允许本机访问'}), 403
    provided = request.headers.get('X-Dbox-Internal', '')
    key = _read_internal_key()
    if not key or provided != key:
        return jsonify({'success': False, 'message': '内部密钥校验失败'}), 401
    return None


def init_internal_key(app) -> str:
    """在 main 启动时生成内部密钥并写入共享文件，返回该密钥。"""
    key = secrets.token_hex(32)
    path = _internal_key_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(key)
        # 限制为仅所有者可读写（Windows 下 best-effort）
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception as e:
        print('[internal_api] 写入内部密钥失败: %s' % e)
    return key


@internal_bp.before_request
def _auth_guard():
    reject = _check_internal_auth()
    if reject is not None:
        return reject


@internal_bp.route('/internal/ingest', methods=['POST'])
def ingest():
    from backend.internal_ingest import ingest_file
    data = request.get_json(force=True, silent=True) or {}
    library_id = data.get('library_id')
    path = data.get('path')
    kind = data.get('kind')
    modes = data.get('modes') or ['video']
    collection_id = data.get('collection_id')
    meta = data.get('meta')
    user_id = data.get('user_id')
    hidden = data.get('hidden', False)
    if not path:
        return jsonify({'success': False, 'message': '缺少 path'}), 400
    from flask import current_app
    result = ingest_file(library_id, path, current_app._get_current_object(),
                         kind=kind, modes=modes, collection_id=collection_id,
                         meta=meta, user_id=user_id, hidden=hidden)
    return jsonify(result)


@internal_bp.route('/internal/allowed-libraries', methods=['GET'])
def allowed_libraries():
    from backend.access import get_allowed_library_ids
    user_id = request.args.get('user_id', type=int)
    ids = get_allowed_library_ids(user_id)
    return jsonify({'success': True, 'library_ids': ids})


@internal_bp.route('/internal/resource-resolve', methods=['POST'])
def resource_resolve():
    """解析 AI 回复中的资源引用 (type, ref) 为可跳转详情页路径与封面。

    原逻辑随 script_engine 一起迁移出主服务，这里在主进程内保留解析能力，
    供独立运行的拓展宿主经平台内部接口回调。
    """
    import re
    import json as _json
    rtype = (request.json or {}).get('type', '') if request.is_json else (request.get_json(force=True, silent=True) or {}).get('type', '')
    ref = (request.get_json(force=True, silent=True) or {}).get('ref', '')
    rtype = (rtype or '').strip().lower()
    ref = (ref or '').strip()
    if not ref:
        return jsonify({'success': True, 'found': False})

    from core.models import Video, Gallery, Post, Text, ResourceIndex
    from backend.access import get_allowed_library_ids

    _HEX64 = re.compile(r'^[0-9a-fA-F]{64}$')
    allowed = set(get_allowed_library_ids())

    def _visible(entity, rtype_):
        if getattr(entity, 'in_trash', False):
            return False
        if rtype_ in ('video', 'gallery'):
            ri = getattr(entity, 'resource_index', None)
            if ri is not None and getattr(ri, 'hidden', False):
                return False
            return entity.library_id in allowed
        if rtype_ == 'post':
            return getattr(entity, 'library_id', None) in allowed
        if rtype_ == 'text':
            ri = getattr(entity, 'resource_index', None)
            if ri is not None:
                if getattr(ri, 'hidden', False):
                    return False
                return ri.library_id in allowed
            return getattr(entity, 'library_id', None) in allowed
        return False

    def _cover(ri):
        return ri.cover if (ri and ri.cover) else None

    def _text_title(ri, fallback):
        title = ''
        if ri and ri.meta:
            try:
                title = (_json.loads(ri.meta) or {}).get('title', '') or ''
            except Exception:
                title = ''
        return title or (fallback or '')[:40] or '文本'

    result = None
    try:
        if rtype in ('video',):
            v = None
            if _HEX64.match(ref):
                v = Video.query.filter_by(hash=ref).first()
            elif ref.isdigit():
                v = Video.query.get(int(ref))
            if not v:
                v = Video.query.filter(Video.title.ilike('%' + ref + '%')).first()
            if v and _visible(v, 'video'):
                ri = ResourceIndex.query.get(v.resource_index_id) if v.resource_index_id else None
                result = {'type': 'video', 'id': v.id, 'hash': v.hash, 'title': v.title,
                          'cover_url': _cover(ri) or v.thumbnail, 'url': '/video/' + (v.hash or str(v.id))}
        elif rtype in ('gallery',):
            g = None
            if _HEX64.match(ref):
                g = Gallery.query.filter_by(hash=ref).first()
            elif ref.isdigit():
                g = Gallery.query.get(int(ref))
            if not g:
                g = Gallery.query.filter(Gallery.title.ilike('%' + ref + '%')).first()
            if g and _visible(g, 'gallery'):
                ri = ResourceIndex.query.get(g.resource_index_id) if g.resource_index_id else None
                result = {'type': 'gallery', 'id': g.id, 'hash': g.hash, 'title': g.title,
                          'cover_url': _cover(ri), 'url': '/gallery/' + (g.hash or str(g.id))}
        elif rtype in ('post',):
            p = None
            if ref.isdigit():
                p = Post.query.get(int(ref))
            if not p:
                p = Post.query.filter(Post.title.ilike('%' + ref + '%')).first()
            if p and _visible(p, 'post'):
                result = {'type': 'post', 'id': p.id, 'title': p.title or '(无标题)',
                          'cover_url': (p.cover_url if hasattr(p, 'cover_url') else None),
                          'url': '/post/' + str(p.id)}
        elif rtype in ('text',):
            t = None
            if ref.isdigit():
                t = Text.query.get(int(ref))
            if not t:
                t = Text.query.filter(Text.summary.ilike('%' + ref + '%')).first()
            if t and _visible(t, 'text'):
                ri = ResourceIndex.query.get(t.resource_index_id) if t.resource_index_id else None
                result = {'type': 'text', 'id': t.id, 'title': _text_title(ri, t.summary),
                          'cover_url': _cover(ri), 'url': '/text/' + str(t.id)}
    except Exception as e:
        return jsonify({'success': False, 'found': False, 'message': str(e)})

    if result:
        return jsonify({'success': True, 'found': True, **result})
    return jsonify({'success': True, 'found': False})


@internal_bp.route('/internal/upsert-post', methods=['POST'])
def upsert_post():
    from core.models import upsert_post_by_group
    data = request.get_json(force=True, silent=True) or {}
    post = upsert_post_by_group(
        group_key=data.get('group_key'),
        title=data.get('title'),
        content=data.get('content'),
        resource_index_ids=data.get('resource_index_ids') or [],
        user_id=data.get('user_id'),
        display_modes=data.get('display_modes'),
        author_name=data.get('author_name'),
        author_url=data.get('author_url'),
        source_url=data.get('source_url'),
    )
    return jsonify({'success': True, 'post_id': post.id})


@internal_bp.route('/internal/library-targets', methods=['GET'])
def library_targets():
    from library_watcher import get_watcher
    library_id = request.args.get('library_id', type=int)
    w = get_watcher()
    if not w:
        return jsonify({'success': True, 'targets': []})
    targets = w.library_disk_targets(library_id) if library_id else []
    return jsonify({'success': True, 'targets': targets})


@internal_bp.route('/internal/feedback', methods=['POST'])
def feedback():
    """AI 助手判定为「新反馈」时，由拓展宿主转发到此建单（身份：自动助手）。"""
    from backend.feedback_db import db_create_issue, init_feedback_db
    init_feedback_db()
    data = request.get_json(force=True, silent=True) or {}
    ftype = data.get('type', 'suggestion')
    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()
    if not title and not content:
        return jsonify({'success': False, 'message': '标题和内容不能同时为空'}), 400
    status = data.get('status', 'open')
    extra = data.get('extra') or None
    issue_id = db_create_issue(
        title=title, content=content, category=ftype,
        submitter='自动助手', source='ai_assistant', auto_classified=True,
        status=status, extra=extra,
    )
    return jsonify({'success': True, 'issue_id': issue_id})
