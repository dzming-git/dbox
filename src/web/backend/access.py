# -*- coding: utf-8 -*-
"""统一鉴权与资源库权限解析层。

把原先散落在 main.py 顶层的鉴权辅助函数集中到此处，供所有蓝图
（gallery / trash / posts / tags ...）直接 import，模块自身不依赖 main。

本模块只依赖 core.models、auth_service、backend.utils.jwt_authlib，
不依赖 main，可在任意上下文中安全导入。
"""
from flask import request, session, g, jsonify
from functools import wraps
import random

from core.models import (
    db, User, UserRole, Video, Gallery, ResourceLibrary, LibraryPermission,
    LibraryUserGroupMember, Post, PostRef, ResourceIndex,
    parse_post_content_tokens,
)
from auth_service import AuthService
from backend.utils.jwt_authlib import SECRET_KEY as JWT_SECRET_KEY
from backend.helpers import _resolve_dbox_library_id_by_folder


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
            for _secret in (JWT_SECRET_KEY, 'dbox-jwt-secret-key-change-in-production-2024'):
                try:
                    _payload = _jwt.decode(_token, _secret)
                    break
                except Exception:
                    continue
            if _payload and _payload.get('type') == 'access':
                return _payload.get('user_id'), int(_payload.get('role', UserRole.GUEST))
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
    # 3. 浏览器原生 <img> 请求无法携带 Authorization 头，
    # 缩略图/封面接口通过 URL ?token= 传递 JWT（与 gallery 侧 _gallery_auth_ok 对齐）
    token_arg = request.args.get('token')
    if token_arg:
        try:
            from authlib.jose import jwt as _jwt
            _payload = None
            for _secret in (JWT_SECRET_KEY, 'dbox-jwt-secret-key-change-in-production-2024'):
                try:
                    _payload = _jwt.decode(token_arg, _secret)
                    break
                except Exception:
                    continue
            if _payload and _payload.get('type') == 'access':
                return _payload.get('user_id'), int(_payload.get('role', UserRole.GUEST))
        except Exception:
            pass
    return None, UserRole.GUEST


def current_interaction_key():
    """返回交互记录（点赞/收藏/踩）的身份键。

    登录用户使用 u{user_id}，跨设备一致；未登录游客使用随机会话，仅当前浏览器有效。
    """
    user_id, _ = resolve_identity()
    if user_id:
        return f'u{user_id}'
    return get_user_session()


def _collect_user_permissions(user_id):
    """收集某用户的全部 LibraryPermission（直接授权 + 用户组授权 + 通用授权）。

    返回 LibraryPermission 对象列表（已去重，通用权限 user_id=None 始终包含）。
    """
    perms = []
    if user_id:
        perms.extend(LibraryPermission.query.filter_by(user_id=user_id).all())
        member_groups = [m.group_id for m in
                         LibraryUserGroupMember.query.filter_by(user_id=user_id).all()]
        if member_groups:
            perms.extend(LibraryPermission.query.filter(
                LibraryPermission.group_id.in_(member_groups)).all())
    # 通用权限（user_id=NULL，表示对所有登录/游客生效）
    perms.extend(LibraryPermission.query.filter_by(user_id=None).all())
    return perms


def _collect_user_denials(user_id):
    """收集某用户被「显式拒绝」访问的资源库 ID 集合。

    拒绝语义用于覆盖「通用授权(user_id=NULL) / 用户组授权」这类会作用到全体
    成员的授权：管理员在用户维度把某库设为 none 时，必须能盖过通用/组授权，
    否则「关闭某用户对某库的权限」对通过通用/组授权获得该库的人无效。

    拒绝 = 直接授权或用户组授权中 access_level='none' 的记录。
    """
    denied = set()
    if not user_id:
        return denied
    for perm in LibraryPermission.query.filter_by(user_id=user_id).all():
        if (perm.access_level or 'read') == 'none':
            denied.add(perm.library_id)
    member_groups = [m.group_id for m in
                     LibraryUserGroupMember.query.filter_by(user_id=user_id).all()]
    if member_groups:
        for perm in LibraryPermission.query.filter(
                LibraryPermission.group_id.in_(member_groups)).all():
            if (perm.access_level or 'read') == 'none':
                denied.add(perm.library_id)
    return denied


def _perm_allows_write(perm):
    """判断一条 LibraryPermission 是否授予写权限。

    access_level:
      - 'full' / 'write'  -> 可读写
      - 'read'            -> 仅只读
      - 'custom'          -> 取决于 permissions JSON 中是否含 'write'
    管理员/ROOT 由调用方单独兜底，此处只评单一记录。
    """
    if perm is None:
        return False
    level = (perm.access_level or 'read')
    if level in ('write', 'full'):
        return True
    if level == 'custom':
        perms = perm.permissions
        if isinstance(perms, (list, tuple)):
            return 'write' in perms
        if isinstance(perms, dict):
            return bool(perms.get('write', False))
    return False


def get_allowed_library_ids():
    """
    获取当前用户允许「读取」的资源库ID列表（库的读权限是写权限的超集）。

    读权限 = access_level 为 read/write/full/custom 的任意授权（含用户组、通用授权）。
    管理员和 ROOT 可读所有激活库。返回: allowed_library_ids (list)
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
        # 已登录的普通用户：任何授予读权限（含 read/write/full/custom）的库均可读
        # 直接授权 + 用户组授权 + 通用授权 三者取并集
        seen = set()
        for perm in _collect_user_permissions(user_id):
            lib = ResourceLibrary.query.get(perm.library_id)
            if lib and lib.is_active and perm.library_id not in seen:
                seen.add(perm.library_id)
                allowed_library_ids.append(perm.library_id)
        # 显式拒绝覆盖通用/用户组授权：被设为 none 的库从可读集合中剔除
        denied = _collect_user_denials(user_id)
        if denied:
            allowed_library_ids = [lid for lid in allowed_library_ids if lid not in denied]
    else:
        # 未登录用户：只能看到有通用权限（user_id=NULL）的激活库
        general_perms = LibraryPermission.query.filter_by(user_id=None).all()
        for perm in general_perms:
            lib = ResourceLibrary.query.get(perm.library_id)
            if lib and lib.is_active:
                allowed_library_ids.append(perm.library_id)

    return allowed_library_ids


def get_writable_library_ids():
    """
    获取当前用户允许「写入」（增删改资源/文件夹/上传）的资源库ID列表。

    写权限 = access_level 为 write/full，或 custom 且 permissions 含 'write'。
    管理员和 ROOT 可写所有激活库。返回: writable_library_ids (list)
    """
    writable = []

    if not hasattr(Video, 'library_id'):
        return writable

    user_id, user_role = resolve_identity()

    if user_role in [UserRole.ADMIN, UserRole.ROOT]:
        all_active_libs = ResourceLibrary.query.filter_by(is_active=True).all()
        writable = [lib.id for lib in all_active_libs]
    elif user_id:
        denied = _collect_user_denials(user_id)
        seen = set()
        for perm in _collect_user_permissions(user_id):
            if perm.library_id in denied:
                continue
            if _perm_allows_write(perm):
                lib = ResourceLibrary.query.get(perm.library_id)
                if lib and lib.is_active and perm.library_id not in seen:
                    seen.add(perm.library_id)
                    writable.append(perm.library_id)

    return writable


def apply_video_visibility(query, allowed_ids=None):
    """在视频查询上叠加「库已激活 + 未删除 + 未隐藏」三层对外可见性过滤。

    这是资源库可见性的唯一收敛点：外界（首页列表、统计、收藏/点赞/不喜欢、
    回收站等）统一通过本函数约束，避免各处散落 `library_id == NULL` 等放行逻辑
    导致「取消资源库激活后资源仍对外可见」的越权泄露。

    - 主库（library_id 为 NULL）已通过 migrate_main_library 统一归入「主资源库」，
      因此不再存在 NULL 例外：可见资源必须归属某个 is_active 库。
    - allowed_ids 为空（未登录无通用权限 / 所有库均取消激活）时返回空结果。

    调用方仍需自行叠加 search / sort / 精确 library_id 筛选与分页。
    """
    if allowed_ids is None:
        allowed_ids = get_allowed_library_ids()
    query = query.filter(Video.in_trash == False)
    # 排除隐藏资源（hidden=True 仅在帖子流可见，不出现在资源库列表）
    query = query.filter(~Video.resource_index.has(ResourceIndex.hidden == True))
    if allowed_ids:
        query = query.filter(Video.library_id.in_(allowed_ids))
    else:
        # 无任何可见库时强制返回空（避免 NULL/全量越权泄露）
        query = query.filter(Video.library_id == -1)
    return query


def apply_gallery_visibility(query, allowed_ids=None):
    """在图集查询上叠加「库已激活 + 未删除 + 未隐藏」可见性过滤。

    与 apply_video_visibility 同源同口径，避免图集侧出现独立的放行分支。
    """
    if allowed_ids is None:
        allowed_ids = get_allowed_library_ids()
    query = query.filter(Gallery.in_trash == False)
    query = query.filter(~Gallery.resource_index.has(ResourceIndex.hidden == True))
    if allowed_ids:
        query = query.filter(Gallery.library_id.in_(allowed_ids))
    else:
        query = query.filter(Gallery.library_id == -1)
    return query


def is_video_visible(video, allowed_ids=None):
    """判断单个视频对当前用户是否可见（库已激活 + 未删除 + 未隐藏）。"""
    if not video:
        return False
    if allowed_ids is None:
        allowed_ids = get_allowed_library_ids()
    if getattr(video, 'in_trash', False):
        return False
    ri = getattr(video, 'resource_index', None)
    if ri is not None and getattr(ri, 'hidden', False):
        return False
    return video.library_id in set(allowed_ids)


def is_gallery_visible(gallery, allowed_ids=None):
    """判断单个图集对当前用户是否可见（库已激活 + 未删除 + 未隐藏）。"""
    if not gallery:
        return False
    if allowed_ids is None:
        allowed_ids = get_allowed_library_ids()
    if getattr(gallery, 'in_trash', False):
        return False
    ri = getattr(gallery, 'resource_index', None)
    if ri is not None and getattr(ri, 'hidden', False):
        return False
    return gallery.library_id in set(allowed_ids)


def visible_item_ids(item_type, item_ids, allowed_ids=None):
    """把一组 (type, hash) 条目过滤成「当前可见」的 hash 集合。

    用于 WatchHistory / WatchLater 这类**快照型**记录：它们冗余存储了
    title/thumbnail 且不含 library_id，无法自证归属，必须回源到 Video/Gallery
    校验所属资源库是否仍处于激活状态，否则库停用后历史/稍后再看仍会泄露资源。
    """
    ids = [str(i) for i in item_ids if i]
    if not ids:
        return set()
    if allowed_ids is None:
        allowed_ids = get_allowed_library_ids()
    if item_type == 'video':
        q = apply_video_visibility(
            Video.query.filter(Video.hash.in_(ids)), allowed_ids)
        return {row.hash for row in q.all()}
    if item_type == 'gallery':
        q = apply_gallery_visibility(
            Gallery.query.filter(Gallery.hash.in_(ids)), allowed_ids)
        return {row.hash for row in q.all()}
    # 未知类型（post/text 等无独立库归属）默认不放行资源型条目
    return set()


def filter_visible_snapshots(rows, type_attr='item_type', id_attr='item_id',
                             allowed_ids=None, passthrough_types=()):
    """过滤快照型记录列表（WatchHistory / WatchLater），只保留资源仍可见的行。

    - rows: ORM 行列表
    - passthrough_types: 不受资源库管控的类型（如 post/text），原样保留
    统一在此收敛，确保「资源库停用 => 历史/稍后再看同步不可见」。
    """
    if not rows:
        return []
    if allowed_ids is None:
        allowed_ids = get_allowed_library_ids()
    buckets = {}
    for r in rows:
        buckets.setdefault(getattr(r, type_attr), []).append(getattr(r, id_attr))
    visible = {}
    for t, ids in buckets.items():
        if t in passthrough_types:
            continue
        visible[t] = visible_item_ids(t, ids, allowed_ids)
    out = []
    for r in rows:
        t = getattr(r, type_attr)
        if t in passthrough_types:
            out.append(r)
            continue
        if str(getattr(r, id_attr)) in visible.get(t, set()):
            out.append(r)
    return out


def default_library_id():
    """返回默认归属资源库（主资源库）ID，用于「所有资源必须有归属」的兜底。

    找不到主资源库时退回任一激活库；再找不到返回 None（调用方据此拒绝写入）。
    """
    from core.models import MAIN_LIBRARY_NAME
    lib = ResourceLibrary.query.filter_by(name=MAIN_LIBRARY_NAME).first()
    if lib:
        return lib.id
    lib = ResourceLibrary.query.filter_by(is_active=True).first()
    return lib.id if lib else None


def resource_index_visible(ri, allowed_ids=None):
    """判断资源索引本身是否对当前用户可见（库已激活且有权限）。

    这是「实际访问」层的统一判定：任何吐字节流的接口（视频串流、原文件、
    缩略图、封面、图集单页、文档下载）都必须先过这一关。
    资源索引是所有实体（视频/图集/文本/帖子引用）的共同底座，
    在此收敛可保证不存在绕过实体层直接拿文件的路径。
    """
    if ri is None:
        return False
    if allowed_ids is None:
        allowed_ids = get_allowed_library_ids()
    return ri.library_id in set(allowed_ids)


def deny_missing():
    """统一的「资源不存在」响应。

    安全要求：外界不得感知资源的存在性。无论是「真的没有」还是
    「存在但无权访问 / 所属资源库未激活」，一律返回 404 且文案一致，
    不得出现「权限不足」「未授权」等可用于探测资源存在的措辞。
    """
    return jsonify({'success': False, 'message': '资源不存在', 'code': 404}), 404


def abort_missing():
    """文件流接口用的「资源不存在」中断（等价于 deny_missing 的 abort 版）。"""
    from flask import abort as _abort
    _abort(404)


def guard_resource_index(ri, allowed_ids=None):
    """文件流接口守卫：资源索引不可见时直接 404（不泄露存在性）。"""
    if not resource_index_visible(ri, allowed_ids):
        abort_missing()
    return ri


def guard_location(location, allowed_ids=None):
    """按磁盘路径反查资源索引并校验可见性，不可见则 404。

    用于 /local_video/<path> 与 /gallery-page/<path> 这类「URL 直接带磁盘
    路径」的历史接口：它们原先只做路径白名单，任何人拿到路径即可取到文件，
    与资源库激活状态完全脱钩。此处强制回源到资源索引做权限判定。
    """
    if not location:
        abort_missing()
    if allowed_ids is None:
        allowed_ids = get_allowed_library_ids()
    import os as _os
    norm = _os.path.normcase(_os.path.abspath(location))
    ri = ResourceIndex.query.filter(ResourceIndex.location == location).first()
    if ri is None:
        # 兜底：统一分隔符与大小写后比较（仍基于完整路径，文件名不作为身份）
        for cand in ResourceIndex.query.filter(ResourceIndex.location.isnot(None)).all():
            try:
                if _os.path.normcase(_os.path.abspath(cand.location)) == norm:
                    ri = cand
                    break
            except Exception:
                continue
    # 图集单页等位于资源目录内部的文件：向上匹配所属资源目录
    if ri is None:
        for cand in ResourceIndex.query.filter(
                ResourceIndex.kind == 'gallery_folder').all():
            try:
                root = _os.path.normcase(_os.path.abspath(cand.location))
                if norm == root or norm.startswith(root + _os.sep):
                    ri = cand
                    break
            except Exception:
                continue
    # 资源索引 library_id 为 None（未归类）时，图集/视频实体仍可能明确归属某库。
    # 图集单页经 gallery_folder 匹配到资源索引后，若其未归类，回退用 Gallery 实体的
    # library_id 判定可见性，避免存量未归类数据导致图集页面 404。
    if ri is not None and ri.library_id is None:
        g = Gallery.query.filter_by(resource_index_id=ri.id).first()
        if g is not None and g.library_id is not None:
            if g.library_id not in set(allowed_ids):
                abort_missing()
            return ri
    if not resource_index_visible(ri, allowed_ids):
        abort_missing()
    return ri


def _post_library_ids(post):
    """收集帖子涉及的所有资源库 ID（含帖子自身、引用资源、正文内联资源）。

    返回 set；元素为 int 库 ID 或 None。None 表示「未归类到任何库」，
    同样需要落在 allowed_libs 内才可见（不再当作默认公开）。
    """
    libs = set()
    # 帖子自身归属库（None 也纳入，交由调用方统一判定）
    libs.add(post.library_id)
    # 引用资源
    for r in post.refs:
        ri = r.resource_index
        if ri is not None:
            libs.add(ri.library_id)
    # 正文内联资源标记 [文字](res:ID:mode)
    for tok in parse_post_content_tokens(post.content):
        ri = ResourceIndex.query.get(tok['resource_index_id'])
        if ri is not None:
            libs.add(ri.library_id)
    return libs


def _user_can_read_post(post, allowed_libs):
    """帖子 read 权限 = 其引用的全部资源的权限取交集。

    用户必须对帖子的每一个资源库都有访问权限（库 ID ∈ allowed_libs），
    包括「未归类库」(library_id=None)。任一库不在 allowed_libs（含未激活库、
    未归类库）则整个帖子对外不可读——即「帖子和帖子内引用资源都有权限看到时，
    才对外显示」。
    """
    allowed_set = set(allowed_libs)
    for lib in _post_library_ids(post):
        if lib not in allowed_set:
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
    """返回用户可作为 'admin' 管理的 dbox 资源库 id 集合（含用户组授权）。"""
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
            for _secret in (JWT_SECRET_KEY, 'dbox-jwt-secret-key-change-in-production-2024'):
                try:
                    from authlib.jose import jwt as _jwt
                    payload = _jwt.decode(token, _secret)
                    if payload.get('type') == 'access':
                        g.user_id = payload.get('user_id')
                        g.role = payload.get('role', UserRole.GUEST)
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
        if role > UserRole.ADMIN:
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
            if role <= UserRole.ADMIN:
                return f(*args, **kwargs)
            lid = kwargs.get(param)
            if param == 'folder_id':
                lid = _resolve_dbox_library_id_by_folder(lid)
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
        if role <= UserRole.ADMIN:
            return f(*args, **kwargs)
        if _user_library_admin_ids(user_id):
            return f(*args, **kwargs)
        return jsonify({'success': False, 'message': '需要资源库管理员权限', 'code': 403}), 403
    return decorated


def _user_can_write_library(user_id, library_id, user_role=None):
    """判断用户是否对指定库有写权限（access_level=write/full/custom+write）。

    管理员/ROOT 对所有激活库默认可写；其余按 LibraryPermission 判定。
    """
    if library_id is None:
        return False
    if user_role is None:
        user_id, user_role = resolve_identity()
    if user_role in [UserRole.ADMIN, UserRole.ROOT]:
        lib = ResourceLibrary.query.get(library_id)
        return bool(lib and lib.is_active)
    if not user_id:
        return False
    if library_id in _collect_user_denials(user_id):
        return False
    for perm in _collect_user_permissions(user_id):
        if perm.library_id == library_id and _perm_allows_write(perm):
            lib = ResourceLibrary.query.get(library_id)
            return bool(lib and lib.is_active)
    return False


def library_write_required(param='library_id'):
    """要求：登录用户 且 (全局管理员) 或 (该资源库的写权限持有者)。

    用于资源库文件夹增删改、上传等到「写」操作的接口，按 access_level
    区分只读(read)与可读写(write/full)，而非仅看 role='admin'。
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user_id, role = resolve_identity()
            if not user_id:
                return jsonify({'success': False, 'message': '未授权', 'code': 401}), 401
            if role <= UserRole.ADMIN:
                return f(*args, **kwargs)
            lid = kwargs.get(param)
            if param == 'folder_id':
                lid = _resolve_dbox_library_id_by_folder(lid)
            if lid is None or not _user_can_write_library(user_id, lid, role):
                return jsonify({'success': False, 'message': '需要该资源库的写入权限', 'code': 403}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator
