# -*- coding: utf-8 -*-
"""
图集模式 API 蓝图

提供图集的列表 / 详情 / 页面图片服务 / 点赞收藏不喜欢 / 阅读进度 / 后台扫描 等接口。
鉴权与交互身份键逻辑对齐主应用的 video 接口（current_interaction_key：登录用户用 u{user_id}，
游客用 session 中的随机键），使图集与视频的点赞/收藏数据体系一致。
"""

import os
import random
import threading
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, session, send_file, abort, current_app
from urllib.parse import quote, unquote
from werkzeug.exceptions import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from core.models import (
    db, Gallery, GalleryPage, GalleryInteraction, GalleryProgress, UserRole, ResourceIndex,
    ResourceLibrary, LibraryPermission, LibraryUserGroupMember,
    GalleryTag, GalleryPlaylist, GalleryPlaylistItem, Tag,
)
from backend.trash import move_to_trash, purge_trash
from backend.access import (
    get_allowed_library_ids, guard_location, guard_resource_index,
    is_gallery_visible, deny_missing,
)
from liblog import get_service_logger
log = get_service_logger('dbox-web')

gallery_bp = Blueprint('gallery', __name__, url_prefix='')

JWT_SECRET_KEY = 'dbox-jwt-secret-key-change-in-production-2024'

# 各库的图集扫描进度（内存态，重启即清空，不影响数据）
_gallery_scan_progress = {}


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
                    return payload.get('user_id'), int(payload.get('role', UserRole.GUEST))
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
    return role <= UserRole.ADMIN


def _gallery_auth_ok():
    """图集图片访问鉴权：登录用户（JWT/session）或游客会话均允许；支持 URL ?token=。"""
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
    """返回当前用户可访问的资源库ID列表。

    统一委托给 backend.access 的唯一实现，避免图集侧维护第二份权限口径
    （两份实现一旦漂移就会形成绕过通道）。保留本函数名仅为兼容既有调用点。
    """
    return get_allowed_library_ids()


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


def _gallery_url(file_path):
    if not file_path:
        return ''
    return '/gallery-page/' + quote(file_path.replace(chr(92), '/'), safe=':/')


def _gallery_ver_param(gallery):
    """根据图集 updated_at 生成缓存失效版本号。

    图集内部图片被替换/重新加载时 updated_at 会刷新，URL 带上 ?v= 后浏览器会重新拉取，
    避免稳定 URL（/gallery-page/<path>、/gallery-cover/<hash>）被浏览器缓存导致看到旧图。
    """
    ts = gallery.updated_at.replace(tzinfo=timezone.utc).timestamp() if gallery.updated_at else 0
    return '?v=%d' % int(ts)


def _allowed_image_path(path):
    """校验请求路径确实是某本图集的页面/封面（防止越权读取任意文件）。

    直接按路径参数化查询，避免每次图片请求都加载全部页面行。
    """
    norm = os.path.normcase(os.path.abspath(path))
    page = GalleryPage.query.filter(GalleryPage.file_path.isnot(None)).filter(
        db.func.lower(GalleryPage.file_path) == norm.lower()).first()
    if page:
        return True
    cover = Gallery.query.join(GalleryPage).filter(
        db.func.lower(GalleryPage.file_path) == norm.lower()).first()
    return cover is not None


# ============ 列表 / 详情 ============
@gallery_bp.route('/api/galleries', methods=['GET'])
def list_galleries():
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

        query = Gallery.query.filter(Gallery.in_trash == False).options(
            joinedload(Gallery.resource_index), joinedload(Gallery.pages))

        # 过滤被隐藏的资源（hidden=True 仅在帖子流可见，不出现在图集库列表）
        query = query.filter(
            ~Gallery.resource_index.has(ResourceIndex.hidden == True)
        )

        # ============ 资源库可见性（统一收敛点，与视频 /api/videos 对齐）============
        # 仅激活库 + 未删除 + 未隐藏的图集对外可见；取消所有库激活后返回空。
        # 主库（library_id 为 NULL）已通过 migrate_main_library 归入「主资源库」，
        # 因此不再有 NULL 例外。
        allowed_libs = _allowed_library_ids()
        if allowed_libs:
            query = query.filter(Gallery.library_id.in_(allowed_libs))
        else:
            # 无可见库时强制返回空（避免 NULL/全量越权泄露）
            query = query.filter(Gallery.library_id == -1)

        if library_id is not None:
            if library_id in allowed_libs:
                query = query.filter(Gallery.library_id == library_id)
            else:
                # 无权限访问该库（含未激活库），返回空结果，外界感知不到其存在
                query = query.filter(Gallery.library_id == -1)

        if search:
            query = query.filter(Gallery.title.like(f'%{search}%'))

        # 标签筛选（含父子继承：选择父标签时同时显示子标签下的图集）
        if tag_id:
            tag = Tag.query.get(tag_id)
            if tag:
                child_ids = tag.get_all_child_ids()
                gallery_ids = [r[0] for r in db.session.query(GalleryTag.gallery_id)
                             .filter(GalleryTag.tag_id.in_(child_ids)).all()]
                query = query.filter(Gallery.id.in_(gallery_ids) if gallery_ids else Gallery.id.in_([-1]))

        disliked_ids = set()
        liked_ids = set()
        favorited_ids = set()
        if key:
            disliked_ids = {r[0] for r in db.session.query(GalleryInteraction.gallery_id)
                            .filter_by(user_session=key, interaction_type='dislike').all()}
            liked_ids = {r[0] for r in db.session.query(GalleryInteraction.gallery_id)
                         .filter_by(user_session=key, interaction_type='like').all()}
            favorited_ids = {r[0] for r in db.session.query(GalleryInteraction.gallery_id)
                             .filter_by(user_session=key, interaction_type='favorite').all()}
            if exclude_disliked and disliked_ids:
                query = query.filter(Gallery.id.notin_(disliked_ids))
            if only_liked:
                query = query.filter(Gallery.id.in_(liked_ids) if liked_ids else Gallery.id.in_([-1]))
            if only_favorited:
                query = query.filter(Gallery.id.in_(favorited_ids) if favorited_ids else Gallery.id.in_([-1]))
            if continue_only:
                _ensure_gallery_progress_in_continue()
                cont_ids = [r[0] for r in db.session.query(GalleryProgress.gallery_id)
                            .filter_by(user_session=key, in_continue=True).all()]
                query = query.filter(Gallery.id.in_(cont_ids) if cont_ids else Gallery.id.in_([-1]))

        total = query.count()
        is_desc = order.lower() == 'desc'
        if sort == 'name':
            galleries = query.order_by(Gallery.title.desc() if is_desc else Gallery.title.asc()).offset(offset).limit(limit).all()
        elif sort == 'created_at':
            galleries = query.order_by(Gallery.created_at.desc() if is_desc else Gallery.created_at.asc()).offset(offset).limit(limit).all()
        elif sort == 'page_count':
            galleries = query.order_by(Gallery.page_count.desc() if is_desc else Gallery.page_count.asc()).offset(offset).limit(limit).all()
        elif sort == 'like_count':
            galleries = query.order_by(Gallery.like_count.desc() if is_desc else Gallery.like_count.asc()).offset(offset).limit(limit).all()
        elif sort == 'favorite_count':
            galleries = query.order_by(Gallery.favorite_count.desc() if is_desc else Gallery.favorite_count.asc()).offset(offset).limit(limit).all()
        else:
            from sqlalchemy import func
            galleries = query.order_by(
                (Gallery.like_count + Gallery.favorite_count * 2 + func.random() * 30).desc()
            ).offset(offset).limit(limit).all()

        result = []
        for c in galleries:
            d = c.to_dict()
            # 统一封面入口：封面来自资源索引（缺失时由模型兜底为第一页封面路由）
            d['cover_url'] = (c.cover_url or _gallery_url(c.cover_path)) + _gallery_ver_param(c)
            d['is_liked'] = c.id in liked_ids
            d['is_favorited'] = c.id in favorited_ids
            d['is_disliked'] = c.id in disliked_ids
            pr = GalleryProgress.query.filter_by(gallery_id=c.id, user_session=key).first() if key else None
            d['last_page'] = pr.page if pr else 0
            d['progress'] = pr.progress if pr else 0.0
            result.append(d)
        return jsonify({'success': True, 'galleries': result, 'total': total})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@gallery_bp.route('/api/gallery/<gallery_hash>', methods=['GET'])
def get_gallery(gallery_hash):
    try:
        c = Gallery.query.filter_by(hash=gallery_hash).first()
        # ============ 资源库权限校验（与视频详情 /api/video/<hash> 对齐）============
        # 资源库未激活 / 无权访问时，外界完全感知不到该图集存在（含详情页、名称、页面）
        # 注意：图集链接属于「资源对外访问」通道，即使是管理员也不允许在详情页泄露名称；
        # 未激活资源库的可见性例外仅限于后台资源库管理界面，不扩展到图集详情页。
        if not is_gallery_visible(c):
            return deny_missing()
        key = current_interaction_key()
        d = c.to_dict()
        pages = GalleryPage.query.filter_by(gallery_id=c.id).order_by(GalleryPage.page_index).all()
        ver = _gallery_ver_param(c)
        # resource_id 供前端使用 /resource-file/<rid>/<idx> 加载页面图片，规避含方括号
        # 等特殊字符的磁盘路径在 URL 路由中 404 的问题（/gallery-page/<path> 仍保留兼容）。
        d['resource_id'] = c.resource_index_id
        d['pages'] = [{'index': p.page_index + 1,
                       'resource_id': c.resource_index_id,
                       'url': _gallery_url(p.file_path) + ver} for p in pages]
        # 总页数以实际页面记录为准：galleries.page_count 是冗余列，目录变动而未重扫时会偏大，
        # 前端据此会以为末页之后还有图片，滚到底多出一张必然加载失败的空页。
        if pages:
            d['page_count'] = len(pages)
        d['cover_url'] = (c.cover_url or _gallery_url(c.cover_path)) + ver
        if key:
            d['is_liked'] = GalleryInteraction.query.filter_by(
                gallery_id=c.id, user_session=key, interaction_type='like').first() is not None
            d['is_favorited'] = GalleryInteraction.query.filter_by(
                gallery_id=c.id, user_session=key, interaction_type='favorite').first() is not None
            d['is_disliked'] = GalleryInteraction.query.filter_by(
                gallery_id=c.id, user_session=key, interaction_type='dislike').first() is not None
            pr = GalleryProgress.query.filter_by(gallery_id=c.id, user_session=key).first()
            d['last_page'] = pr.page if pr else 0
            d['progress'] = pr.progress if pr else 0.0
            d['in_continue'] = bool(pr.in_continue) if pr else False
        else:
            d['is_liked'] = d['is_favorited'] = d['is_disliked'] = False
            d['last_page'] = 0
            d['progress'] = 0.0
            d['in_continue'] = False
        return jsonify({'success': True, 'gallery': d})
    except HTTPException:
        raise
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ 点赞 / 收藏 / 不喜欢 ============
@gallery_bp.route('/api/gallery/<gallery_hash>/<itype>', methods=['POST'])
def gallery_interact(gallery_hash, itype):
    if itype not in ('like', 'favorite', 'dislike'):
        return jsonify({'success': False, 'message': '未知操作'}), 400
    try:
        c = Gallery.query.filter_by(hash=gallery_hash).first_or_404()
        key = current_interaction_key()
        # 关闭自动 flush，避免存在性查询触发未决 INSERT 造成唯一约束误报
        with db.session.no_autoflush:
            inter = GalleryInteraction.query.filter_by(
                gallery_id=c.id, user_session=key, interaction_type=itype).first()
        if inter:
            db.session.delete(inter)
            active = False
        else:
            score = {'like': 2.0, 'favorite': 5.0, 'dislike': -1.0}[itype]
            db.session.add(GalleryInteraction(
                gallery_id=c.id, user_session=key, interaction_type=itype, interaction_score=score))
            active = True
        if itype == 'like':
            c.like_count = GalleryInteraction.query.filter_by(
                gallery_id=c.id, interaction_type='like').count()
        elif itype == 'favorite':
            c.favorite_count = GalleryInteraction.query.filter_by(
                gallery_id=c.id, interaction_type='favorite').count()
        db.session.commit()
        return jsonify({'success': True, 'active': active,
                        'like_count': c.like_count, 'favorite_count': c.favorite_count})
    except IntegrityError:
        # 并发或历史脏数据导致唯一约束冲突：已存在则视为「取消」（toggle off）
        db.session.rollback()
        c = Gallery.query.filter_by(hash=gallery_hash).first_or_404()
        key = current_interaction_key()
        with db.session.no_autoflush:
            existing = GalleryInteraction.query.filter_by(
                gallery_id=c.id, user_session=key, interaction_type=itype).first()
        if existing:
            db.session.delete(existing)
            active = False
        else:
            active = True
        db.session.commit()
        return jsonify({'success': True, 'active': active,
                        'like_count': c.like_count, 'favorite_count': c.favorite_count})
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ 阅读进度 ============
@gallery_bp.route('/api/gallery/<gallery_hash>/progress', methods=['GET', 'POST'])
def gallery_progress(gallery_hash):
    try:
        c = Gallery.query.filter_by(hash=gallery_hash).first_or_404()
        key = current_interaction_key()
        if request.method == 'POST':
            _ensure_gallery_progress_in_continue()
            data = request.get_json(silent=True) or {}
            page = int(data.get('page', 0) or 0)
            progress = float(data.get('progress', 0.0) or 0.0)
            pr = GalleryProgress.query.filter_by(gallery_id=c.id, user_session=key).first()
            if pr:
                pr.page = page
                pr.progress = progress
                pr.updated_at = datetime.utcnow()
                if progress >= 1.0:
                    pr.in_continue = False
            else:
                pr = GalleryProgress(gallery_id=c.id, user_session=key, page=page, progress=progress)
                db.session.add(pr)
            db.session.commit()
            return jsonify({'success': True, 'page': page, 'progress': progress, 'in_continue': bool(pr.in_continue)})
        else:
            pr = GalleryProgress.query.filter_by(gallery_id=c.id, user_session=key).first() if key else None
            return jsonify({'success': True,
                            'page': pr.page if pr else 0,
                            'progress': pr.progress if pr else 0.0})
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


def _ensure_gallery_progress_in_continue():
    """兼容旧库：为 gallery_progress 表补充 in_continue 列（显式加入「继续阅读」列表的标志）。"""
    try:
        db.session.execute(text(
            "ALTER TABLE gallery_progress ADD COLUMN in_continue BOOLEAN NOT NULL DEFAULT 0"
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


@gallery_bp.route('/api/gallery/<gallery_hash>/continue', methods=['POST'])
def set_gallery_continue(gallery_hash):
    """显式加入 / 移出「继续阅读」列表（由用户主动选择，而非打开即加入）。"""
    try:
        c = Gallery.query.filter_by(hash=gallery_hash).first_or_404()
        data = request.get_json(silent=True) or {}
        add = bool(data.get('add', False))
        key = current_interaction_key()
        if not key:
            return jsonify({'success': False, 'message': '请先登录'}), 401
        _ensure_gallery_progress_in_continue()
        pr = GalleryProgress.query.filter_by(gallery_id=c.id, user_session=key).first()
        if not pr:
            pr = GalleryProgress(gallery_id=c.id, user_session=key, page=0, progress=0.0)
        pr.in_continue = add
        db.session.add(pr)
        db.session.commit()
        return jsonify({'success': True, 'in_continue': bool(pr.in_continue)})
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ 我的图集（收藏 / 点赞 / 不喜欢 / 历史）列表 ============
# 与 main.py 的 /api/favorites|likes|disliked 对齐，使图集与视频地位等同，
# 可被「我的收藏 / 点赞 / 不喜欢 / 历史」统一合并展示。
def _gallery_interaction_rows(key, itype, date_field, with_size=False):
    """返回某用户某类型交互对应的图集列表（带交互时间）。
    with_size=True 时，对管理员额外计算文件夹总大小（磁盘遍历）。

    收藏/点赞/不喜欢均须经资源库可见性收敛：所属库取消激活后不再对外输出。
    """
    include_size = False
    if with_size:
        try:
            _, urole = _resolve_identity()
            include_size = urole in (UserRole.ADMIN, UserRole.ROOT)
        except Exception:
            include_size = False
    rows = GalleryInteraction.query.filter_by(
        user_session=key, interaction_type=itype
    ).order_by(GalleryInteraction.created_at.desc()).all()
    allowed_libs = set(_allowed_library_ids())
    items = []
    for row in rows:
        c = Gallery.query.get(row.gallery_id)
        if not c or c.in_trash:
            continue
        if c.library_id not in allowed_libs:
            continue
        d = c.to_dict()
        d['cover_url'] = c.cover_url or _gallery_url(c.cover_path)
        d[date_field] = row.created_at.isoformat() if row.created_at else None
        if include_size and c.folder_path and os.path.isdir(c.folder_path):
            try:
                total = 0
                for entry in os.scandir(c.folder_path):
                    if entry.is_file():
                        total += entry.stat().st_size
                d['size'] = total
            except Exception:
                pass
        items.append(d)
    return items


@gallery_bp.route('/api/galleries/favorites', methods=['GET'])
def list_gallery_favorites():
    try:
        key = current_interaction_key()
        galleries = _gallery_interaction_rows(key, 'favorite', 'favorited_at') if key else []
        return jsonify({'success': True, 'galleries': galleries, 'total': len(galleries)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@gallery_bp.route('/api/galleries/likes', methods=['GET'])
def list_gallery_likes():
    try:
        key = current_interaction_key()
        galleries = _gallery_interaction_rows(key, 'like', 'liked_at') if key else []
        return jsonify({'success': True, 'galleries': galleries, 'total': len(galleries)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@gallery_bp.route('/api/galleries/disliked', methods=['GET'])
def list_gallery_disliked():
    try:
        key = current_interaction_key()
        galleries = _gallery_interaction_rows(key, 'dislike', 'disliked_at', with_size=True) if key else []
        return jsonify({'success': True, 'galleries': galleries, 'total': len(galleries)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@gallery_bp.route('/api/galleries/history', methods=['GET'])
def list_gallery_history():
    """已阅读过（progress>0）的图集，按最近阅读时间倒序。"""
    try:
        key = current_interaction_key()
        if not key:
            return jsonify({'success': True, 'galleries': [], 'total': 0})
        rows = GalleryProgress.query.filter(
            GalleryProgress.user_session == key,
            GalleryProgress.progress > 0
        ).order_by(GalleryProgress.updated_at.desc()).all()
        items = []
        for row in rows:
            c = Gallery.query.get(row.gallery_id)
            if not c:
                continue
            d = c.to_dict()
            d['cover_url'] = (c.cover_url or _gallery_url(c.cover_path)) + _gallery_ver_param(c)
            d['page'] = row.page
            d['last_page'] = row.page
            d['progress'] = row.progress
            d['page_count'] = c.page_count
            d['updated_at'] = row.updated_at.isoformat() if row.updated_at else None
            items.append(d)
        return jsonify({'success': True, 'galleries': items, 'total': len(items)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ 图集页面图片服务 ============
@gallery_bp.route('/gallery-page/<path:page_path>', methods=['GET'])
def serve_gallery_page(page_path):
    try:
        page_path = unquote(page_path)
        while '//' in page_path:
            page_path = page_path.replace('//', '/')
        page_path = page_path.replace('/', os.sep)

        # 回源资源索引校验所属资源库是否激活：
        # 仅凭磁盘路径白名单放行会绕过资源库管控，使未激活库的图片仍可直取。
        guard_location(page_path)
        if not os.path.isfile(page_path):
            abort(404)
        return send_file(page_path, mimetype=_image_mimetype(page_path))
    except HTTPException:
        raise
    except Exception:
        abort(500)


# ============ 帖子专属图集文件服务 ============
# 帖子专属的 gallery_folder 资源（仅 post 模式、未建 Gallery 实体）直接按
# resource_index 位置提供图片，避免依赖 GalleryPage 表，也不进图集列表。
_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.avif')


def _gallery_folder_images(ri):
    """列出 gallery_folder 资源目录下的图片文件。

    排序必须与扫描器 _list_images 一致（自然序 1,2,10 而非字典序 1,10,2），
    否则按下标定位时会与入库的 page_index 错位，翻出来的图和页码对不上。
    """
    if not ri or ri.kind != 'gallery_folder' or not ri.location or not os.path.isdir(ri.location):
        return []
    from backend.gallery.scanner import _natural_key
    return sorted((f for f in os.listdir(ri.location) if f.lower().endswith(_IMAGE_EXTS)),
                  key=_natural_key)


@gallery_bp.route('/resource-file/<int:rid>/<int:idx>', methods=['GET'])
def serve_resource_file(rid, idx):
    try:
        ri = ResourceIndex.query.get_or_404(rid)
        guard_resource_index(ri)
        if ri.kind != 'gallery_folder' or not ri.location or not os.path.isdir(ri.location):
            abort(404)
        if idx < 0:
            abort(404)
        # 已建图集实体时，以入库的页面记录为准取文件：
        # 页面记录（file_path / page_index）才是「这本图集有哪几页、第几页是哪张」的权威来源。
        # 若改用「重新列目录 + 下标」定位，目录内容一旦与入库时不同（增删图片、排序规则不一致），
        # 尾部下标就会越界 404，阅读器上表现为「明明没有这张图，却多出一页且加载失败」。
        g = Gallery.query.filter_by(resource_index_id=ri.id).first()
        if g is not None:
            p = GalleryPage.query.filter_by(gallery_id=g.id, page_index=idx).first()
            # 该页无记录或记录指向的文件已不在磁盘上：这一页确实不存在，直接 404，
            # 不能回退成按下标取相邻文件，否则会串页。
            if not p or not p.file_path or not os.path.isfile(p.file_path):
                abort(404)
            fp = os.path.normpath(p.file_path)
        else:
            # 帖子专属 gallery_folder（未建 Gallery 实体、无页面记录）仍按目录下标定位
            files = _gallery_folder_images(ri)
            if idx >= len(files):
                abort(404)
            fp = os.path.normpath(os.path.join(ri.location, files[idx]))
        root = os.path.normpath(ri.location)
        if not (fp == root or fp.startswith(root + os.sep)):
            abort(403)
        if not os.path.isfile(fp):
            abort(404)
        return send_file(fp, mimetype=_image_mimetype(fp))
    except HTTPException:
        raise
    except Exception:
        abort(500)


@gallery_bp.route('/resource-file/<int:rid>/doc', methods=['GET'])
def serve_resource_document(rid):
    """提供帖子专属文档附件（PDF / Office 等）下载。"""
    try:
        ri = ResourceIndex.query.get_or_404(rid)
        guard_resource_index(ri)
        if ri.kind != 'document_file' or not ri.location or not os.path.isfile(ri.location):
            abort(404)
        return send_file(ri.location, as_attachment=True,
                         download_name=os.path.basename(ri.location))
    except HTTPException:
        raise
    except Exception:
        abort(500)


@gallery_bp.route('/gallery-cover/<gallery_hash>', methods=['GET'])
def serve_gallery_cover(gallery_hash):
    try:
        c = Gallery.query.filter_by(hash=gallery_hash).first_or_404()
        if not is_gallery_visible(c):
            abort(404)
        if not c.cover_path or not os.path.isfile(c.cover_path):
            abort(404)
        return send_file(c.cover_path, mimetype=_image_mimetype(c.cover_path))
    except HTTPException:
        raise
    except Exception:
        abort(500)


# ============ 后台扫描（管理员） ============
@gallery_bp.route('/api/admin/libraries/<int:library_id>/scan-galleries', methods=['POST'])
def admin_scan_galleries(library_id):
    if not _is_admin():
        return jsonify({'success': False, 'message': '需要管理员权限', 'code': 403}), 403
    try:
        app = current_app._get_current_object()

        def _run():
            _gallery_scan_progress[library_id] = {
                'status': 'scanning', 'added': 0, 'updated': 0,
                'removed': 0, 'total': 0, 'message': '扫描中...'
            }
            try:
                from backend.gallery.scanner import scan_library_galleries
                res = scan_library_galleries(library_id, app)
                _gallery_scan_progress[library_id] = {
                    'status': 'done',
                    'added': res.get('added', 0),
                    'updated': res.get('updated', 0),
                    'removed': res.get('removed', 0),
                    'total': res.get('total', 0),
                    'message': '扫描完成',
                }
            except Exception as e:
                _gallery_scan_progress[library_id] = {
                    'status': 'error', 'message': str(e)
                }

        threading.Thread(target=_run, daemon=True).start()
        return jsonify({'success': True, 'started': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@gallery_bp.route('/api/admin/libraries/<int:library_id>/gallery-scan-status', methods=['GET'])
def admin_gallery_scan_status(library_id):
    return jsonify({'success': True,
                    'status': _gallery_scan_progress.get(library_id, {'status': 'idle'})})





# ============ 图集标签（复用 tags 表，对齐视频标签体系）============
@gallery_bp.route('/api/galleries/tags', methods=['GET'])
def list_gallery_tags():
    """返回标签树（或扁平列表）及每个标签下的图集数，对齐视频 /api/tags。"""
    try:
        tree = request.args.get('tree') == 'true'
        library_id = request.args.get('library_id', type=int)
        allowed_libs = _allowed_library_ids()
        # 主库已统一归入「主资源库」，不再有 library_id 为 NULL 的例外放行；
        # 无可见库时标签计数应为空，避免通过标签树反推被停用库的资源规模。
        allowed_gallery_ids = set()
        if allowed_libs:
            for cid in db.session.query(Gallery.id).filter(
                    Gallery.library_id.in_(allowed_libs)).all():
                allowed_gallery_ids.add(cid[0])

        rows = db.session.query(GalleryTag.tag_id, GalleryTag.gallery_id).all()
        tag_gallery = {}
        for tid, cid in rows:
            if cid in allowed_gallery_ids:
                tag_gallery.setdefault(tid, set()).add(cid)

        q = Tag.query
        if library_id is not None:
            q = q.filter((Tag.library_id == None) | (Tag.library_id == library_id))
        tags = q.all()

        def count_for(tag):
            ids = set(tag.get_all_child_ids())
            cset = set()
            for t in ids:
                if t in tag_gallery:
                    cset |= tag_gallery[t]
            return len(cset)

        result = []
        for t in tags:
            result.append({
                'id': t.id, 'name': t.name, 'qualifiers': t.get_qualifiers(), 'path': t.path,
                'category': t.category, 'parent_id': t.parent_id,
                'library_id': t.library_id, 'gallery_count': count_for(t)
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


@gallery_bp.route('/api/gallery/<gallery_hash>/tags', methods=['GET'])
def get_gallery_tags(gallery_hash):
    try:
        c = Gallery.query.filter_by(hash=gallery_hash).first()
        if not is_gallery_visible(c):
            return deny_missing()
        tag_ids = [r[0] for r in db.session.query(GalleryTag.tag_id).filter_by(gallery_id=c.id).all()]
        tags = Tag.query.filter(Tag.id.in_(tag_ids)).all() if tag_ids else []
        return jsonify({'success': True, 'tags': [{'id': t.id, 'name': t.name, 'qualifiers': t.get_qualifiers(), 'path': t.path, 'library_id': t.library_id} for t in tags]})
    except HTTPException:
        raise
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@gallery_bp.route('/api/gallery/<gallery_hash>/tags', methods=['POST'])
def set_gallery_tags(gallery_hash):
    """以传入的标签路径列表整体替换该图集的标签（对齐视频打标签）。"""
    try:
        c = Gallery.query.filter_by(hash=gallery_hash).first_or_404()
        data = request.get_json(silent=True) or {}
        tag_paths = data.get('tags', [])
        GalleryTag.query.filter_by(gallery_id=c.id).delete()
        lib_id = c.library_id
        for tp in tag_paths:
            tp = (tp or '').strip()
            if not tp:
                continue
            path = tp if tp.startswith('/') else '/' + tp
            tag = _ensure_tag_path(path, lib_id)
            db.session.add(GalleryTag(gallery_id=c.id, tag_id=tag.id))
        db.session.commit()
        return jsonify({'success': True})
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@gallery_bp.route('/api/gallery/<gallery_hash>/update', methods=['POST'])
def update_gallery_info(gallery_hash):
    """更新图集信息（标题、所属资源库）"""
    try:
        c = Gallery.query.filter_by(hash=gallery_hash).first_or_404()
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
        return jsonify({'success': True, 'gallery': c.to_dict()})
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@gallery_bp.route('/api/gallery/<gallery_hash>/tags', methods=['DELETE'])
def delete_gallery_tags(gallery_hash):
    try:
        c = Gallery.query.filter_by(hash=gallery_hash).first_or_404()
        # 资源所属权校验：仅本人或管理员/ROOT 可编辑
        uid, role = _resolve_identity()
        if not _is_admin() and c.owner_id not in (None, uid):
            return jsonify({'success': False, 'message': '无权编辑该资源（仅上传者或管理员可操作）', 'code': 403}), 403
        data = request.get_json(silent=True) or {}
        tag_id = data.get('tag_id')
        if tag_id:
            GalleryTag.query.filter_by(gallery_id=c.id, tag_id=tag_id).delete()
        else:
            GalleryTag.query.filter_by(gallery_id=c.id).delete()
        db.session.commit()
        return jsonify({'success': True})
    except HTTPException:
        raise
    except Exception as er2:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(er2)}), 500


# ============ 图集合集（播放列表，对齐视频 Playlist）============
@gallery_bp.route('/api/gallery-playlists', methods=['GET'])
def list_gallery_playlists():
    try:
        key = current_interaction_key()
        pls = GalleryPlaylist.query.filter(
            (GalleryPlaylist.user_session == key) | (GalleryPlaylist.is_public == True)
        ).order_by(GalleryPlaylist.updated_at.desc()).all()
        return jsonify({'success': True, 'playlists': [p.to_dict() for p in pls]})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@gallery_bp.route('/api/gallery-playlists', methods=['POST'])
def create_gallery_playlist():
    try:
        key = current_interaction_key()
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'success': False, 'message': '名称不能为空'}), 400
        pl = GalleryPlaylist(
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


@gallery_bp.route('/api/gallery-playlists/<int:pid>', methods=['GET'])
def get_gallery_playlist(pid):
    try:
        pl = GalleryPlaylist.query.get_or_404(pid)
        key = current_interaction_key()
        if pl.user_session != key and not pl.is_public:
            return jsonify({'success': False, 'message': '无权访问', 'code': 403}), 403
        return jsonify({'success': True, 'playlist': pl.to_dict()})
    except HTTPException:
        raise
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@gallery_bp.route('/api/gallery/<gallery_hash>', methods=['DELETE'])
def delete_gallery(gallery_hash):
    """删除图集：默认移入回收站；管理员可传 delete_file/permanent 永久删除。"""
    try:
        body = request.get_json(silent=True) or {}
        permanent = bool(body.get('delete_file', False) or body.get('permanent', False))
        c = Gallery.query.filter_by(hash=gallery_hash).first_or_404()

        uid, urole = _resolve_identity()
        if urole not in (UserRole.ADMIN, UserRole.ROOT) and c.owner_id not in (None, uid):
            return jsonify({'success': False, 'message': '无权删除该图集（仅上传者或管理员可操作）', 'code': 403}), 403

        if permanent:
            if urole not in (UserRole.ADMIN, UserRole.ROOT):
                return jsonify({'success': False, 'message': '仅管理员可永久删除', 'code': 403}), 403
            purge_trash(c, 'gallery')
            log.maintenance('INFO', f"永久删除图集: {c.title} (hash: {gallery_hash})")
            return jsonify({'success': True, 'message': '图集已永久删除'})
        else:
            move_to_trash(c, 'gallery')
            log.maintenance('INFO', f"图集移入回收站: {c.title} (hash: {gallery_hash})")
            return jsonify({'success': True, 'message': '已移入回收站'})
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        try:
            current_app.logger.exception(f"删除图集失败 hash={gallery_hash}")
        except Exception:
            pass
        return jsonify({'success': False, 'message': str(e)}), 500


@gallery_bp.route('/api/gallery/<gallery_hash>/reload', methods=['POST'])
def reload_gallery(gallery_hash):
    """重新加载图集资源：从磁盘重新读取文件夹、同步页面与封面，并刷新 updated_at。

    用于图集内部图片被替换 / 增删后，强制更新而不必等整库扫描或重启。
    仅上传者或管理员/ROOT 可操作（对齐删除/编辑权限）。
    """
    try:
        c = Gallery.query.filter_by(hash=gallery_hash).first_or_404()
        uid, urole = _resolve_identity()
        if urole not in (UserRole.ADMIN, UserRole.ROOT) and c.owner_id not in (None, uid):
            return jsonify({'success': False, 'message': '无权重新加载该图集（仅上传者或管理员可操作）', 'code': 403}), 403

        folder = c.folder_path
        if not folder or not os.path.isdir(folder):
            return jsonify({'success': False, 'message': '图集文件夹不存在或已被移动', 'code': 404}), 404

        from backend.gallery.scanner import _list_images, _sync_pages
        pages = _list_images(folder)
        if not pages:
            return jsonify({'success': False, 'message': '文件夹内未找到图片', 'code': 400}), 400

        _sync_pages(c, pages)
        # cover 由 pages[0] 推导，无需单独存储
        c.page_count = len(pages)
        c.updated_at = datetime.utcnow()
        db.session.commit()

        log.maintenance('INFO', f"重新加载图集资源: {c.title} (hash: {gallery_hash}), 页数={len(pages)}")
        return jsonify({
            'success': True,
            'gallery': c.to_dict(),
            'page_count': len(pages),
            'message': '图集资源已重新加载'
        })
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@gallery_bp.route('/api/gallery-playlists/<int:pid>', methods=['PUT'])
def update_gallery_playlist(pid):
    try:
        pl = GalleryPlaylist.query.get_or_404(pid)
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


@gallery_bp.route('/api/gallery-playlists/<int:pid>', methods=['DELETE'])
def delete_gallery_playlist(pid):
    try:
        pl = GalleryPlaylist.query.get_or_404(pid)
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


@gallery_bp.route('/api/gallery-playlists/<int:pid>/galleries', methods=['POST'])
def add_gallery_to_playlist(pid):
    try:
        pl = GalleryPlaylist.query.get_or_404(pid)
        key = current_interaction_key()
        if pl.user_session != key:
            return jsonify({'success': False, 'message': '无权修改', 'code': 403}), 403
        data = request.get_json(silent=True) or {}
        gallery_hash = data.get('hash')
        if not gallery_hash:
            return jsonify({'success': False, 'message': '缺少图集 hash'}), 400
        c = Gallery.query.filter_by(hash=gallery_hash).first()
        if not c:
            return jsonify({'success': False, 'message': '图集不存在'}), 404
        if GalleryPlaylistItem.query.filter_by(playlist_id=pid, gallery_id=c.id).first():
            return jsonify({'success': False, 'message': '已在合集中'}), 409
        pos = db.session.query(db.func.max(GalleryPlaylistItem.position)).filter_by(playlist_id=pid).scalar() or 0
        item = GalleryPlaylistItem(playlist_id=pid, gallery_id=c.id, position=pos + 1)
        db.session.add(item)
        pl.update_gallery_count()
        pl.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True, 'item': item.to_dict(), 'gallery_count': pl.gallery_count})
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@gallery_bp.route('/api/gallery-playlists/<int:pid>/galleries/<gallery_hash>', methods=['DELETE'])
def remove_gallery_from_playlist(pid, gallery_hash):
    try:
        pl = GalleryPlaylist.query.get_or_404(pid)
        key = current_interaction_key()
        if pl.user_session != key:
            return jsonify({'success': False, 'message': '无权修改', 'code': 403}), 403
        c = Gallery.query.filter_by(hash=gallery_hash).first()
        if not c:
            return jsonify({'success': False, 'message': '图集不存在'}), 404
        item = GalleryPlaylistItem.query.filter_by(playlist_id=pid, gallery_id=c.id).first()
        if item:
            db.session.delete(item)
            pl.update_gallery_count()
            pl.updated_at = datetime.utcnow()
            db.session.commit()
        return jsonify({'success': True, 'gallery_count': pl.gallery_count})
    except HTTPException:
        raise
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@gallery_bp.route('/api/gallery-playlists/<int:pid>/galleries/reorder', methods=['PUT'])
def reorder_gallery_playlist(pid):
    try:
        pl = GalleryPlaylist.query.get_or_404(pid)
        key = current_interaction_key()
        if pl.user_session != key:
            return jsonify({'success': False, 'message': '无权修改', 'code': 403}), 403
        data = request.get_json(silent=True) or {}
        order = data.get('order', [])
        pos = 1
        for h in order:
            c = Gallery.query.filter_by(hash=h).first()
            if not c:
                continue
            item = GalleryPlaylistItem.query.filter_by(playlist_id=pid, gallery_id=c.id).first()
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



