"""Auto-split blueprint: post_resource_api (moved from main.py)."""
from core.models import PostRef
from backend.access import _user_can_read_post
from core.models import set_resource_modes as apply_resource_modes
from backend.access import resolve_user
from core.models import ResourceMode
from core.models import Gallery
from core.models import Text
from core.models import Post
from core.models import ResourceModeMembership
from sqlalchemy import or_
from backend.helpers import _resolve_post_refs
from auth_service import AuthService
from core.models import ResourceIndex
from core.models import Collection
from backend.helpers import _build_post_refs
from core.models import db
from core.models import UserRole
from core.models import Video
from datetime import datetime, timedelta
from backend.access import get_allowed_library_ids
from backend.access import resource_index_visible, default_library_id
import json
from backend.access import resolve_identity
from backend.access import auth_required
from flask import Blueprint, request, jsonify, send_file, send_from_directory, session, g, abort, Response, current_app

bp = Blueprint('post_resource_api', __name__)

@bp.route('/api/posts', methods=['GET'])
def get_posts():
    library_id = request.args.get('library_id', type=int)
    include_trash = request.args.get('include_trash') == '1'
    search = (request.args.get('search') or '').strip()
    q = Post.query
    if not include_trash:
        q = q.filter_by(in_trash=False)
    if library_id is not None:
        q = q.filter_by(library_id=library_id)
    if search:
        like = f'%{search}%'
        q = q.filter(or_(Post.title.ilike(like), Post.content.ilike(like)))
    posts = q.order_by(Post.created_at.desc()).all()
    # 帖子 read 权限：其引用资源的全部权限取交集
    allowed_libs = get_allowed_library_ids()
    visible = [p for p in posts if _user_can_read_post(p, allowed_libs)]
    return jsonify({'posts': [d.to_dict(resolve=True) for d in visible], 'total': len(visible)})

@bp.route('/api/posts', methods=['POST'])
@auth_required
def create_post():
    user = resolve_user()
    if not user:
        return jsonify({'error': '未登录'}), 401
    data = request.get_json(force=True, silent=True) or {}
    d = Post(title=data.get('title', ''), content=data.get('content', ''),
                owner_id=user.id, library_id=data.get('library_id'),
                author_name=data.get('author_name'),
                author_url=data.get('author_url'),
                source_url=data.get('source_url'))
    for ref in _build_post_refs(data.get('content', ''), data.get('refs')):
        d.refs.append(ref)
    db.session.add(d)
    db.session.commit()
    return jsonify(d.to_dict(resolve=True)), 201

@bp.route('/api/posts/<int:did>', methods=['GET'])
def get_post(did):
    d = Post.query.get(did)
    # 统一按「不存在」响应，不透露帖子及其引用资源的存在性。
    # 回收站内的帖子、或引用了未激活/未归类库的帖子，对外均不可见。
    if (not d or d.in_trash
            or not _user_can_read_post(d, get_allowed_library_ids())):
        return jsonify({'success': False, 'message': '资源不存在', 'code': 404}), 404
    return jsonify(d.to_dict(resolve=True))

@bp.route('/api/posts/<int:did>', methods=['PUT'])
@auth_required
def update_post(did):
    user = resolve_user()
    if not user:
        return jsonify({'error': '未登录'}), 401
    d = Post.query.get_or_404(did)
    if d.owner_id != user.id and user.role > UserRole.ADMIN:
        return jsonify({'error': '无权修改'}), 403
    data = request.get_json(force=True, silent=True) or {}
    if 'title' in data:
        d.title = data['title']
    if 'content' in data:
        d.content = data['content']
    if 'library_id' in data:
        d.library_id = data['library_id']
    if 'refs' in data or 'content' in data:
        d.refs.clear()
        for ref in _build_post_refs(data.get('content', ''), data.get('refs')):
            d.refs.append(ref)
    d.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(d.to_dict(resolve=True))

@bp.route('/api/posts/<int:did>', methods=['DELETE'])
@auth_required
def delete_post(did):
    user = resolve_user()
    if not user:
        return jsonify({'error': '未登录'}), 401
    d = Post.query.get_or_404(did)
    if d.owner_id != user.id and user.role > UserRole.ADMIN:
        return jsonify({'error': '无权删除'}), 403
    data = request.get_json(force=True, silent=True) or {}
    delete_resources = bool(data.get('delete_resources', False))
    # 可指定仅删除部分资源（资源索引 id 列表）；不传则按 delete_resources 全量判断
    selected_ids = data.get('resource_index_ids')
    if selected_ids is not None:
        try:
            selected_ids = [int(x) for x in selected_ids]
        except (TypeError, ValueError):
            selected_ids = []

    # 收集关联的资源索引 id（用于可选的连带删除）
    ri_ids = [r.resource_index_id for r in d.refs]

    # 先软删除帖子本身（进入回收站，可恢复）
    d.in_trash = True
    d.trashed_at = datetime.utcnow()
    db.session.commit()

    deleted_resources = []
    if delete_resources:
        for rid in ri_ids:
            # 用户指定了资源子集时，仅处理被勾选的资源
            if selected_ids is not None and rid not in selected_ids:
                continue
            ri = ResourceIndex.query.get(rid)
            if not ri:
                continue
            # 仍被其它「未删除」帖子引用 -> 不删（共享资源）
            other = (PostRef.query
                     .filter(PostRef.resource_index_id == rid)
                     .join(Post)
                     .filter(Post.id != d.id, Post.in_trash == False)
                     .first())
            if other:
                continue
            # 该资源仍有视频 / 图集实体（在库中可用）-> 不删，避免误删其它库数据
            if Video.query.filter_by(resource_index_id=rid).first():
                continue
            if Gallery.query.filter_by(resource_index_id=rid).first():
                continue
            # 删除孤立资源索引（其 URL/路径仍保留在磁盘，仅移除索引记录）
            db.session.delete(ri)
            deleted_resources.append(rid)
        db.session.commit()

    return jsonify({'success': True, 'deleted_resources': deleted_resources})

@bp.route('/api/posts/<int:did>/refs', methods=['POST'])
@auth_required
def add_post_ref(did):
    user = resolve_user()
    if not user:
        return jsonify({'error': '未登录'}), 401
    d = Post.query.get_or_404(did)
    if d.owner_id != user.id and user.role > UserRole.ADMIN:
        return jsonify({'error': '无权修改'}), 403
    data = request.get_json(force=True, silent=True) or {}
    refs = _resolve_post_refs([data])
    if not refs:
        return jsonify({'error': '无效的资源引用'}), 400
    ri, note = refs[0]
    pos = (d.refs[-1].position + 1) if d.refs else 0
    ref = PostRef(post_id=d.id, resource_index_id=ri.id, position=pos, note=note)
    db.session.add(ref)
    db.session.commit()
    return jsonify(ref.to_dict()), 201

@bp.route('/api/posts/<int:did>/refs/<int:rid>', methods=['DELETE'])
@auth_required
def remove_post_ref(did, rid):
    user = resolve_user()
    if not user:
        return jsonify({'error': '未登录'}), 401
    d = Post.query.get_or_404(did)
    if d.owner_id != user.id and user.role > UserRole.ADMIN:
        return jsonify({'error': '无权修改'}), 403
    ref = PostRef.query.filter_by(id=rid, post_id=did).first_or_404()
    db.session.delete(ref)
    db.session.commit()
    return jsonify({'success': True})

@bp.route('/api/resource-index', methods=['GET'])
def resource_index_pool():
    """统一资源池：供帖子引用选择器 / 各模式复用。支持按模式、库、类型、关键字筛选。

    只读接口，与 /api/videos、/api/posts 列表保持一致，公开可访问。
    """
    mode = request.args.get('mode')
    library_id = request.args.get('library_id', type=int)
    kind = request.args.get('kind')
    search = request.args.get('search', '').strip()
    q = ResourceIndex.query
    # 资源池是所有实体的底座，必须先过资源库可见性，否则可绕过各实体列表直接枚举
    allowed = get_allowed_library_ids()
    if allowed:
        q = q.filter(ResourceIndex.library_id.in_(allowed))
    else:
        q = q.filter(ResourceIndex.library_id == -1)
    if library_id is not None:
        q = q.filter_by(library_id=library_id)
    if kind:
        q = q.filter_by(kind=kind)
    items = q.order_by(ResourceIndex.updated_at.desc()).limit(500).all()
    # 补全缩略图：video_file/gallery_folder 的缩略图在 Video/Gallery 实体上，
    # 资源索引 meta.thumbnail 往往为空，导致帖子引用选择器预览图无法显示。
    video_ri_ids = [ri.id for ri in items if ri.kind == 'video_file']
    thumb_by_ri = {}
    if video_ri_ids:
        for v in Video.query.filter(Video.resource_index_id.in_(video_ri_ids)).all():
            if v.resource_index_id and v.thumbnail:
                thumb_by_ri[v.resource_index_id] = v.thumbnail
    result = []
    for ri in items:
        modes = [m.mode for m in ri.memberships]
        if mode and mode != ResourceMode.POST and mode not in modes:
            continue
        d = ri.to_dict()  # 已含 cover 字段
        d['modes'] = modes
        # 统一封面入口：优先用 resource_index.cover，缺失时回退到 Video 实体 thumbnail
        cover = ri.cover
        if not cover and ri.kind == 'video_file':
            cover = thumb_by_ri.get(ri.id)
        if cover:
            d['cover'] = cover
            d.setdefault('presentation', {})['thumbnail'] = cover
        if search:
            title = (ri.get_meta().get('title') or ri._basename() or '').lower()
            if search.lower() not in title:
                continue
        result.append(d)
    return jsonify({'items': result, 'total': len(result)})

@bp.route('/api/resource-index/<int:rid>/modes', methods=['POST'])
def set_resource_modes(rid):
    """设置资源的模式归属（手动管理界面调用）。"""
    user = resolve_user()
    if not user:
        return jsonify({'error': '未登录'}), 401
    ri = ResourceIndex.query.get_or_404(rid)
    data = request.get_json(force=True, silent=True) or {}
    apply_resource_modes(ri, data.get('modes') or [],
                          collection_id=data.get('collection_id'),
                          user_id=user.id if user else None)
    return jsonify(ri.to_dict())

@bp.route('/api/mode-collections', methods=['GET', 'POST'])
def collections_api():
    if request.method == 'GET':
        mode = request.args.get('mode')
        q = Collection.query
        if mode:
            q = q.filter_by(mode=mode)
        return jsonify({'collections': [c.to_dict() for c in q.all()]})
    user = resolve_user()
    if not user:
        return jsonify({'error': '未登录'}), 401
    data = request.get_json(force=True, silent=True) or {}
    name = data.get('name')
    mode = data.get('mode')
    if not name or not ResourceMode.is_valid(mode):
        return jsonify({'error': 'name/mode 无效'}), 400
    c = Collection(name=name, mode=mode, library_id=data.get('library_id'),
                   created_by=user.id)
    db.session.add(c)
    db.session.commit()
    return jsonify(c.to_dict()), 201

@bp.route('/api/texts', methods=['GET', 'POST'])
def texts_api():
    if request.method == 'GET':
        library_id = request.args.get('library_id', type=int)
        search = request.args.get('search', '').strip()
        sub = db.session.query(ResourceModeMembership.resource_index_id).filter_by(mode=ResourceMode.TEXT)
        q = Text.query.filter(Text.resource_index_id.in_(sub)).join(ResourceIndex)
        # 文本同样归属资源库：所属库未激活时对外不可见
        allowed = get_allowed_library_ids()
        if allowed:
            q = q.filter(ResourceIndex.library_id.in_(allowed))
        else:
            q = q.filter(ResourceIndex.library_id == -1)
        if library_id is not None:
            q = q.filter(ResourceIndex.library_id == library_id)
        items = q.all()
        if search:
            items = [t for t in items
                     if search.lower() in (t.summary or '').lower()
                     or search.lower() in (t.resource_index.get_meta().get('title') if t.resource_index else '').lower()]
        return jsonify({'texts': [t.to_dict() for t in items], 'total': len(items)})
    user = resolve_user()
    if not user:
        return jsonify({'error': '未登录'}), 401
    data = request.get_json(force=True, silent=True) or {}
    title = data.get('title') or '未命名文本'
    # 所有资源都必须有归属：未指定时落到主资源库，且只能写入已激活且有权限的库
    target_lib = data.get('library_id')
    allowed = get_allowed_library_ids()
    if target_lib is None:
        target_lib = default_library_id()
    if target_lib is None or target_lib not in allowed:
        return jsonify({'error': '资源不存在', 'code': 404}), 404
    ri = ResourceIndex(kind='text', location=data.get('location') or '',
                       library_id=target_lib,
                       meta=json.dumps({'title': title, 'summary': data.get('summary', '')}, ensure_ascii=False))
    db.session.add(ri)
    db.session.flush()
    t = Text(resource_index_id=ri.id, body=data.get('body', ''), summary=data.get('summary', ''))
    db.session.add(t)
    db.session.add(ResourceModeMembership(resource_index_id=ri.id, mode=ResourceMode.TEXT, created_by=user.id))
    db.session.commit()
    return jsonify(t.to_dict()), 201

@bp.route('/api/texts/<int:tid>', methods=['GET', 'PUT', 'DELETE'])
def text_item_api(tid):
    t = Text.query.get(tid)
    # 文本详情同样受资源库管控，不可见即视为不存在
    if not t or not resource_index_visible(t.resource_index):
        return jsonify({'error': '资源不存在', 'code': 404}), 404
    if request.method == 'GET':
        return jsonify(t.to_dict())
    user = resolve_user()
    if not user:
        return jsonify({'error': '未登录'}), 401
    if request.method == 'PUT':
        data = request.get_json(force=True, silent=True) or {}
        if 'body' in data:
            t.body = data['body']
        if 'summary' in data:
            t.summary = data['summary']
        if t.resource_index:
            m = t.resource_index.get_meta()
            if 'title' in data:
                m['title'] = data['title']
            if 'summary' in data:
                m['summary'] = data['summary']
            t.resource_index.meta = json.dumps(m, ensure_ascii=False)
        db.session.commit()
        return jsonify(t.to_dict())
    db.session.delete(t)
    if t.resource_index:
        db.session.delete(t.resource_index)
    db.session.commit()
    return jsonify({'status': 'deleted'})

@bp.route('/api/modes', methods=['GET'])
def available_modes():
    """返回当前可用模式及数量，供首页 tab 动态渲染。"""
    counts = dict(db.session.query(ResourceModeMembership.mode, db.func.count())
                  .group_by(ResourceModeMembership.mode).all())
    dyn_count = db.session.query(PostRef.resource_index_id).distinct().count()
    modes = []
    for m in ResourceMode.SINGLE:
        if counts.get(m):
            modes.append({'mode': m, 'count': counts[m]})
    if dyn_count:
        modes.append({'mode': ResourceMode.POST, 'count': dyn_count})
    return jsonify({'modes': modes})

@bp.route('/api/resource-index/<int:rid>/repoint', methods=['POST'])
def repoint_resource_index(rid):
    """重新指向磁盘位置：移动 / 重命名资源只需更新索引表一行，所有引用它的实体自动跟随。"""
    user = AuthService.get_current_user()
    if not user or user.role > UserRole.ADMIN:
        return jsonify({'error': '需要管理员权限'}), 403
    ri = ResourceIndex.query.get_or_404(rid)
    data = request.get_json(force=True, silent=True) or {}
    new_loc = data.get('location')
    if not new_loc:
        return jsonify({'error': '缺少 location'}), 400
    ri.location = new_loc
    ri.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(ri.to_dict())

@bp.route('/api/resource-index/<int:rid>/hidden', methods=['PATCH'])
def set_resource_index_hidden(rid):
    """设置资源是否隐藏：隐藏的资源不出现在视频 / 图集库列表，仅在帖子流可见。

    仅管理员可操作（来自帖子详情点进资源界面后编辑）。
    """
    user_id, role = resolve_identity()
    if not user_id or role > UserRole.ADMIN:
        return jsonify({'error': '需要管理员权限'}), 403
    ri = ResourceIndex.query.get_or_404(rid)
    data = request.get_json(force=True, silent=True) or {}
    if 'hidden' not in data:
        return jsonify({'error': '缺少 hidden 字段'}), 400
    ri.hidden = bool(data['hidden'])
    ri.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(ri.to_dict())
