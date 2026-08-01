"""Auto-split blueprint: post_resource_api (moved from main.py)."""
from backend.access import auth_required
from flask import Blueprint, request, jsonify, send_file, send_from_directory, session, g, abort, Response, current_app

bp = Blueprint('post_resource_api', __name__)

@bp.route('/api/posts', methods=['GET'])
def get_posts():
    import main
    library_id = main.request.args.get('library_id', type=int)
    include_trash = main.request.args.get('include_trash') == '1'
    q = main.Post.query
    if not include_trash:
        q = q.filter_by(in_trash=False)
    if library_id is not None:
        q = q.filter_by(library_id=library_id)
    posts = q.order_by(main.Post.created_at.desc()).all()
    # 帖子 read 权限：其引用资源的全部权限取交集
    allowed_libs = main.get_allowed_library_ids()
    visible = [p for p in posts if main._user_can_read_post(p, allowed_libs)]
    return main.jsonify({'posts': [d.to_dict(resolve=True) for d in visible], 'total': len(visible)})

@bp.route('/api/posts', methods=['POST'])
@auth_required
def create_post():
    import main
    user = main.resolve_user()
    if not user:
        return main.jsonify({'error': '未登录'}), 401
    data = main.request.get_json(force=True, silent=True) or {}
    d = main.Post(title=data.get('title', ''), content=data.get('content', ''),
                owner_id=user.id, library_id=data.get('library_id'),
                author_name=data.get('author_name'),
                author_url=data.get('author_url'),
                source_url=data.get('source_url'))
    for ref in main._build_post_refs(data.get('content', ''), data.get('refs')):
        d.refs.append(ref)
    main.db.session.add(d)
    main.db.session.commit()
    return main.jsonify(d.to_dict(resolve=True)), 201

@bp.route('/api/posts/<int:did>', methods=['GET'])
def get_post(did):
    import main
    d = main.Post.query.get_or_404(did)
    if not main._user_can_read_post(d, main.get_allowed_library_ids()):
        return main.jsonify({'success': False, 'message': '无权访问该帖子（引用了您无权限的资源）'}), 403
    return main.jsonify(d.to_dict(resolve=True))

@bp.route('/api/posts/<int:did>', methods=['PUT'])
@auth_required
def update_post(did):
    import main
    user = main.resolve_user()
    if not user:
        return main.jsonify({'error': '未登录'}), 401
    d = main.Post.query.get_or_404(did)
    if d.owner_id != user.id and user.role < main.UserRole.ADMIN:
        return main.jsonify({'error': '无权修改'}), 403
    data = main.request.get_json(force=True, silent=True) or {}
    if 'title' in data:
        d.title = data['title']
    if 'content' in data:
        d.content = data['content']
    if 'library_id' in data:
        d.library_id = data['library_id']
    if 'refs' in data or 'content' in data:
        d.refs.clear()
        for ref in main._build_post_refs(data.get('content', ''), data.get('refs')):
            d.refs.append(ref)
    d.updated_at = main.datetime.utcnow()
    main.db.session.commit()
    return main.jsonify(d.to_dict(resolve=True))

@bp.route('/api/posts/<int:did>', methods=['DELETE'])
@auth_required
def delete_post(did):
    import main
    user = main.resolve_user()
    if not user:
        return main.jsonify({'error': '未登录'}), 401
    d = main.Post.query.get_or_404(did)
    if d.owner_id != user.id and user.role < main.UserRole.ADMIN:
        return main.jsonify({'error': '无权删除'}), 403
    data = main.request.get_json(force=True, silent=True) or {}
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
    d.trashed_at = main.datetime.utcnow()
    main.db.session.commit()

    deleted_resources = []
    if delete_resources:
        for rid in ri_ids:
            # 用户指定了资源子集时，仅处理被勾选的资源
            if selected_ids is not None and rid not in selected_ids:
                continue
            ri = main.ResourceIndex.query.get(rid)
            if not ri:
                continue
            # 仍被其它「未删除」帖子引用 -> 不删（共享资源）
            other = (main.PostRef.query
                     .filter(main.PostRef.resource_index_id == rid)
                     .join(main.Post)
                     .filter(main.Post.id != d.id, main.Post.in_trash == False)
                     .first())
            if other:
                continue
            # 该资源仍有视频 / 图集实体（在库中可用）-> 不删，避免误删其它库数据
            if main.Video.query.filter_by(resource_index_id=rid).first():
                continue
            if main.Gallery.query.filter_by(resource_index_id=rid).first():
                continue
            # 删除孤立资源索引（其 URL/路径仍保留在磁盘，仅移除索引记录）
            main.db.session.delete(ri)
            deleted_resources.append(rid)
        main.db.session.commit()

    return main.jsonify({'success': True, 'deleted_resources': deleted_resources})

@bp.route('/api/posts/<int:did>/refs', methods=['POST'])
@auth_required
def add_post_ref(did):
    import main
    user = main.resolve_user()
    if not user:
        return main.jsonify({'error': '未登录'}), 401
    d = main.Post.query.get_or_404(did)
    if d.owner_id != user.id and user.role < main.UserRole.ADMIN:
        return main.jsonify({'error': '无权修改'}), 403
    data = main.request.get_json(force=True, silent=True) or {}
    refs = main._resolve_post_refs([data])
    if not refs:
        return main.jsonify({'error': '无效的资源引用'}), 400
    ri, note = refs[0]
    pos = (d.refs[-1].position + 1) if d.refs else 0
    ref = main.PostRef(post_id=d.id, resource_index_id=ri.id, position=pos, note=note)
    main.db.session.add(ref)
    main.db.session.commit()
    return main.jsonify(ref.to_dict()), 201

@bp.route('/api/posts/<int:did>/refs/<int:rid>', methods=['DELETE'])
@auth_required
def remove_post_ref(did, rid):
    import main
    user = main.resolve_user()
    if not user:
        return main.jsonify({'error': '未登录'}), 401
    d = main.Post.query.get_or_404(did)
    if d.owner_id != user.id and user.role < main.UserRole.ADMIN:
        return main.jsonify({'error': '无权修改'}), 403
    ref = main.PostRef.query.filter_by(id=rid, post_id=did).first_or_404()
    main.db.session.delete(ref)
    main.db.session.commit()
    return main.jsonify({'success': True})

@bp.route('/api/resource-index', methods=['GET'])
def resource_index_pool():
    import main
    """统一资源池：供帖子引用选择器 / 各模式复用。支持按模式、库、类型、关键字筛选。

    只读接口，与 /api/videos、/api/posts 列表保持一致，公开可访问。
    """
    mode = main.request.args.get('mode')
    library_id = main.request.args.get('library_id', type=int)
    kind = main.request.args.get('kind')
    search = main.request.args.get('search', '').strip()
    q = main.ResourceIndex.query
    if library_id is not None:
        q = q.filter_by(library_id=library_id)
    if kind:
        q = q.filter_by(kind=kind)
    items = q.order_by(main.ResourceIndex.updated_at.desc()).limit(500).all()
    # 补全缩略图：video_file/gallery_folder 的缩略图在 main.Video/main.Gallery 实体上，
    # 资源索引 meta.thumbnail 往往为空，导致帖子引用选择器预览图无法显示。
    video_ri_ids = [ri.id for ri in items if ri.kind == 'video_file']
    thumb_by_ri = {}
    if video_ri_ids:
        for v in main.Video.query.filter(main.Video.resource_index_id.in_(video_ri_ids)).all():
            if v.resource_index_id and v.thumbnail:
                thumb_by_ri[v.resource_index_id] = v.thumbnail
    result = []
    for ri in items:
        modes = [m.mode for m in ri.memberships]
        if mode and mode != main.ResourceMode.POST and mode not in modes:
            continue
        d = ri.to_dict()  # 已含 cover 字段
        d['modes'] = modes
        # 统一封面入口：优先用 resource_index.cover，缺失时回退到 main.Video 实体 thumbnail
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
    return main.jsonify({'items': result, 'total': len(result)})

@bp.route('/api/resource-index/<int:rid>/modes', methods=['POST'])
def set_resource_modes(rid):
    import main
    """设置资源的模式归属（手动管理界面调用）。"""
    user = main.resolve_user()
    if not user:
        return main.jsonify({'error': '未登录'}), 401
    ri = main.ResourceIndex.query.get_or_404(rid)
    data = main.request.get_json(force=True, silent=True) or {}
    main.apply_resource_modes(ri, data.get('modes') or [],
                          collection_id=data.get('collection_id'),
                          user_id=user.id if user else None)
    return main.jsonify(ri.to_dict())

@bp.route('/api/mode-collections', methods=['GET', 'POST'])
def collections_api():
    import main
    if main.request.method == 'GET':
        mode = main.request.args.get('mode')
        q = main.Collection.query
        if mode:
            q = q.filter_by(mode=mode)
        return main.jsonify({'collections': [c.to_dict() for c in q.all()]})
    user = main.resolve_user()
    if not user:
        return main.jsonify({'error': '未登录'}), 401
    data = main.request.get_json(force=True, silent=True) or {}
    name = data.get('name')
    mode = data.get('mode')
    if not name or not main.ResourceMode.is_valid(mode):
        return main.jsonify({'error': 'name/mode 无效'}), 400
    c = main.Collection(name=name, mode=mode, library_id=data.get('library_id'),
                   created_by=user.id)
    main.db.session.add(c)
    main.db.session.commit()
    return main.jsonify(c.to_dict()), 201

@bp.route('/api/texts', methods=['GET', 'POST'])
def texts_api():
    import main
    if main.request.method == 'GET':
        library_id = main.request.args.get('library_id', type=int)
        search = main.request.args.get('search', '').strip()
        sub = main.db.session.query(main.ResourceModeMembership.resource_index_id).filter_by(mode=main.ResourceMode.TEXT)
        q = main.Text.query.filter(main.Text.resource_index_id.in_(sub))
        if library_id is not None:
            q = q.join(main.ResourceIndex).filter(main.ResourceIndex.library_id == library_id)
        items = q.all()
        if search:
            items = [t for t in items
                     if search.lower() in (t.summary or '').lower()
                     or search.lower() in (t.resource_index.get_meta().get('title') if t.resource_index else '').lower()]
        return main.jsonify({'texts': [t.to_dict() for t in items], 'total': len(items)})
    user = main.resolve_user()
    if not user:
        return main.jsonify({'error': '未登录'}), 401
    data = main.request.get_json(force=True, silent=True) or {}
    title = data.get('title') or '未命名文本'
    ri = main.ResourceIndex(kind='text', location=data.get('location') or '',
                       library_id=data.get('library_id'),
                       meta=main.json.dumps({'title': title, 'summary': data.get('summary', '')}, ensure_ascii=False))
    main.db.session.add(ri)
    main.db.session.flush()
    t = main.Text(resource_index_id=ri.id, body=data.get('body', ''), summary=data.get('summary', ''))
    main.db.session.add(t)
    main.db.session.add(main.ResourceModeMembership(resource_index_id=ri.id, mode=main.ResourceMode.TEXT, created_by=user.id))
    main.db.session.commit()
    return main.jsonify(t.to_dict()), 201

@bp.route('/api/texts/<int:tid>', methods=['GET', 'PUT', 'DELETE'])
def text_item_api(tid):
    import main
    t = main.Text.query.get_or_404(tid)
    if main.request.method == 'GET':
        return main.jsonify(t.to_dict())
    user = main.resolve_user()
    if not user:
        return main.jsonify({'error': '未登录'}), 401
    if main.request.method == 'PUT':
        data = main.request.get_json(force=True, silent=True) or {}
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
            t.resource_index.meta = main.json.dumps(m, ensure_ascii=False)
        main.db.session.commit()
        return main.jsonify(t.to_dict())
    main.db.session.delete(t)
    if t.resource_index:
        main.db.session.delete(t.resource_index)
    main.db.session.commit()
    return main.jsonify({'status': 'deleted'})

@bp.route('/api/modes', methods=['GET'])
def available_modes():
    import main
    """返回当前可用模式及数量，供首页 tab 动态渲染。"""
    counts = dict(main.db.session.query(main.ResourceModeMembership.mode, main.db.func.count())
                  .group_by(main.ResourceModeMembership.mode).all())
    dyn_count = main.db.session.query(main.PostRef.resource_index_id).distinct().count()
    modes = []
    for m in main.ResourceMode.SINGLE:
        if counts.get(m):
            modes.append({'mode': m, 'count': counts[m]})
    if dyn_count:
        modes.append({'mode': main.ResourceMode.POST, 'count': dyn_count})
    return main.jsonify({'modes': modes})

@bp.route('/api/resource-index/<int:rid>/repoint', methods=['POST'])
def repoint_resource_index(rid):
    import main
    """重新指向磁盘位置：移动 / 重命名资源只需更新索引表一行，所有引用它的实体自动跟随。"""
    user = main.AuthService.get_current_user()
    if not user or user.role < main.UserRole.ADMIN:
        return main.jsonify({'error': '需要管理员权限'}), 403
    ri = main.ResourceIndex.query.get_or_404(rid)
    data = main.request.get_json(force=True, silent=True) or {}
    new_loc = data.get('location')
    if not new_loc:
        return main.jsonify({'error': '缺少 location'}), 400
    ri.location = new_loc
    ri.updated_at = main.datetime.utcnow()
    main.db.session.commit()
    return main.jsonify(ri.to_dict())

@bp.route('/api/resource-index/<int:rid>/hidden', methods=['PATCH'])
def set_resource_index_hidden(rid):
    import main
    """设置资源是否隐藏：隐藏的资源不出现在视频 / 图集库列表，仅在帖子流可见。

    仅管理员可操作（来自帖子详情点进资源界面后编辑）。
    """
    user_id, role = main.resolve_identity()
    if not user_id or role < main.UserRole.ADMIN:
        return main.jsonify({'error': '需要管理员权限'}), 403
    ri = main.ResourceIndex.query.get_or_404(rid)
    data = main.request.get_json(force=True, silent=True) or {}
    if 'hidden' not in data:
        return main.jsonify({'error': '缺少 hidden 字段'}), 400
    ri.hidden = bool(data['hidden'])
    ri.updated_at = main.datetime.utcnow()
    main.db.session.commit()
    return main.jsonify(ri.to_dict())
