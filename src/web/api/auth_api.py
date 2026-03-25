"""
用户认证API接口
提供注册、登录、登出、用户信息等接口
"""
from flask import Blueprint, request, jsonify, session
from core.models import db, User, UserRole, ROLE_NAMES
from auth_service import AuthService
from functools import wraps
from liblog import get_module_logger
log = get_module_logger()

# 创建蓝图
auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not AuthService.is_logged_in():
            return jsonify({
                'success': False,
                'message': '请先登录',
                'error_code': 'AUTH_REQUIRED'
            }), 401
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """管理员权限验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not AuthService.is_logged_in():
            return jsonify({
                'success': False,
                'message': '请先登录',
                'error_code': 'AUTH_REQUIRED'
            }), 401
        if not AuthService.is_admin():
            return jsonify({
                'success': False,
                'message': '权限不足',
                'error_code': 'PERMISSION_DENIED'
            }), 403
        return f(*args, **kwargs)
    return decorated_function


def root_required(f):
    """超级管理员权限验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not AuthService.is_logged_in():
            return jsonify({
                'success': False,
                'message': '请先登录',
                'error_code': 'AUTH_REQUIRED'
            }), 401
        if not AuthService.is_root():
            return jsonify({
                'success': False,
                'message': '需要超级管理员权限',
                'error_code': 'ROOT_REQUIRED'
            }), 403
        return f(*args, **kwargs)
    return decorated_function


@auth_bp.route('/register', methods=['POST'])
def register():
    """用户注册
    
    请求体:
        {
            "username": "用户名",
            "password": "密码",
            "email": "邮箱（可选）"
        }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': '无效的请求数据'}), 400

        username = data.get('username', '').strip()
        password = data.get('password', '')
        email = data.get('email', '').strip() or None

        # 验证用户名
        if not username:
            return jsonify({'success': False, 'message': '用户名不能为空'}), 400
        if len(username) < 3 or len(username) > 50:
            return jsonify({'success': False, 'message': '用户名长度应为3-50个字符'}), 400

        # 验证密码
        if not password:
            return jsonify({'success': False, 'message': '密码不能为空'}), 400
        if len(password) < 6:
            return jsonify({'success': False, 'message': '密码长度至少6个字符'}), 400

        # 验证邮箱格式
        if email and '@' not in email:
            return jsonify({'success': False, 'message': '邮箱格式不正确'}), 400

        # 注册用户
        success, message, user = AuthService.register(
            username=username,
            password=password,
            email=email
        )

        if success:
            return jsonify({
                'success': True,
                'message': message,
                'user': user.to_dict()
            }), 201
        else:
            return jsonify({'success': False, 'message': message}), 400

    except Exception as e:
        log.debug('ERROR', f"注册失败: {e}")
        return jsonify({'success': False, 'message': f'注册失败: {str(e)}'}), 500


@auth_bp.route('/login', methods=['POST'])
def login():
    """用户登录（v1版本 - session认证）"""
    print("=== auth_bp.login 被调用 ===")

    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': '无效的请求数据'}), 400

        username = data.get('username', '').strip()
        password = data.get('password', '')
        remember = data.get('remember', True)  # 默认为True，保存长久token

        if not username or not password:
            return jsonify({'success': False, 'message': '用户名和密码不能为空'}), 400

        success, message, user = AuthService.login(
            username=username,
            password=password,
            remember=remember
        )

        if success:
            return jsonify({
                'success': True,
                'message': message,
                'user': user.to_dict()
            })
        else:
            return jsonify({'success': False, 'message': message}), 401

    except Exception as e:
        log.debug('ERROR', f"登录失败: {e}")
        return jsonify({'success': False, 'message': f'登录失败: {str(e)}'}), 500


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """用户登出"""
    try:
        AuthService.logout()
        return jsonify({
            'success': True,
            'message': '已退出登录'
        })
    except Exception as e:
        log.debug('ERROR', f"登出失败: {e}")
        return jsonify({'success': False, 'message': f'登出失败: {str(e)}'}), 500


@auth_bp.route('/me', methods=['GET'])
def get_current_user():
    """获取当前登录用户信息"""
    try:
        user = AuthService.get_current_user()
        if user:
            return jsonify({
                'success': True,
                'user': user.to_dict(),
                'is_logged_in': True
            })
        else:
            return jsonify({
                'success': True,
                'user': None,
                'is_logged_in': False,
                'role': UserRole.GUEST,
                'role_name': ROLE_NAMES[UserRole.GUEST]
            })
    except Exception as e:
        log.debug('ERROR', f"获取用户信息失败: {e}")
        return jsonify({'success': False, 'message': f'获取用户信息失败: {str(e)}'}), 500


@auth_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    """修改密码
    
    请求体:
        {
            "old_password": "旧密码",
            "new_password": "新密码"
        }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': '无效的请求数据'}), 400

        old_password = data.get('old_password', '')
        new_password = data.get('new_password', '')

        if not old_password or not new_password:
            return jsonify({'success': False, 'message': '旧密码和新密码不能为空'}), 400

        if len(new_password) < 6:
            return jsonify({'success': False, 'message': '新密码长度至少6个字符'}), 400

        user = AuthService.get_current_user()
        success, message = AuthService.change_password(
            user_id=user.id,
            old_password=old_password,
            new_password=new_password
        )

        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'message': message}), 400

    except Exception as e:
        log.debug('ERROR', f"修改密码失败: {e}")
        return jsonify({'success': False, 'message': f'修改密码失败: {str(e)}'}), 500


@auth_bp.route('/check-permission', methods=['POST'])
def check_permission():
    """检查权限
    
    请求体:
        {
            "required_role": 1  // 需要的角色级别
        }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': '无效的请求数据'}), 400

        required_role = data.get('required_role', 0)
        has_permission = AuthService.check_permission(required_role)

        return jsonify({
            'success': True,
            'has_permission': has_permission,
            'current_role': AuthService.get_current_role(),
            'required_role': required_role
        })

    except Exception as e:
        log.debug('ERROR', f"检查权限失败: {e}")
        return jsonify({'success': False, 'message': f'检查权限失败: {str(e)}'}), 500


# ==================== 用户管理API（管理员及以上） ====================

@auth_bp.route('/users', methods=['GET'])
@admin_required
def list_users():
    """获取用户列表（管理员及以上）
    
    查询参数:
        page: 页码（默认1）
        per_page: 每页数量（默认20）
        role: 按角色筛选（可选）
        search: 搜索用户名（可选）
    """
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        role_filter = request.args.get('role', type=int)
        search = request.args.get('search', '').strip()

        # 构建查询
        query = User.query

        if role_filter is not None:
            query = query.filter(User.role == role_filter)

        if search:
            query = query.filter(User.username.contains(search))

        # 分页
        pagination = query.order_by(User.created_at.desc()).paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )

        users = [user.to_dict() for user in pagination.items]

        return jsonify({
            'success': True,
            'users': users,
            'total': pagination.total,
            'pages': pagination.pages,
            'current_page': page
        })

    except Exception as e:
        log.debug('ERROR', f"获取用户列表失败: {e}")
        return jsonify({'success': False, 'message': f'获取用户列表失败: {str(e)}'}), 500


@auth_bp.route('/users/<int:user_id>', methods=['GET'])
@admin_required
def get_user(user_id):
    """获取用户详情（管理员及以上）"""
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

        return jsonify({
            'success': True,
            'user': user.to_dict(include_sensitive=True)
        })

    except Exception as e:
        log.debug('ERROR', f"获取用户详情失败: {e}")
        return jsonify({'success': False, 'message': f'获取用户详情失败: {str(e)}'}), 500


@auth_bp.route('/users', methods=['POST'])
@admin_required
def create_user():
    """创建用户（管理员及以上）
    
    请求体:
        {
            "username": "用户名",
            "password": "密码",
            "email": "邮箱（可选）",
            "role": 1  // 角色级别
        }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': '无效的请求数据'}), 400

        username = data.get('username', '').strip()
        password = data.get('password', '')
        email = data.get('email', '').strip() or None
        role = data.get('role', UserRole.USER)

        # 验证
        if not username or not password:
            return jsonify({'success': False, 'message': '用户名和密码不能为空'}), 400

        if len(password) < 6:
            return jsonify({'success': False, 'message': '密码长度至少6个字符'}), 400

        # 检查权限：只有root可以创建管理员和root用户
        current_user = AuthService.get_current_user()
        if role >= UserRole.ADMIN and not current_user.is_root():
            return jsonify({
                'success': False,
                'message': '只有超级管理员可以创建管理员账户'
            }), 403

        # 只有root可以创建root用户
        if role == UserRole.ROOT and not current_user.is_root():
            return jsonify({
                'success': False,
                'message': '只有超级管理员可以创建超级管理员账户'
            }), 403
        
        # root账号唯一性检查：系统中只能有一个root用户
        if role == UserRole.ROOT:
            existing_root = User.query.filter_by(role=UserRole.ROOT).first()
            if existing_root:
                return jsonify({
                    'success': False,
                    'message': '系统中已存在超级管理员账户，只能有一个root账号'
                }), 403

        success, message, user = AuthService.register(
            username=username,
            password=password,
            email=email,
            role=role
        )

        if success:
            return jsonify({
                'success': True,
                'message': message,
                'user': user.to_dict()
            }), 201
        else:
            return jsonify({'success': False, 'message': message}), 400

    except Exception as e:
        log.debug('ERROR', f"创建用户失败: {e}")
        return jsonify({'success': False, 'message': f'创建用户失败: {str(e)}'}), 500


@auth_bp.route('/users/<int:user_id>', methods=['PUT'])
@admin_required
def update_user(user_id):
    """更新用户信息（管理员及以上）
    
    请求体:
        {
            "email": "邮箱（可选）",
            "role": 1,  // 角色级别（可选）
            "is_active": true  // 是否激活（可选）
        }
    """
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': '无效的请求数据'}), 400

        current_user = AuthService.get_current_user()

        # 更新邮箱
        if 'email' in data:
            email = data['email'].strip() or None
            if email and email != user.email:
                if User.query.filter(User.email == email, User.id != user_id).first():
                    return jsonify({'success': False, 'message': '邮箱已被使用'}), 400
                user.email = email

        # 更新角色
        if 'role' in data:
            new_role = data['role']

            # 只有root可以修改角色为管理员及以上
            if new_role >= UserRole.ADMIN and not current_user.is_root():
                return jsonify({
                    'success': False,
                    'message': '只有超级管理员可以设置管理员角色'
                }), 403

            # 不能修改root用户的角色（除非是root自己）
            if user.is_root() and not current_user.is_root():
                return jsonify({
                    'success': False,
                    'message': '不能修改超级管理员的角色'
                }), 403

            # root不能将自己的角色降级
            if user.id == current_user.id and new_role < UserRole.ROOT:
                return jsonify({
                    'success': False,
                    'message': '不能降低自己的角色权限'
                }), 400
            
            # root账号唯一性检查：不能将其他用户升级为root
            if new_role == UserRole.ROOT and not user.is_root():
                existing_root = User.query.filter_by(role=UserRole.ROOT).first()
                if existing_root:
                    return jsonify({
                        'success': False,
                        'message': '系统中已存在超级管理员账户，只能有一个root账号'
                    }), 403

            user.role = new_role

        # 更新激活状态
        if 'is_active' in data:
            is_active = data['is_active']

            # 不能禁用root用户（除非是root自己）
            if user.is_root() and not is_active and not current_user.is_root():
                return jsonify({
                    'success': False,
                    'message': '不能禁用超级管理员账户'
                }), 403

            # 不能禁用自己
            if user.id == current_user.id and not is_active:
                return jsonify({
                    'success': False,
                    'message': '不能禁用自己的账户'
                }), 400

            user.is_active = is_active

        db.session.commit()

        log.runtime('INFO', f"用户信息已更新: {user.username} by {current_user.username}")
        return jsonify({
            'success': True,
            'message': '用户信息已更新',
            'user': user.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"更新用户信息失败: {e}")
        return jsonify({'success': False, 'message': f'更新用户信息失败: {str(e)}'}), 500


@auth_bp.route('/users/<int:user_id>', methods=['DELETE'])
@root_required
def delete_user(user_id):
    """删除用户（仅超级管理员）
    
    注意：删除用户是不可逆操作
    """
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

        current_user = AuthService.get_current_user()

        # 不能删除自己
        if user.id == current_user.id:
            return jsonify({
                'success': False,
                'message': '不能删除自己的账户'
            }), 400

        # 不能删除root用户
        if user.is_root():
            return jsonify({
                'success': False,
                'message': '不能删除超级管理员账户'
            }), 403

        username = user.username
        db.session.delete(user)
        db.session.commit()

        log.runtime('INFO', f"用户已删除: {username} by {current_user.username}")
        return jsonify({
            'success': True,
            'message': f'用户 {username} 已删除'
        })

    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"删除用户失败: {e}")
        return jsonify({'success': False, 'message': f'删除用户失败: {str(e)}'}), 500


@auth_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@admin_required
def reset_user_password(user_id):
    """重置用户密码（管理员及以上）
    
    请求体:
        {
            "new_password": "新密码"
        }
    """
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': '无效的请求数据'}), 400

        new_password = data.get('new_password', '')
        if not new_password or len(new_password) < 6:
            return jsonify({'success': False, 'message': '密码长度至少6个字符'}), 400

        current_user = AuthService.get_current_user()

        # 只有root可以重置管理员密码
        if user.is_admin_or_above() and not current_user.is_root():
            return jsonify({
                'success': False,
                'message': '只有超级管理员可以重置管理员密码'
            }), 403

        user.set_password(new_password)
        db.session.commit()

        log.runtime('INFO', f"用户密码已重置: {user.username} by {current_user.username}")
        return jsonify({
            'success': True,
            'message': f'用户 {user.username} 的密码已重置'
        })

    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"重置用户密码失败: {e}")
        return jsonify({'success': False, 'message': f'重置密码失败: {str(e)}'}), 500


@auth_bp.route('/stats', methods=['GET'])
@admin_required
def user_stats():
    """获取用户统计信息（管理员及以上）"""
    try:
        from sqlalchemy import func

        # 统计各角色用户数量
        role_stats = db.session.query(
            User.role,
            func.count(User.id)
        ).group_by(User.role).all()

        stats = {
            'total': User.query.count(),
            'active': User.query.filter_by(is_active=True).count(),
            'by_role': {role: count for role, count in role_stats}
        }

        return jsonify({
            'success': True,
            'stats': stats
        })

    except Exception as e:
        log.debug('ERROR', f"获取用户统计失败: {e}")
        return jsonify({'success': False, 'message': f'获取统计失败: {str(e)}'}), 500
