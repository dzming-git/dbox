# -*- coding: utf-8 -*-
"""
漫画模式 API 蓝图

提供漫画的列表 / 详情 / 页面图片服务 / 点赞收藏不喜欢 / 阅读进度 / 后台扫描 等接口。
鉴权与交互身份键逻辑对齐主应用的 video 接口（current_interaction_key：登录用户用 u{user_id}，
游客用 session 中的随机键），使漫画与视频的点赞/收藏数据体系一致。
"""

import os
import random
import threading
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, session, send_file, abort, current_app
from urllib.parse import quote, unquote
from werkzeug.exceptions import HTTPException
from sqlalchemy import text

from core.models import (
    db, Comic, ComicPage, ComicInteraction, ComicProgress, UserRole,
    ResourceLibrary, LibraryPermission, LibraryUserGroupMember,
    ComicTag, ComicPlaylist, ComicPlaylistItem, Tag,
)
from backend.trash import move_to_trash, purge_trash

comic_bp = Blueprint('comic', __name__, url_prefix='')

JWT_SECRET_KEY = 'dplayer-jwt-secret-key-change-in-production-2024'

# 各库的漫画扫描进度（内存态，重启即清空，不影响数据）
_comic_scan_progress = {}


# ============ 鉴权 / 身份辅助 ============
def _resolve_identity():
    """解析登录身份，返回 (user_id, role)。对齐 main.resolve_identity。"""
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        try:
            from authlib.jose import jwt as _jwt
        except Exception:
            _jwt = None
        if _jwt:
            try:
                payload = _jwt.decode(auth[7:], JWT_SECRET_KEY)
                if payload.get('type') == 'access':
                    return payload.get('user_id'), int(payload.get('role', 0))
            except Exception:
                pass
    try:
        from auth_service import AuthService
        user = AuthService.get_current_user()
        if user:
            return user.id, int(user.role)
    except Exception:
        pass
    return None, 0


def current_interaction_key():
    """交互身份键：登录用户 u{id}，游客用 session 随机键（与 video 一致）。"""
    uid, _ = _resolve_identity()
    if uid:
        return f'u{uid}'
    if 'user_session' not in session:
        session['user_session'] = str(random.randint(100000, 999999))
    return session['user_session']


def _is_admin():
    _, role = _resolve_identity()
    return role >= UserRole.ADMIN


def _comic_auth_ok():
    """漫画图片访问鉴权：登录用户（JWT/session）或游客会话均允许；支持 URL ?token=。"""
    uid, _ = _resolve_identity()
    if uid:
        return True
    if 'user_session' in session:
        return True
    token = request.args.get('token')
    if token:
        try:
            from authlib.jose import jwt as _jwt
            _jwt.decode(token, JWT_SECRET_KEY)
            return True
        except Exception:
            pass
    return False


_MIME_MAP = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
    '.webp': 'image/webp', '.gif': 'image/gif', '.bmp': 'image/bmp',
    '.avif': 'image/avif',
}


def _allowed_library_ids():
    """返回当前用户可访问的资源库ID列表（与 main.get_allowed_library_ids 对齐）。

    漫画复用 resource_libraries 表，权限模型与视频一致：
    - 管理员/ROOT：返回全部「激活」资源库ID；
    - 登录普通用户：自身直接权限 + 所属用户组权限 + 通用权限(user_id=None)；
    - 游客：仅通用权限。
    返回永远是 list（可能为空）。调用方据此过滤 Comic.library_id。
    """
    uid, role = _resolve_identity()
    allowed = []
    if role in (UserRole.ADMIN, UserRole.ROOT):
        libs = ResourceLibrary.query.filter_by(is_active=True).all()
        return [lib.id for lib in libs]
    if uid:
        perms = LibraryPermission.query.filter_by(user_id=uid).all()
        for p in perms:
            lib = ResourceLibrary.query.get(p.library_id)
            if lib and getattr(lib, 'is_active', True):
                allowed.append(p.library_id)
        groups = LibraryUserGroupMember.query.filter_by(user_id=uid).all()
        for ugm in groups:
            gperms = LibraryPermission.query.filter_by(group_id=ugm.group_id).all()
            for p in gperms:
                lib = ResourceLibrary.query.get(p.library_id)
                if lib and getattr(lib, 'is_active', True) and p.library_id not in allowed:
                    allowed.append(p.library_id)
    general = LibraryPermission.query.filter_by(user_id=None).all()
    for p in general:
        lib = ResourceLibrary.query.get(p.library_id)
        if lib and getattr(lib, 'is_active', True) and p.library_id not in allowed:
            allowed.append(p.library_id)
    return allowed


def _ensure_tag_path(path, library_id):
    """确保 path 标签及其所有父级标签都存在，返回最末级标签对象（对齐视频打标签）。"""
    parts = [x for x in (path or '').strip('/').split('/') if x]
    parent_id = None
    cur = None
    for i, name in enumerate(parts):
        sub = '/' + '/'.join(parts[:i + 1])
        tag = Tag.query.filter_by(path=sub, library_id=library_id).first()
        if not tag:
            tag = Tag(path=sub, name=name, library_id=library_id, parent_id=parent_id)
            db.session.add(tag)
            db.session.flush()
        parent_id = tag.id
        cur = tag
    return cur


def _image_mimetype(path):
    return _MIME_MAP.get(os.path.splitext(path)[1].lower())


def _comic_url(file_path):
    if not file_path:
        return ''
    return '/comic-page/' + quote(file_path.replace(chr(92), '/'), safe=':/')


def _comic_ver_param(comic):
    """根据漫画 updated_at 生成缓存失效版本号。

    漫画内部图片被替换/重新加载时 updated_at 会刷新，URL 带上 ?v= 后浏览器会重新拉取，
    避免稳定 URL（/comic-page/<path>、/comic-cover/<hash>）被浏览器缓存导致看到旧图。
    """
    ts = comic.updated_at.replace(tzinfo=timezone.utc).timestamp() if comic.updated_at else 0
    return '?v=%d' % int(ts)


def _allowed_image_path(path):
    """校验请求路径确实是某本漫画的页面/封面（防止越权读取任意文件）。

    直接按路径参数化查询，避免每次图片请求都加载全部页面行。
    """
    norm = os.path.normcase(os.path.abspath(path))
    page = ComicPage.query.filter(ComicPage.file_path.isnot(None)).filter(
        db.func.lower(ComicPage.file_path) == norm.lower()).first()
    if page:
        return True
    cover = Comic.query.filter(Comic.cover_path.isnot(None)).filter(
        db.func.lower(Comic.cover_path) == norm.lower()).first()
    return cover is not None


# ============ 列表 / 详情 ============
@comic_bp.route('/api/comics', methods=['GET'])
def list_comics():
    try:
        key = current_interaction_key()
        library_id = request.args.get('library_id', type=int)
        tag_id = request.args.get('tag_id', type=int)
        search = (request.args.get('search') or '').strip()
        sort = request.args.get('sort', 'recommended')
        order = request.args.get('order', 'desc')
        only_favorited = request.args.get('only_favorited') == 'true'
        only_liked = request.args.get('only_liked') == 'true'
        exclude_disliked = request.args.get('exclude_disliked', 'true') == 'true'
        continue_only = request.args.get('continue') == 'true'
        limit = request.args.get('limit', 24, type=int)
        offset = request.args.get('offset', 0, type=int)

        query = Comic.query.filter(Comic.in_trash == False)

        # ============ 资源库权限过滤（与视频 /api/videos 对齐）============
        allowed_libs = _allowed_library_ids()
        if allowed_libs:
            query = query.filter(
                (Comic.library_id == None) |
                (Comic.library_id.in_(allowed_libs))
            )
        else:
            # 无权限用户只能看到主数据库（library_id 为 NULL）的漫画
            query = query.filter(Comic.library_id == None)

        if library_id is not None:
            if _is_admin() or library_id in allowed_libs:
                query = query.filter(Comic.library_id == library_id)
            else:
                # 无权限访问该库，返回空结果
                query = query.filter(Comic.library_id == -1)

        if search:
            query = query.filter(Comic.title.like(f'%{search}%'))

        # 标签筛选（含父子继承：选择父标签时同时显示子标签下的漫画）
        if tag_id:
            tag = Tag.query.get(tag_id)
            if tag:
                child_ids = tag.get_all_child_ids()
                comic_ids = [r[0] for r in db.session.query(ComicTag.comic_id)
                             .filter(ComicTag.tag_id.in_(child_ids)).all()]
                query = query.filter(Comic.id.in_(comic_ids) if comic_ids else Comic.id.in_([-1]))

        disliked_ids = set()
        liked_ids = set()
        favorited_ids = set()
        if key:
            disliked_ids = {r[0] for r in db.session.query(ComicInteraction.comic_id)
                            .filter_by(user_session=key, interaction_type='dislike').all()}
            liked_ids = {r[0] for r in db.session.query(ComicInteraction.comic_id)
                         .filter_by(user_session=key, interaction_type='like').all()}
            favorited_ids = {r[0] for r in db.session.query(ComicInteraction.comic_id)
                             .filter_by(user_session=key, interaction_type='favorite').all()}
            if exclude_disliked and disliked_ids:
                query = query.filter(Comic.id.notin_(disliked_ids))
            if only_liked:
                query = query.filter(Comic.id.in_(liked_ids) if liked_ids else Comic.id.in_([-1]))
            if only_favorited:
                query = query.filter(Comic.id.in_(favorited_ids) if favorited_ids else Comic.id.in_([-1]))
            if continue_only:
                _ensure_comic_progress_in_continue()
                cont_ids = [r[0] for r in db.session.query(ComicProgress.comic_id)
                            .filter_by(user_session=key, in_continue=True).all()]
                query = query.filter(Comic.id.in_(cont_ids) if cont_ids else Comic.id.in_([-1]))

        total = query.count()
        is_desc = order.lower() == 'desc'
        if sort == 'name':
            comics = query.order_by(Comic.title.desc() if is_desc else Comic.title.asc()).offset(offset).limit(limit).all()
        elif sort == 'created_at':
            comics = query.order_by(Comic.created_at.desc() if is_desc else Comic.created_at.asc()).offset(offset).limit(limit).all()
        elif sort == 'page_count':
            comics = query.order_by(Comic.page_count.desc() if is_desc else Comic.page_count.asc()).offset(offset).limit(limit).all()
        elif sort == 'like_count':
            comics = query.order_by(Comic.like_count.desc() if is_desc else Comic.like_count.asc()).offset(offset).limit(limit).all()
        elif sort == 'favorite_count':
            comics = query.order_by(Comic.favorite_count.desc() if is_desc else Comic.favorite_count.asc()).offset(offset).limit(limit).all()
        else:
            from sqlalchemy import func
            comics = query.order_by(
                (Comic.like_count + Comic.favorite_count * 2 + func.random() * 30).desc()
            ).offset(offset).limit(limit).all()

        result = []
        for c in comics:
            d = c.to_dict()
            d['cover_url'] = _comic_url(c.cover_path) + _comic_ver_param(c)
            d['is_liked'] = c.id in liked_ids
            d['is_favorited'] = c.id in favorited_ids
            d['is_disliked'] = c.id in disliked_ids
            pr = ComicProgress.query.filter_by(comic_id=c.id, user_session=key).first() if key else None
            d['last_page'] = pr.page if pr else 0
            d['progress'] = pr.progress if pr else 0.0
            result.append(d)
        return jsonify({'success': True, 'comics': result, 'total': total})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@comic_bp.route('/api/comic/<comic_hash>', methods=['GET'])
def get_comic(comic_hash):
    try:
        c = Comic.query.filter_by(hash=comic_hash).first_or_404()
        # ============ 资源库权限校验（与视频详情 /api/video/<hash> 对齐）============
        if c.library_id:
            _uid, _role = _resolve_identity()
            if _role not in (UserRole.ADMIN, UserRole.ROOT):
                if c.library_id not in _allowed_library_ids():
                    return jsonify({'success': False, 'message': '无权访问该漫画所在的资源库', 'code': 403}), 403
        key = current_interaction_key()
        d = c.to_dict()
        pages = ComicPage.query.filter_by(comic_id=c.id).order_by(ComicPage.page_index).all()
        ver = _comic_ver_param(c)
        d['pages'] = [{'index': p.page_index + 1, 'url': _comic_url(p.file_path) + ver} for p in pages]
        d['cover_url'] = _comic_url(c.cover_path) + ver
        if key:
            d['is_liked'] = ComicInteraction.query.filter_by(
                comic_id=c.id, user_session=key, interaction_type='like').first() is not None
            d['is_favorited'] = ComicInteraction.query.filter_by(
                comic_id=c.id, user_session=key, interaction_type='favorite').first() is not None
            d['is_disliked'] = ComicInteraction.query.filter_by(
                comic_id=c.id, user_session=key, interaction_type='dislike').first() is not None
            pr = ComicProgress.query.filter_by(comic_id=c.id, user_session=key).first()
            d['last_page'] = pr.page if pr else 0
            d['progress'] = pr.progress if pr else 0.0
            d['in_continue'] = bool(pr.in_continue) if pr else False
        else:
            d['is_liked'] = d['is_favorited'] = d['is_disliked'] = False
            d['last_page'] = 0
            d['progress'] = 0.0
            d['in_continue'] = False
        return jsonify({'success': True, 'comic': d})
    except HTTPException:
        raise
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ 点赞 / 收藏 / 不喜欢 ============
@comic_bp.route('/api/comic/<comic_hash>/<itype>', methods=['POST'])
def comic_interact(comic_hash, itype):
    if itype not in ('like', 'favorite', 'dislike'):
        return jsonify({'success': False, 'message': '未知操作'}), 400
    try:
        c = Comic.query.filter_by(hash=comic_hash).first_or_404()
        key = current_interaction_key()
        inter = ComicInteraction.query.filter_by(
            comic_id=c.id, user_session=key, interaction_type=itype).first()
        if inter:
            db.session.delete(inter)
            active = False
        else:
            score = {'like': 2.0, 'favorite': 5.0, 'dislike': -1.0}[itype]
            db.session.add(ComicInteraction(
                comic_id=c.id, user_session=key, interaction_type=itype, interaction_score=score))
            active = True
        if itype == 'like':
            c.like_count = ComicInteraction.query.filter_by(
                comic_id=c.id, interaction_type='like').count()
        elif itype == 'favorite':
            c.favorite_count = ComicInteraction.query.filter_by(
                comic_id=c.id, interaction_type='favorite').count()
        db.session.commit()
        return jsonify({'success': True, 'active': active,
                        'like_count': c.like_count, 'favorite_count': c.favorite_count})
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ 阅读进度 ============
@comic_bp.route('/api/comic/<comic_hash>/progress', methods=['GET', 'POST'])
def comic_progress(comic_hash):
    try:
        c = Comic.query.filter_by(hash=comic_hash).first_or_404()
        key = current_interaction_key()
        if request.method == 'POST':
            _ensure_comic_progress_in_continue()
            data = request.get_json(silent=True) or {}
            page = int(data.get('page', 0) or 0)
            progress = float(data.get('progress', 0.0) or 0.0)
            pr = ComicProgress.query.filter_by(comic_id=c.id, user_session=key).first()
            if pr:
                pr.page = page
                pr.progress = progress
                pr.updated_at = datetime.utcnow()
                if progress >= 1.0:
                    pr.in_continue = False
            else:
                pr = ComicProgress(comic_id=c.id, user_session=key, page=page, progress=progress)
                db.session.add(pr)
            db.session.commit()
            return jsonify({'success': True, 'page': page, 'progress': progress, 'in_continue': bool(pr.in_continue)})
        else:
            pr = ComicProgress.query.filter_by(comic_id=c.id, user_session=key).first() if key else None
            return jsonify({'success': True,
                            'page': pr.page if pr else 0,
                            'progress': pr.progress if pr else 0.0})
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


def _ensure_comic_progress_in_continue():
    """兼容旧库：为 comic_progress 表补充 in_continue 列（显式加入「继续阅读」列表的标志）。"""
    try:
        db.session.execute(text(
            "ALTER TABLE comic_progress ADD COLUMN in_continue BOOLEAN NOT NULL DEFAULT 0"
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


@comic_bp.route('/api/comic/<comic_hash>/continue', methods=['POST'])
def set_comic_continue(comic_hash):
    """显式加入 / 移出「继续阅读」列表（由用户主动选择，而非打开即加入）。"""
    try:
        c = Comic.query.filter_by(hash=comic_hash).first_or_404()
        data = request.get_json(silent=True) or {}
        add = bool(data.get('add', False))
        key = current_interaction_key()
        if not key:
            return jsonify({'success': False, 'message': '请先登录'}), 401
        _ensure_comic_progress_in_continue()
        pr = ComicProgress.query.filter_by(comic_id=c.id, user_session=key).first()
        if not pr:
            pr = ComicProgress(comic_id=c.id, user_session=key, page=0, progress=0.0)
        pr.in_continue = add
        db.session.add(pr)
        db.session.commit()
        return jsonify({'success': True, 'in_continue': bool(pr.in_continue)})
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ 我的漫画（收藏 / 点赞 / 不喜欢 / 历史）列表 ============
# 与 main.py 的 /api/favorites|likes|disliked 对齐，使漫画与视频地位等同，
# 可被「我的收藏 / 点赞 / 不喜欢 / 历史」统一合并展示。
def _comic_interaction_rows(key, itype, date_field):
    """返回某用户某类型交互对应的漫画列表（带交互时间）。"""
    rows = ComicInteraction.query.filter_by(
        user_session=key, interaction_type=itype
    ).order_by(ComicInteraction.created_at.desc()).all()
    items = []
    for row in rows:
        c = Comic.query.get(row.comic_id)
        if not c or c.in_trash:
            continue
        d = c.to_dict()
        d['cover_url'] = _comic_url(c.cover_path)
        d[date_field] = row.created_at.isoformat() if row.created_at else None
        items.append(d)
    return items


@comic_bp.route('/api/comics/favorites', methods=['GET'])
def list_comic_favorites():
    try:
        key = current_interaction_key()
        comics = _comic_interaction_rows(key, 'favorite', 'favorited_at') if key else []
        return jsonify({'success': True, 'comics': comics, 'total': len(comics)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@comic_bp.route('/api/comics/likes', methods=['GET'])
def list_comic_likes():
    try:
        key = current_interaction_key()
        comics = _comic_interaction_rows(key, 'like', 'liked_at') if key else []
        return jsonify({'success': True, 'comics': comics, 'total': len(comics)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@comic_bp.route('/api/comics/disliked', methods=['GET'])
def list_comic_disliked():
    try:
        key = current_interaction_key()
        comics = _comic_interaction_rows(key, 'dislike', 'disliked_at') if key else []
        return jsonify({'success': True, 'comics': comics, 'total': len(comics)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@comic_bp.route('/api/comics/history', methods=['GET'])
def list_comic_history():
    """已阅读过（progress>0）的漫画，按最近阅读时间倒序。"""
    try:
        key = current_interaction_key()
        if not key:
            return jsonify({'success': True, 'comics': [], 'total': 0})
        rows = ComicProgress.query.filter(
            ComicProgress.user_session == key,
            ComicProgress.progress > 0
        ).order_by(ComicProgress.updated_at.desc()).all()
        items = []
        for row in rows:
            c = Comic.query.get(row.comic_id)
            if not c:
                continue
            d = c.to_dict()
            d['cover_url'] = _comic_url(c.cover_path) + _comic_ver_param(c)
            d['page'] = row.page
            d['last_page'] = row.page
            d['progress'] = row.progress
            d['page_count'] = c.page_count
            d['updated_at'] = row.updated_at.isoformat() if row.updated_at else None
            items.append(d)
        return jsonify({'success': True, 'comics': items, 'total': len(items)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ 漫画页面图片服务 ============
@comic_bp.route('/comic-page/<path:page_path>', methods=['GET'])
def serve_comic_page(page_path):
    try:
        page_path = unquote(page_path)
        while '//' in page_path:
            page_path = page_path.replace('//', '/')
        page_path = page_path.replace('/', os.sep)
        if not _comic_auth_ok():
            abort(401)
        if not _allowed_image_path(page_path):
            abort(403)
        if not os.path.isfile(page_path):
            abort(404)
        return send_file(page_path, mimetype=_image_mimetype(page_path))
    except HTTPException:
        raise
    except Exception:
        abort(500)


@comic_bp.route('/comic-cover/<comic_hash>', methods=['GET'])
def serve_comic_cover(comic_hash):
    try:
        c = Comic.query.filter_by(hash=comic_hash).first_or_404()
        if not _comic_auth_ok():
            abort(401)
        if not c.cover_path or not os.path.isfile(c.cover_path):
            abort(404)
        return send_file(c.cover_path, mimetype=_image_mimetype(c.cover_path))
    except HTTPException:
        raise
    except Exception:
        abort(500)


# ============ 后台扫描（管理员） ============
@comic_bp.route('/api/admin/libraries/<int:library_id>/scan-comics', methods=['POST'])
def admin_scan_comics(library_id):
    if not _is_admin():
        return jsonify({'success': False, 'message': '需要管理员权限', 'code': 403}), 403
    try:
        app = current_app._get_current_object()

        def _run():
            _comic_scan_progress[library_id] = {
                'status': 'scanning', 'added': 0, 'updated': 0,
                'removed': 0, 'total': 0, 'message': '扫描中...'
            }
            try:
                from backend.comic.scanner import scan_library_comics
                res = scan_library_comics(library_id, app)
                _comic_scan_progress[library_id] = {
                    'status': 'done',
                    'added': res.get('added', 0),
                    'updated': res.get('updated', 0),
                    'removed': res.get('removed', 0),
                    'total': res.get('total', 0),
                    'message': '扫描完成',
                }
            except Exception as e:
                _comic_scan_progress[library_id] = {
                    'status': 'error', 'message': str(e)
                }

        threading.Thread(target=_run, daemon=True).start()
        return jsonify({'success': True, 'started': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@comic_bp.route('/api/admin/libraries/<int:library_id>/comic-scan-status', methods=['GET'])
def admin_comic_scan_status(library_id):
    return jsonify({'success': True,
                    'status': _comic_scan_progress.get(library_id, {'status': 'idle'})})





# ============ 漫画标签（复用 tags 表，对齐视频标签体系）============
@comic_bp.route('/api/comics/tags', methods=['GET'])
def list_comic_tags():
    """返回标签树（或扁平列表）及每个标签下的漫画数，对齐视频 /api/tags。"""
    try:
        tree = request.args.get('tree') == 'true'
        library_id = request.args.get('library_id', type=int)
        allowed_libs = _allowed_library_ids()
        allowed_comic_ids = set()
        if allowed_libs:
            for cid in db.session.query(Comic.id).filter(
                (Comic.library_id == None) | (Comic.library_id.in_(allowed_libs))).all():
                allowed_comic_ids.add(cid[0])
        else:
            for cid in db.session.query(Comic.id).filter(Comic.library_id == None).all():
                allowed_comic_ids.add(cid[0])

        rows = db.session.query(ComicTag.tag_id, ComicTag.comic_id).all()
        tag_comic = {}
        for tid, cid in rows:
            if cid in allowed_comic_ids:
                tag_comic.setdefault(tid, set()).add(cid)

        q = Tag.query
        if library_id is not None:
            q = q.filter((Tag.library_id == None) | (Tag.library_id == library_id))
        tags = q.all()

        def count_for(tag):
            ids = set(tag.get_all_child_ids())
            cset = set()
            for t in ids:
                if t in tag_comic:
                    cset |= tag_comic[t]
            return len(cset)

        result = []
        for t in tags:
            result.append({
                'id': t.id, 'name': t.name, 'qualifiers': t.get_qualifiers(), 'path': t.path,
                'category': t.category, 'parent_id': t.parent_id,
                'library_id': t.library_id, 'comic_count': count_for(t)
            })
        if tree:
            by_id = {t['id']: t for t in result}
            for t in result:
                t['children'] = []
            roots = []
            for t in result:
                if t['parent_id'] and t['parent_id'] in by_id:
                    by_id[t['parent_id']]['children'].append(t)
                else:
                    roots.append(t)
            return jsonify({'success': True, 'tags': roots})
        return jsonify({'success': True, 'tags': result})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@comic_bp.route('/api/comic/<comic_hash>/tags', methods=['GET'])
def get_comic_tags(comic_hash):
    try:
        c = Comic.query.filter_by(hash=comic_hash).first_or_404()
        tag_ids = [r[0] for r in db.session.query(ComicTag.tag_id).filter_by(comic_id=c.id).all()]
        tags = Tag.query.filter(Tag.id.in_(tag_ids)).all() if tag_ids else []
        return jsonify({'success': True, 'tags': [{'id': t.id, 'name': t.name, 'qualifiers': t.get_qualifiers(), 'path': t.path, 'library_id': t.library_id} for t in tags]})
    except HTTPException:
        raise
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@comic_bp.route('/api/comic/<comic_hash>/tags', methods=['POST'])
def set_comic_tags(comic_hash):
    """以传入的标签路径列表整体替换该漫画的标签（对齐视频打标签）。"""
    try:
        c = Comic.query.filter_by(hash=comic_hash).first_or_404()
        data = request.get_json(silent=True) or {}
        tag_paths = data.get('tags', [])
        ComicTag.query.filter_by(comic_id=c.id).delete()
        lib_id = c.library_id
        for tp in tag_paths:
            tp = (tp or '').strip()
            if not tp:
                continue
            path = tp if tp.startswith('/') else '/' + tp
            tag = _ensure_tag_path(path, lib_id)
            db.session.add(ComicTag(comic_id=c.id, tag_id=tag.id))
        db.session.commit()
        return jsonify({'success': True})
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@comic_bp.route('/api/comic/<comic_hash>/update', methods=['POST'])
def update_comic_info(comic_hash):
    """更新漫画信息（标题、所属资源库）"""
    try:
        c = Comic.query.filter_by(hash=comic_hash).first_or_404()
        # 资源所属权校验：仅本人或管理员/ROOT 可编辑
        uid, role = _resolve_identity()
        if not _is_admin() and c.owner_id not in (None, uid):
            return jsonify({'success': False, 'message': '无权编辑该资源（仅上传者或管理员可操作）', 'code': 403}), 403
        data = request.get_json(silent=True) or {}
        if 'title' in data and data['title'] is not None:
            c.title = data['title'].strip()
        if 'library_id' in data:
            library_id = data['library_id']
            if library_id is not None:
                library = ResourceLibrary.query.get(int(library_id))
                if not library:
                    return jsonify({'success': False, 'message': '资源库不存在'}), 400
            c.library_id = library_id
        db.session.commit()
        return jsonify({'success': True, 'comic': c.to_dict()})
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@comic_bp.route('/api/comic/<comic_hash>/tags', methods=['DELETE'])
def delete_comic_tags(comic_hash):
    try:
        c = Comic.query.filter_by(hash=comic_hash).first_or_404()
        # 资源所属权校验：仅本人或管理员/ROOT 可编辑
        uid, role = _resolve_identity()
        if not _is_admin() and c.owner_id not in (None, uid):
            return jsonify({'success': False, 'message': '无权编辑该资源（仅上传者或管理员可操作）', 'code': 403}), 403
        data = request.get_json(silent=True) or {}
        tag_id = data.get('tag_id')
        if tag_id:
            ComicTag.query.filter_by(comic_id=c.id, tag_id=tag_id).delete()
        else:
            ComicTag.query.filter_by(comic_id=c.id).delete()
        db.session.commit()
        return jsonify({'success': True})
    except HTTPException:
        raise
    except Exception as er2:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(er2)}), 500


# ============ 漫画合集（播放列表，对齐视频 Playlist）============
@comic_bp.route('/api/comic-playlists', methods=['GET'])
def list_comic_playlists():
    try:
        key = current_interaction_key()
        pls = ComicPlaylist.query.filter(
            (ComicPlaylist.user_session == key) | (ComicPlaylist.is_public == True)
        ).order_by(ComicPlaylist.updated_at.desc()).all()
        return jsonify({'success': True, 'playlists': [p.to_dict() for p in pls]})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@comic_bp.route('/api/comic-playlists', methods=['POST'])
def create_comic_playlist():
    try:
        key = current_interaction_key()
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'success': False, 'message': '名称不能为空'}), 400
        pl = ComicPlaylist(
            name=name,
            description=data.get('description', ''),
            user_session=key,
            is_public=bool(data.get('is_public', False)),
        )
        db.session.add(pl)
        db.session.commit()
        return jsonify({'success': True, 'playlist': pl.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@comic_bp.route('/api/comic-playlists/<int:pid>', methods=['GET'])
def get_comic_playlist(pid):
    try:
        pl = ComicPlaylist.query.get_or_404(pid)
        key = current_interaction_key()
        if pl.user_session != key and not pl.is_public:
            return jsonify({'success': False, 'message': '无权访问', 'code': 403}), 403
        return jsonify({'success': True, 'playlist': pl.to_dict()})
    except HTTPException:
        raise
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@comic_bp.route('/api/comic/<comic_hash>', methods=['DELETE'])
def delete_comic(comic_hash):
    """删除漫画：默认移入回收站；管理员可传 delete_file/permanent 永久删除。"""
    try:
        body = request.get_json(silent=True) or {}
        permanent = bool(body.get('delete_file', False) or body.get('permanent', False))
        c = Comic.query.filter_by(hash=comic_hash).first_or_404()

        uid, urole = _resolve_identity()
        if urole not in (UserRole.ADMIN, UserRole.ROOT) and c.owner_id not in (None, uid):
            return jsonify({'success': False, 'message': '无权删除该漫画（仅上传者或管理员可操作）', 'code': 403}), 403

        if permanent:
            if urole not in (UserRole.ADMIN, UserRole.ROOT):
                return jsonify({'success': False, 'message': '仅管理员可永久删除', 'code': 403}), 403
            purge_trash(c, 'comic')
            log.maintenance('INFO', f"永久删除漫画: {c.title} (hash: {comic_hash})")
            return jsonify({'success': True, 'message': '漫画已永久删除'})
        else:
            move_to_trash(c, 'comic')
            log.maintenance('INFO', f"漫画移入回收站: {c.title} (hash: {comic_hash})")
            return jsonify({'success': True, 'message': '已移入回收站'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@comic_bp.route('/api/comic/<comic_hash>/reload', methods=['POST'])
def reload_comic(comic_hash):
    """重新加载漫画资源：从磁盘重新读取文件夹、同步页面与封面，并刷新 updated_at。

    用于漫画内部图片被替换 / 增删后，强制更新而不必等整库扫描或重启。
    仅上传者或管理员/ROOT 可操作（对齐删除/编辑权限）。
    """
    try:
        c = Comic.query.filter_by(hash=comic_hash).first_or_404()
        uid, urole = _resolve_identity()
        if urole not in (UserRole.ADMIN, UserRole.ROOT) and c.owner_id not in (None, uid):
            return jsonify({'success': False, 'message': '无权重新加载该漫画（仅上传者或管理员可操作）', 'code': 403}), 403

        folder = c.folder_path
        if not folder or not os.path.isdir(folder):
            return jsonify({'success': False, 'message': '漫画文件夹不存在或已被移动', 'code': 404}), 404

        from backend.comic.scanner import _list_images, _sync_pages
        pages = _list_images(folder)
        if not pages:
            return jsonify({'success': False, 'message': '文件夹内未找到图片', 'code': 400}), 400

        _sync_pages(c, pages)
        c.cover_path = pages[0]
        c.page_count = len(pages)
        c.updated_at = datetime.utcnow()
        db.session.commit()

        log.maintenance('INFO', f"重新加载漫画资源: {c.title} (hash: {comic_hash}), 页数={len(pages)}")
        return jsonify({
            'success': True,
            'comic': c.to_dict(),
            'page_count': len(pages),
            'message': '漫画资源已重新加载'
        })
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@comic_bp.route('/api/comic-playlists/<int:pid>', methods=['PUT'])
def update_comic_playlist(pid):
    try:
        pl = ComicPlaylist.query.get_or_404(pid)
        key = current_interaction_key()
        if pl.user_session != key:
            return jsonify({'success': False, 'message': '无权修改', 'code': 403}), 403
        data = request.get_json(silent=True) or {}
        if 'name' in data:
            pl.name = data['name']
        if 'description' in data:
            pl.description = data['description']
        if 'is_public' in data:
            pl.is_public = bool(data['is_public'])
        pl.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True, 'playlist': pl.to_dict()})
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@comic_bp.route('/api/comic-playlists/<int:pid>', methods=['DELETE'])
def delete_comic_playlist(pid):
    try:
        pl = ComicPlaylist.query.get_or_404(pid)
        key = current_interaction_key()
        if pl.user_session != key:
            return jsonify({'success': False, 'message': '无权删除', 'code': 403}), 403
        db.session.delete(pl)
        db.session.commit()
        return jsonify({'success': True})
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@comic_bp.route('/api/comic-playlists/<int:pid>/comics', methods=['POST'])
def add_comic_to_playlist(pid):
    try:
        pl = ComicPlaylist.query.get_or_404(pid)
        key = current_interaction_key()
        if pl.user_session != key:
            return jsonify({'success': False, 'message': '无权修改', 'code': 403}), 403
        data = request.get_json(silent=True) or {}
        comic_hash = data.get('hash')
        if not comic_hash:
            return jsonify({'success': False, 'message': '缺少漫画 hash'}), 400
        c = Comic.query.filter_by(hash=comic_hash).first()
        if not c:
            return jsonify({'success': False, 'message': '漫画不存在'}), 404
        if ComicPlaylistItem.query.filter_by(playlist_id=pid, comic_id=c.id).first():
            return jsonify({'success': False, 'message': '已在合集中'}), 409
        pos = db.session.query(db.func.max(ComicPlaylistItem.position)).filter_by(playlist_id=pid).scalar() or 0
        item = ComicPlaylistItem(playlist_id=pid, comic_id=c.id, position=pos + 1)
        db.session.add(item)
        pl.update_comic_count()
        pl.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True, 'item': item.to_dict(), 'comic_count': pl.comic_count})
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@comic_bp.route('/api/comic-playlists/<int:pid>/comics/<comic_hash>', methods=['DELETE'])
def remove_comic_from_playlist(pid, comic_hash):
    try:
        pl = ComicPlaylist.query.get_or_404(pid)
        key = current_interaction_key()
        if pl.user_session != key:
            return jsonify({'success': False, 'message': '无权修改', 'code': 403}), 403
        c = Comic.query.filter_by(hash=comic_hash).first()
        if not c:
            return jsonify({'success': False, 'message': '漫画不存在'}), 404
        item = ComicPlaylistItem.query.filter_by(playlist_id=pid, comic_id=c.id).first()
        if item:
            db.session.delete(item)
            pl.update_comic_count()
            pl.updated_at = datetime.utcnow()
            db.session.commit()
        return jsonify({'success': True, 'comic_count': pl.comic_count})
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@comic_bp.route('/api/comic-playlists/<int:pid>/comics/reorder', methods=['PUT'])
def reorder_comic_playlist(pid):
    try:
        pl = ComicPlaylist.query.get_or_404(pid)
        key = current_interaction_key()
        if pl.user_session != key:
            return jsonify({'success': False, 'message': '无权修改', 'code': 403}), 403
        data = request.get_json(silent=True) or {}
        order = data.get('order', [])
        pos = 1
        for h in order:
            c = Comic.query.filter_by(hash=h).first()
            if not c:
                continue
            item = ComicPlaylistItem.query.filter_by(playlist_id=pid, comic_id=c.id).first()
            if item:
                item.position = pos
                pos += 1
        db.session.commit()
        return jsonify({'success': True, 'playlist': pl.to_dict()})
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500



