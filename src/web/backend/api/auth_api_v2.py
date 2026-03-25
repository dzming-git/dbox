# 认证API v2 - JWT认证（前后端分离版本）
from flask import Blueprint, request, jsonify, current_app
from core.models import db, User, UserSession
from backend.utils.jwt_authlib import create_access_token, create_refresh_token, verify_token, auth_required
from backend.utils.validators import validate_username, validate_password, validate_email
from authlib.common.security import generate_token
import datetime
from liblog import get_module_logger
log = get_module_logger()

auth_v2_bp = Blueprint('auth_v2', __name__, url_prefix='/api/v2/auth')

@auth_v2_bp.route('/register', methods=['POST'])
def register():
    """用户注册（v2版本 - 返回JWT token）"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'data': None,
                'message': '请求数据不能为空',
                'code': 400
            }), 400
        
        username = data.get('username', '').strip()
        password = data.get('password', '')
        email = data.get('email', '').strip() or None
        
        # 验证数据
        is_valid, error_msg = validate_username(username)
        if not is_valid:
            return jsonify({
                'success': False,
                'data': None,
                'message': error_msg,
                'code': 400
            }), 400
        
        is_valid, error_msg = validate_password(password)
        if not is_valid:
            return jsonify({
                'success': False,
                'data': None,
                'message': error_msg,
                'code': 400
            }), 400
        
        if email:
            is_valid, error_msg = validate_email(email)
            if not is_valid:
                return jsonify({
                    'success': False,
                    'data': None,
                    'message': error_msg,
                    'code': 400
                }), 400
        
        # 检查用户是否存在
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            return jsonify({
                'success': False,
                'data': None,
                'message': '用户名已存在',
                'code': 400
            }), 400
        
        if email:
            existing_email = User.query.filter_by(email=email).first()
            if existing_email:
                return jsonify({
                    'success': False,
                    'data': None,
                    'message': '邮箱已被使用',
                    'code': 400
                }), 400
        
        # 创建用户
        user = User(
            username=username,
            email=email,
            role=1,  # 默认为普通用户
            is_active=True,
            created_at=datetime.datetime.utcnow()
        )
        user.set_password(password)  # 使用User模型的方法设置密码
        db.session.add(user)
        db.session.commit()
        
        # 生成token
        access_token = create_access_token(user.id, user.role, user.username)
        refresh_token = create_refresh_token(user.id)
        
        # 创建会话记录
        session = UserSession(
            user_id=user.id,
            session_token=refresh_token,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', ''),
            expires_at=datetime.datetime.utcnow() + datetime.timedelta(days=7),
            created_at=datetime.datetime.utcnow()
        )
        db.session.add(session)
        db.session.commit()
        
        log.runtime('INFO', f"新用户注册成功: {username}")
        
        return jsonify({
            'success': True,
            'data': {
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'role': user.role,
                    'role_name': get_role_name(user.role),
                    'created_at': user.created_at.isoformat() if user.created_at else None
                },
                'access_token': access_token,
                'refresh_token': refresh_token,
                'token_type': 'Bearer'
            },
            'message': '注册成功',
            'code': 201
        }), 201
        
    except Exception as e:
        log.debug('ERROR', f"注册失败: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({
            'success': False,
            'data': None,
            'message': f'注册失败: {str(e)}',
            'code': 500
        }), 500


@auth_v2_bp.route('/login', methods=['POST'])
def login():
    """用户登录（v2版本 - 返回JWT token）"""
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                'success': False,
                'data': None,
                'message': '请求数据不能为空',
                'code': 400
            }), 400

        username = data.get('username', '').strip()
        password = data.get('password', '')

        # 验证数据
        if not username or not password:
            return jsonify({
                'success': False,
                'data': None,
                'message': '用户名和密码不能为空',
                'code': 400
            }), 400

        # 查找用户
        user = User.query.filter_by(username=username).first()
        if not user:
            log.debug('WARN', f"登录失败 - 用户不存在: {username}")
            return jsonify({
                'success': False,
                'data': None,
                'message': '用户名或密码错误',
                'code': 401
            }), 401

        # 验证密码
        if not user.check_password(password):
            log.debug('WARN', f"登录失败 - 密码错误: {username}")
            return jsonify({
                'success': False,
                'data': None,
                'message': '用户名或密码错误',
                'code': 401
            }), 401

        if not user.is_active:
            log.debug('WARN', f"登录失败 - 账号已禁用: {username}")
            return jsonify({
                'success': False,
                'data': None,
                'message': '账号已被禁用',
                'code': 403
            }), 403
        
        # 生成token
        access_token = create_access_token(user.id, user.role, user.username)
        refresh_token = create_refresh_token(user.id)
        
        # 更新用户最后登录时间
        user.last_login = datetime.datetime.utcnow()
        
        # 创建会话记录
        session = UserSession(
            user_id=user.id,
            session_token=refresh_token,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', ''),
            expires_at=datetime.datetime.utcnow() + datetime.timedelta(days=7),
            created_at=datetime.datetime.utcnow()
        )
        db.session.add(session)
        db.session.commit()
        
        log.runtime('INFO', f"用户登录成功: {username}")
        
        return jsonify({
            'success': True,
            'data': {
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'role': user.role,
                    'role_name': get_role_name(user.role),
                    'last_login': user.last_login.isoformat() if user.last_login else None
                },
                'access_token': access_token,
                'refresh_token': refresh_token,
                'token_type': 'Bearer'
            },
            'message': '登录成功',
            'code': 200
        })
        
    except Exception as e:
        log.debug('ERROR', f"登录失败: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'data': None,
            'message': f'登录失败: {str(e)}',
            'code': 500
        }), 500


@auth_v2_bp.route('/refresh', methods=['POST'])
def refresh_token():
    """刷新token"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'data': None,
                'message': '请求数据不能为空',
                'code': 400
            }), 400
        
        refresh_token_str = data.get('refresh_token')
        if not refresh_token_str:
            return jsonify({
                'success': False,
                'data': None,
                'message': 'refresh_token不能为空',
                'code': 400
            }), 400
        
        # 验证token
        payload = verify_token(refresh_token_str)
        if not payload or payload.get('type') != 'refresh':
            log.debug('WARN', "刷新token失败 - 无效的refresh_token")
            return jsonify({
                'success': False,
                'data': None,
                'message': '无效的刷新token',
                'code': 401
            }), 401
        
        # 验证会话是否存在且有效
        session = UserSession.query.filter_by(
            session_token=refresh_token_str,
            is_active=True
        ).first()
        
        if not session:
            log.debug('WARN', "刷新token失败 - 会话不存在或已过期")
            return jsonify({
                'success': False,
                'data': None,
                'message': '会话已过期，请重新登录',
                'code': 401
            }), 401
        
        user = User.query.get(session.user_id)
        if not user:
            log.debug('WARN', "刷新token失败 - 用户不存在")
            return jsonify({
                'success': False,
                'data': None,
                'message': '用户不存在',
                'code': 404
            }), 404
        
        if not user.is_active:
            log.debug('WARN', "刷新token失败 - 账号已禁用")
            return jsonify({
                'success': False,
                'data': None,
                'message': '账号已被禁用',
                'code': 403
            }), 403
        
        # 生成新的访问token
        access_token = create_access_token(user.id, user.role, user.username)
        
        log.runtime('INFO', f"刷新token成功: {user.username}")
        
        return jsonify({
            'success': True,
            'data': {
                'access_token': access_token,
                'token_type': 'Bearer'
            },
            'message': '刷新成功',
            'code': 200
        })
        
    except Exception as e:
        log.debug('ERROR', f"刷新token失败: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'data': None,
            'message': f'刷新失败: {str(e)}',
            'code': 500
        }), 500


@auth_v2_bp.route('/logout', methods=['POST'])
def logout():
    """用户登出"""
    try:
        data = request.get_json()
        refresh_token_str = data.get('refresh_token') if data else None
        
        # 如果提供了refresh_token，将对应的会话标记为无效
        if refresh_token_str:
            session = UserSession.query.filter_by(session_token=refresh_token_str).first()
            if session:
                session.is_active = False
                db.session.commit()
                log.runtime('INFO', f"用户登出成功（会话ID: {session.id}）")
        else:
            log.runtime('INFO', "用户登出成功（未提供refresh_token）")
        
        return jsonify({
            'success': True,
            'data': None,
            'message': '登出成功',
            'code': 200
        })
        
    except Exception as e:
        log.debug('ERROR', f"登出失败: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'data': None,
            'message': f'登出失败: {str(e)}',
            'code': 500
        }), 500


@auth_v2_bp.route('/me', methods=['GET'])
@auth_required
def get_current_user():
    """获取当前用户信息（需要JWT认证）"""
    from flask import g

    user_id = getattr(g, 'user_id', None)
    
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({
                'success': False,
                'data': None,
                'message': '用户不存在',
                'code': 404
            }), 404
        
        return jsonify({
            'success': True,
            'data': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': user.role,
                'role_name': get_role_name(user.role),
                'is_active': user.is_active,
                'created_at': user.created_at.isoformat() if user.created_at else None,
                'last_login': user.last_login.isoformat() if user.last_login else None
            },
            'code': 200
        })
        
    except Exception as e:
        log.debug('ERROR', f"获取用户信息失败: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'data': None,
            'message': f'获取用户信息失败: {str(e)}',
            'code': 500
        }), 500


def get_role_name(role: int) -> str:
    """获取角色名称"""
    role_names = {
        0: '访客',
        1: '普通用户',
        2: '管理员',
        3: '超级管理员'
    }
    return role_names.get(role, '未知')
