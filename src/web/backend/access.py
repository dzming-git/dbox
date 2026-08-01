# -*- coding: utf-8 -*-
"""统一鉴权与资源库权限解析层。

把原先散落在 main.py 顶层的鉴权辅助函数集中到此处，供所有蓝图
（gallery / trash / posts / tags ...）直接 import，消除
「蓝图从 main 延迟 import 鉴权函数」的反模式与循环依赖。

本模块只依赖 core.models、auth_service、backend.utils.jwt_authlib，
不依赖 main，可在任意上下文中安全导入。
"""
from flask import request, session, g, jsonify
from functools import wraps
import random

from core.models import (
    db, User, UserRole, Video, ResourceLibrary, LibraryPermission,
    LibraryUserGroupMember, Post, PostRef, ResourceIndex,
    parse_post_content_tokens,
)
from auth_service import AuthService
from backend.utils.jwt_authlib import SECRET_KEY as JWT_SECRET_KEY
from backend.helpers import _resolve_dplayer_library_id_by_folder


def get_user_session():
    if 'user_session' not in session:
        session['user_session'] = str(random.randint(100000, 999999))
    return session['user_session']


def resolve_identity():
    """解析当前登录用户身份，返回 (user_id, user_role)。

    登录态以 JWT Bearer 或 session 中的 auth_token 为准（与 AuthService 一致）。
    注意：登录只会在 session 写入 auth_token，不会写入 user_id/role，
    因此必须通过 auth_token 反查用户，而不能直接读取 session['user_id']。
    """
    # 1. 优先 JWT Bearer Token
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        _token = auth_header[7:]
        try:
            from authlib.jose import jwt as _jwt
            _payload = None
            for _secret in (JWT_SECRET_KEY, 'dplayer-jwt-secret-key-change-in-production-2024'):
                try:
                    _payload = _jwt.decode(_token, _secret)
                    break
                except Exception:
                    continue
            if _payload and _payload.get('type') == 'access':
                return _payload.get('user_id'), int(_payload.get('role', 0))
        except Exception:
            pass
        # 前端实际鉴权方式：Bearer 后接的是 session_token（非 JWT），
        # 通过 UserSession 表反查登录用户。
        try:
            user = AuthService.get_user_by_token(_token)
            if user:
                return user.id, int(user.role)
        except Exception:
            pass
    # 2. 回退到 session cookie（Flask session 中的 auth_token）
    try:
        user = AuthService.get_current_user()
        if user:
            return user.id, int(user.role)
    except Exception:
        pass
    return None, 0


def current_interaction_key():
    """返回交互记录（点赞/收藏/踩）的身份键。

    登录用户使用 u{user_id}，跨设备一致；未登录游客使用随机会话，仅当前浏览器有效。
    """
    user_id, _ = resolve_identity()
    if user_id:
        return f'u{user_id}'
    return get_user_session()


def get_allowed_library_ids():
    """
    获取当前用户允许访问的资源库ID列表
    返回: allowed_library_ids (list)
    """
    allowed_library_ids = []

    # 检查 Video 模型是否有 library_id 属性
    if not hasattr(Video, 'library_id'):
        return allowed_library_ids

    user_id, user_role = resolve_identity()

    # 管理员和ROOT可以访问所有激活的库
    if user_role in [UserRole.ADMIN, UserRole.ROOT]:
        all_active_libs = ResourceLibrary.query.filter_by(is_active=True).all()
        allowed_library_ids = [lib.id for lib in all_active_libs]
    elif user_id:
        # 已登录的普通用户：查询用户直接权限 + 用户组权限
        # 1. 获取用户直接权限的库
        user_perms = LibraryPermission.query.filter_by(user_id=user_id).all()
        for perm in user_perms:
            lib = ResourceLibrary.query.get(perm.library_id)
            if lib and lib.is_active:
                allowed_library_ids.append(perm.library_id)

        # 2. 获取用户组权限的库
        user_groups = LibraryUserGroupMember.query.filter_by(user_id=user_id).all()
        for ugm in user_groups:
            group_perms = LibraryPermission.query.filter_by(group_id=ugm.group_id).all()
            for perm in group_perms:
                lib = ResourceLibrary.query.get(perm.library_id)
                if lib and lib.is_active and perm.library_id not in allowed_library_ids:
                    allowed_library_ids.append(perm.library_id)

        # 3. 获取通用权限（user_id=NULL，表示所有人都可以访问）
        general_perms = LibraryPermission.query.filter_by(user_id=None).all()
        for perm in general_perms:
            lib = ResourceLibrary.query.get(perm.library_id)
            if lib and lib.is_active and perm.library_id not in allowed_library_ids:
                allowed_library_ids.append(perm.library_id)
    else:
        # 未登录用户：只能看到主数据库的视频（library_id=NULL）
        # 以及有通用权限的库
        # 1. 获取通用权限的库
        general_perms = LibraryPermission.query.filter_by(user_id=None).all()
        for perm in general_perms:
            lib = ResourceLibrary.query.get(perm.library_id)
            if lib and lib.is_active and perm.library_id not in allowed_library_ids:
                allowed_library_ids.append(perm.library_id)

    return allowed_library_ids


def _post_library_ids(post):
    """收集帖子涉及的所有资源库 ID（含帖子自身、引用资源、正文内联资源）。

    返回 set；元素为 int 库 ID 或 None（主库/公共可见）。
    """
    libs = set()
    if post.library_id is not None:
        libs.add(post.library_id)
    # 引用资源
    for r in post.refs:
        ri = r.resource_index
        if ri and ri.library_id is not None:
            libs.add(ri.library_id)
    # 正文内联资源标记 [文字](res:ID:mode)
    for tok in parse_post_content_tokens(post.content):
        ri = ResourceIndex.query.get(tok['resource_index_id'])
        if ri and ri.library_id is not None:
            libs.add(ri.library_id)
    return libs


def _user_can_read_post(post, allowed_libs):
    """帖子 read 权限 = 其引用的全部资源的权限取交集。

    用户必须对帖子的每一个资源库都有访问权限（库 ID ∈ allowed_libs），
    主库（library_id=None）视为所有人可访问。任一受限库无权限则不可读。
    """
    for lib in _post_library_ids(post):
        if lib is not None and lib not in allowed_libs:
            return False
    return True


def resolve_user():
    """统一解析当前用户：优先 JWT 中间件注入的 g.user_id，回退到 session 用户。

    前端经由 vite 代理 / JWT 鉴权时，请求上下文由全局 before_request 把用户写入 g.user_id；
    直接的 session 登录则走 AuthService.get_current_user()。两者都支持，避免鉴权口径不一致。
    """
    uid = getattr(g, 'user_id', None)
    if uid:
        u = User.query.get(uid)
        if u:
            return u
    return AuthService.get_current_user()


def _is_library_admin(user_id, library_id):
    """用户是否为该资源库的 'admin'（资源管理员），含用户组授权。"""
    if LibraryPermission.query.filter_by(user_id=user_id, library_id=library_id, role='admin').first():
        return True
    member_groups = [m.group_id for m in LibraryUserGroupMember.query.filter_by(user_id=user_id).all()]
    if member_groups:
        if LibraryPermission.query.filter(
            LibraryPermission.group_id.in_(member_groups),
            LibraryPermission.library_id == library_id,
            LibraryPermission.role == 'admin'
        ).first():
            return True
    return False


def _user_library_admin_ids(user_id):
    """返回用户可作为 'admin' 管理的 dplayer 资源库 id 集合（含用户组授权）。"""
    ids = set()
    for p in LibraryPermission.query.filter_by(user_id=user_id, role='admin').all():
        ids.add(p.library_id)
    member_groups = [m.group_id for m in LibraryUserGroupMember.query.filter_by(user_id=user_id).all()]
    if member_groups:
        for p in LibraryPermission.query.filter(
            LibraryPermission.group_id.in_(member_groups),
            LibraryPermission.role == 'admin'
        ).all():
            ids.add(p.library_id)
    return ids


def auth_required(f):
    """通用认证装饰器 - 复用 resolve_identity 统一解析；保留 URL query token 回退。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id, role = resolve_identity()
        if user_id:
            g.user_id = user_id
            g.role = role
            u = User.query.get(user_id)
            g.username = u.username if u else None
            return f(*args, **kwargs)
        token = request.args.get('token')
        if token:
            for _secret in (JWT_SECRET_KEY, 'dplayer-jwt-secret-key-change-in-production-2024'):
                try:
                    from authlib.jose import jwt as _jwt
                    payload = _jwt.decode(token, _secret)
                    if payload.get('type') == 'access':
                        g.user_id = payload.get('user_id')
                        g.role = payload.get('role', 0)
                        g.username = payload.get('username')
                        return f(*args, **kwargs)
                except Exception:
                    continue
        return jsonify({'success': False, 'message': '未授权', 'code': 401}), 401
    return decorated


def admin_required(f):
    """管理员权限装饰器 - 复用 resolve_identity 统一解析。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id, role = resolve_identity()
        if not user_id:
            return jsonify({'success': False, 'message': '未授权', 'code': 401}), 401
        if role < UserRole.ADMIN:
            return jsonify({'success': False, 'message': '需要管理员权限', 'code': 403}), 403
        g.user_id = user_id
        g.role = role
        u = User.query.get(user_id)
        g.username = u.username if u else None
        return f(*args, **kwargs)
    return decorated


def library_admin_required(param='library_id'):
    """要求：登录用户 且 (全局管理员) 或 (该资源库的 'admin' 权限持有者)。"""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user_id, role = resolve_identity()
            if not user_id:
                return jsonify({'success': False, 'message': '未授权', 'code': 401}), 401
            if role >= UserRole.ADMIN:
                return f(*args, **kwargs)
            lid = kwargs.get(param)
            if param == 'folder_id':
                lid = _resolve_dplayer_library_id_by_folder(lid)
            if lid is None or not _is_library_admin(user_id, lid):
                return jsonify({'success': False, 'message': '需要该资源库管理员权限', 'code': 403}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


def resource_manager_required(f):
    """要求：登录用户 且 (全局管理员) 或 (任一资源库的 'admin' 权限持有者)。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id, role = resolve_identity()
        if not user_id:
            return jsonify({'success': False, 'message': '未授权', 'code': 401}), 401
        if role >= UserRole.ADMIN:
            return f(*args, **kwargs)
        if _user_library_admin_ids(user_id):
            return f(*args, **kwargs)
        return jsonify({'success': False, 'message': '需要资源库管理员权限', 'code': 403}), 403
    return decorated
