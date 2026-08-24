"""Auto-split blueprint: system_api (moved from main.py)."""
from backend.paths import DATA_DIR
import threading
from backend.system_helpers import SETTINGS_DEFAULTS
import time
from core.models import Tag
from backend.audit import log_operation
from core.models import User
from core.models import db
from backend.system_helpers import save_config
import os
from core.models import UserRole
from core.models import ResourceLibrary
from core.models import LibraryPermission
from core.models import LibraryUserGroupMember
from core.models import Video
from core.models import AppSetting
from datetime import datetime, timedelta
from backend.runtime import runtime
from backend.access import get_allowed_library_ids
from backend.access import resolve_identity
from backend.access import admin_required, auth_required
from backend.access import _perm_allows_write
from flask import Blueprint, request, jsonify, send_file, send_from_directory, session, g, abort, Response, current_app
from liblog import get_service_logger
log = get_service_logger('dbox-web')

bp = Blueprint('system_api', __name__)

@bp.route('/api/settings', methods=['GET'])
def api_get_settings():
    """获取当前用户可见的分层设置（游客仅返回全局层与默认值）。

    返回 defaults / global / user 三层原始数据，浏览器层由前端自行合并。
    无需登录即可访问，以便游客也能继承管理员的全局默认。
    """
    user_id, role = resolve_identity()
    global_setting = AppSetting.query.filter_by(scope='global', owner='').first()
    global_data = global_setting.get_data() if global_setting else {}
    user_data = {}
    if user_id:
        user_setting = AppSetting.query.filter_by(scope='user', owner=str(user_id)).first()
        user_data = user_setting.get_data() if user_setting else {}
    return jsonify({
        'success': True,
        'defaults': SETTINGS_DEFAULTS,
        'global': global_data,
        'user': user_data,
        'is_admin': role <= UserRole.ADMIN,
    })

@bp.route('/api/settings', methods=['POST'])
@auth_required
def api_save_settings():
    """保存设置。

    body: { scope: 'user'|'global', settings: {...partial}, reset?: [keys] }
    - scope='global' 需要管理员权限，写入全站默认（owner=''）
    - scope='user'   写入当前登录用户（owner=用户ID），跨设备生效
    - reset 中的键会从该层删除（回落到下一层）
    """
    user_id, role = resolve_identity()
    body = request.get_json(silent=True) or {}
    scope = body.get('scope')
    settings = body.get('settings') or {}
    reset_keys = body.get('reset') or []

    if not isinstance(settings, dict):
        return jsonify({'success': False, 'message': 'settings 必须是对象', 'code': 400}), 400

    if scope == 'global':
        if role > UserRole.ADMIN:
            return jsonify({'success': False, 'message': '需要管理员权限', 'code': 403}), 403
        owner = ''
    elif scope == 'user':
        if not user_id:
            return jsonify({'success': False, 'message': '未登录', 'code': 401}), 401
        owner = str(user_id)
    else:
        return jsonify({'success': False, 'message': 'scope 必须是 user 或 global', 'code': 400}), 400

    record = AppSetting.query.filter_by(scope=scope, owner=owner).first()
    existing = record.get_data() if record else {}
    existing.update(settings)
    # 仅保留白名单内的键
    existing = {k: v for k, v in existing.items() if k in SETTINGS_DEFAULTS}
    for k in (reset_keys or []):
        existing.pop(k, None)

    if record is None:
        record = AppSetting(scope=scope, owner=owner)
        db.session.add(record)
    record.set_data(existing)
    db.session.commit()
    log_operation('save settings', target=f'层={scope}', detail=f'键={list(settings.keys())}', success=True)
    return jsonify({'success': True, 'scope': scope, 'data': record.get_data()})

@bp.route('/api/admin/config', methods=['GET'])
@admin_required
def get_system_config():
    """获取系统配置"""
    try:
        # 从数据库或配置文件读取
        config = {
            'max_upload_size': 1024,  # MB
            'thumbnail_quality': 85,
            'auto_sync': True,
            'allow_register': False
        }
        return jsonify({'success': True, 'config': config})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/config', methods=['POST'])
@admin_required
def update_system_config():
    """更新系统配置"""
    try:
        data = request.get_json()
        # 这里可以保存到数据库或配置文件
        return jsonify({'success': True, 'message': '配置已保存'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/config', methods=['GET'])
def get_config():
    return jsonify({'success': True, 'config': runtime.app_config})

@bp.route('/api/config', methods=['PUT'])
def update_config():
    try:
        data = request.get_json()
        changed_keys = set(data.keys()) & {
            'library_watch_enabled', 'auto_scan_on_startup',
            'scan_directories', 'watch_poll_interval', 'supported_formats',
        }
        for k, v in data.items():
            runtime.app_config[k] = v
        if save_config(runtime.app_config):
            log.maintenance('INFO', f"更新配置文件: {list(data.keys())}")
            # 与资源库扫描相关的开关变更时，重建监控器/触发扫描（后台执行，避免阻塞响应）
            if changed_keys:
                try:
                    import threading as _tw
                    from backend.library_helpers import _restart_library_watchers, _initial_library_scan

                    def _apply_scan_config():
                        try:
                            _restart_library_watchers()
                            if runtime.app_config.get('auto_scan_on_startup', True):
                                _initial_library_scan()
                        except Exception as _e:
                            log.debug('ERROR', f'应用扫描配置失败: {_e}')

                    _tw.Thread(target=_apply_scan_config, daemon=True,
                               name='apply-scan-config').start()
                except Exception as _e:
                    log.debug('ERROR', f'应用扫描配置失败: {_e}')
            return jsonify({'success': True, 'config': runtime.app_config})
        return jsonify({'success': False, 'message': '保存失败'}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/status')
def status():
    try:
        # 获取用户权限过滤后的视频数量
        allowed_library_ids = get_allowed_library_ids()
        
        if allowed_library_ids:
            # 过滤：library_id 为 NULL（主数据库的视频）或在允许的资源库中
            filtered_query = Video.query.filter(
                (Video.library_id == None) |
                (Video.library_id.in_(allowed_library_ids))
            ).filter(Video.in_trash == False)
            video_count = filtered_query.count()
        else:
            # 未登录或无权限用户只能看到主数据库的视频
            video_count = Video.query.filter(Video.library_id == None, Video.in_trash == False).count()
        
        return jsonify({
            'success': True,
            'status': 'running',
            'database': {
                'videos': video_count,
                'tags': Tag.query.count()
            },
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500



@bp.route('/api/admin/users', methods=['GET'])
@admin_required
def get_admin_users():
    """获取用户列表（管理员）"""
    try:
        users = User.query.all()
        return jsonify({
            'success': True,
            'users': [{
                'id': u.id,
                'username': u.username,
                'role': u.role,
                'role_name': u.role_name,
                'created_at': u.created_at.isoformat() if u.created_at else None
            } for u in users]
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/users', methods=['POST'])
@admin_required
def create_admin_user():
    """创建新用户（管理员）"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        role_str = data.get('role', 'user')
        
        # 将字符串角色转换为数字
        role_map = {
            'guest': UserRole.GUEST,
            'user': UserRole.USER,
            'admin': UserRole.ADMIN,
            'root': UserRole.ROOT
        }
        role = role_map.get(role_str, UserRole.USER)

        # ROOT 账号仅允许 ROOT 创建，防止普通管理员越权提权
        if role == UserRole.ROOT and g.role > UserRole.ROOT:
            return jsonify({'success': False, 'message': '只有超级管理员可以创建超级管理员账号'}), 403

        if not username or not password:
            return jsonify({'success': False, 'message': '用户名和密码不能为空'}), 400
        
        if User.query.filter_by(username=username).first():
            return jsonify({'success': False, 'message': '用户名已存在'}), 400
        
        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        log.maintenance('INFO', f"创建用户: {username} (角色: {user.role_name})")
        log_operation('create user', target=username, detail=f'角色={user.role_name}', success=True)
        
        return jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'role': user.role,
                'role_name': user.role_name
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/users/<int:user_id>', methods=['PUT'])
@admin_required
def update_admin_user(user_id):
    """更新用户信息（管理员）"""
    try:
        user = User.query.get_or_404(user_id)
        data = request.get_json()

        # 更新用户名
        if 'username' in data:
            new_username = data['username'].strip()
            if not new_username:
                return jsonify({'success': False, 'message': '用户名不能为空'}), 400
            # 检查用户名是否已被其他用户占用
            existing_user = User.query.filter_by(username=new_username).first()
            if existing_user and existing_user.id != user_id:
                return jsonify({'success': False, 'message': '用户名已存在'}), 400
            user.username = new_username

        # 更新角色
        if 'role' in data:
            role_map = {
                'guest': UserRole.GUEST,
                'user': UserRole.USER,
                'admin': UserRole.ADMIN,
                'root': UserRole.ROOT
            }
            new_role = role_map.get(data['role'], UserRole.USER)
            # ROOT 账号仅允许 ROOT 修改
            if user.role == UserRole.ROOT and g.role > UserRole.ROOT:
                return jsonify({'success': False, 'message': '只有超级管理员可以修改超级管理员账号'}), 403
            # 禁止普通管理员把任意账号提权为 ROOT
            if new_role == UserRole.ROOT and g.role > UserRole.ROOT:
                return jsonify({'success': False, 'message': '只有超级管理员可以设置超级管理员角色'}), 403
            user.role = new_role

        # 更新密码（如果提供了）
        if data.get('password'):
            user.set_password(data['password'])

        db.session.commit()
        log.maintenance('INFO', f"更新用户信息: {user.username} (ID: {user_id})")
        log_operation('update user', target=user.username, detail=f'角色={user.role_name}', success=True)

        return jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'role': user.role,
                'role_name': user.role_name
            }
        })
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"更新用户信息失败: {user_id}, {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_admin_user(user_id):
    """删除用户（管理员）"""
    try:
        user = User.query.get_or_404(user_id)
        # ROOT 账号仅允许 ROOT 删除
        if user.role == UserRole.ROOT and g.role > UserRole.ROOT:
            return jsonify({'success': False, 'message': '只有超级管理员可以删除超级管理员账号'}), 403
        if user.id == g.user_id:
            return jsonify({'success': False, 'message': '不能删除当前登录用户'}), 400
        db.session.delete(user)
        db.session.commit()
        log.maintenance('INFO', f"删除用户: {user.username} (ID: {user_id})")
        log_operation('delete user', target=user.username, success=True)
        return jsonify({'success': True, 'message': '用户已删除'})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"删除用户失败: {user_id}, {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


def _effective_library_perm(user, library_id):
    """返回用户对某库的实际生效权限级别：'none'/'read'/'write'/'admin'/'full'。

    管理员(role<=ADMIN，数值越小权限越高)对激活库恒为 'full'；普通用户取直接授权/用户组授权/通用授权中
    最高的一档（admin > write > read；custom 按 permissions 推断，这里简化为 read/write）。
    """
    if user.role <= UserRole.ADMIN:
        lib = ResourceLibrary.query.get(library_id)
        if lib and lib.is_active:
            return 'full'
    best = None
    perms = list(LibraryPermission.query.filter_by(user_id=user.id).all())
    for m in LibraryUserGroupMember.query.filter_by(user_id=user.id).all():
        perms.extend(LibraryPermission.query.filter_by(group_id=m.group_id).all())
    perms.extend(LibraryPermission.query.filter_by(user_id=None).all())
    # 显式拒绝（access_level='none'）优先级最高：覆盖通用/用户组授权
    for p in perms:
        if p.library_id == library_id and (p.access_level or 'read') == 'none':
            return 'none'
    rank = {'read': 1, 'write': 2, 'admin': 3}
    for p in perms:
        if p.library_id != library_id:
            continue
        lvl = p.access_level or 'read'
        if lvl == 'custom':
            lvl = 'write' if _perm_allows_write(p) else 'read'
        r = rank.get(lvl, 1)
        if best is None or r > rank.get(best, 1):
            best = lvl
    if best == 'admin':
        return 'admin'
    if best == 'write':
        return 'write'
    if best == 'read':
        return 'read'
    return 'none'


@bp.route('/api/admin/users/<int:user_id>/library-permissions', methods=['GET'])
@admin_required
def get_user_library_permissions(user_id):
    """获取指定用户对全部资源库的读写权限（仅直接授权 + 用户组授权，不含管理员默认全权）。"""
    try:
        user = User.query.get_or_404(user_id)
        libraries = ResourceLibrary.query.filter_by(is_active=True).order_by(ResourceLibrary.id).all()
        # 该用户已有的直接授权记录（用于区分"无"与"有记录但仅通用授权"）
        direct = {p.library_id: p for p in LibraryPermission.query.filter_by(user_id=user.id).all()}
        data = [{
            'library_id': lib.id,
            'library_name': lib.name,
            'effective': _effective_library_perm(user, lib.id),
            'direct_level': direct.get(lib.id).access_level if lib.id in direct else None,
        } for lib in libraries]
        return jsonify({
            'success': True,
            'is_admin': user.role <= UserRole.ADMIN,
            'libraries': data,
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/admin/users/<int:user_id>/library-permissions', methods=['POST'])
@admin_required
def set_user_library_permissions(user_id):
    """批量设置指定用户对各资源库的读写权限。

    body: { permissions: [ { library_id, level } ] }  level ∈ 'none'|'read'|'write'
    仅修改该用户的「直接授权」记录。'none' 表示显式拒绝该用户访问该库：写入一条
    access_level='none' 的直接授权（而非仅删除），以覆盖「通用授权(user_id=NULL) /
    用户组授权」，否则对通过通用/组授权获得该库权限的用户，撤回直接授权无效。
    管理员(role<=ADMIN，数值越小权限越高)对所有激活库默认可读写，不允许通过此接口改降。
    """
    try:
        user = User.query.get_or_404(user_id)
        if user.role <= UserRole.ADMIN:
            return jsonify({'success': False, 'message': '管理员默认拥有全部资源库权限，无需单独设置'}), 400
        data = request.get_json(silent=True) or {}
        items = data.get('permissions', [])
        if not isinstance(items, list):
            return jsonify({'success': False, 'message': 'permissions 必须是数组'}), 400

        allowed = {'none', 'read', 'write'}
        for item in items:
            lid = item.get('library_id')
            level = item.get('level')
            if lid is None or level not in allowed:
                return jsonify({'success': False, 'message': '无效的 library_id 或 level'}), 400
            lib = ResourceLibrary.query.get(lid)
            if not lib or not lib.is_active:
                return jsonify({'success': False, 'message': f'资源库不存在或未激活: {lid}'}), 400

        # 一次性覆盖：先删除该用户现有直接授权，再按请求重建
        LibraryPermission.query.filter_by(user_id=user.id).delete()
        for item in items:
            lid = item['library_id']
            level = item['level']
            if level == 'none':
                # 显式拒绝：写入 access_level='none' 的直接授权，覆盖通用/用户组授权。
                # 仅「删除直接授权」无法撤销库 p 这类由通用授权(user_id=NULL)授予的可见性。
                db.session.add(LibraryPermission(
                    user_id=user.id,
                    library_id=lid,
                    access_level='none',
                    created_by=g.user_id,
                ))
                continue
            db.session.add(LibraryPermission(
                user_id=user.id,
                library_id=lid,
                access_level=level,
                created_by=g.user_id,
            ))
        db.session.commit()
        log.maintenance('INFO', f"更新用户资源库权限: {user.username} (ID: {user_id})")
        log_operation('update user library permissions', target=user.username, success=True)
        return jsonify({'success': True, 'message': '资源库权限已更新'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
