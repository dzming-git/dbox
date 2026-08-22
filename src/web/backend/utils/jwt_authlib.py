# JWT工具类 - 使用Authlib实现
from authlib.jose import jwt
import datetime
import os
import secrets
from functools import wraps
from flask import request, jsonify, g
from typing import Optional, Dict, Any
from liblog import get_service_logger
from core.models import UserRole
log = get_service_logger('dbox-web')

# JWT配置 - 从环境变量读取，生产环境必须设置 DBOX_JWT_SECRET
_DEFAULT_SECRET = 'dbox-jwt-secret-key-change-in-production-2024'
SECRET_KEY = os.environ.get('DBOX_JWT_SECRET', _DEFAULT_SECRET)
if SECRET_KEY == _DEFAULT_SECRET:
    log.debug('WARN', '[安全警告] 正在使用默认 JWT SECRET_KEY，生产环境请设置 DBOX_JWT_SECRET 环境变量')
ALGORITHM = 'HS256'
ACCESS_TOKEN_EXPIRE_HOURS = 24
REFRESH_TOKEN_EXPIRE_DAYS = 7


def create_access_token(user_id: int, role: int, username: str) -> str:
    """创建访问token"""
    expire = datetime.datetime.utcnow() + datetime.timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        'user_id': user_id,
        'role': role,
        'username': username,
        'exp': expire,
        'iat': datetime.datetime.utcnow(),
        'type': 'access'
    }
    header = {'alg': ALGORITHM}
    token = jwt.encode(header, payload, SECRET_KEY)
    # Authlib返回bytes，需要转换为str
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    return token


def create_refresh_token(user_id: int) -> str:
    """创建刷新token

    注意：payload 必须包含随机 jti，否则同一秒内重复登录会生成完全相同的
    JWT，而登录逻辑把它当作 user_sessions.session_token 写入，触发 UNIQUE
    冲突导致登录 500。加入随机 jti 后每次令牌唯一。
    """
    expire = datetime.datetime.utcnow() + datetime.timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        'user_id': user_id,
        'exp': expire,
        'iat': datetime.datetime.utcnow(),
        'type': 'refresh',
        'jti': secrets.token_hex(8)
    }
    header = {'alg': ALGORITHM}
    token = jwt.encode(header, payload, SECRET_KEY)
    # Authlib返回bytes，需要转换为str
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    return token


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """验证token"""
    try:
        payload = jwt.decode(token, SECRET_KEY)
        return payload
    except Exception as e:
        log.debug('WARN', f'Token验证失败: {e}')
        return None


def auth_required(f):
    """认证装饰器 - 需要登录"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 从请求头获取token
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({
                'success': False,
                'data': None,
                'message': '未提供认证token',
                'code': 401
            }), 401
        
        # 移除 'Bearer ' 前缀
        if token.startswith('Bearer '):
            token = token[7:]
        
        # 验证token
        payload = verify_token(token)
        if not payload:
            return jsonify({
                'success': False,
                'data': None,
                'message': '无效的token或token已过期',
                'code': 401
            }), 401
        
        # 检查token类型
        if payload.get('type') != 'access':
            return jsonify({
                'success': False,
                'data': None,
                'message': 'token类型错误',
                'code': 401
            }), 401
        
        # 将用户信息存储到g对象（role 从 DB 取最新值，避免 stale JWT role）
        g.user_id = payload.get('user_id')
        uid = payload.get('user_id')
        if uid:
            from core.models import User as _User
            _u = _User.query.get(uid)
            g.user_role = int(_u.role) if _u else payload.get('role')
        else:
            g.user_role = payload.get('role')
        g.username = payload.get('username')
        
        return f(*args, **kwargs)
    
    return decorated_function


def admin_required(f):
    """管理员权限装饰器 - 需要管理员权限（数值越小权限越高：ROOT=0,ADMIN=1,USER=2,GUEST=3）"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 检查用户角色
        user_role = getattr(g, 'user_role', 99)
        if user_role > UserRole.ADMIN:  # 高于 ADMIN(1) 即权限不足
            return jsonify({
                'success': False,
                'data': None,
                'message': '需要管理员权限',
                'code': 403
            }), 403

        return f(*args, **kwargs)

    return decorated_function


def root_required(f):
    """超级管理员权限装饰器 - 需要超级管理员权限"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 检查用户角色
        user_role = getattr(g, 'user_role', 99)
        if user_role > UserRole.ROOT:
            return jsonify({
                'success': False,
                'data': None,
                'message': '需要超级管理员权限',
                'code': 403
            }), 403
        
        return f(*args, **kwargs)
    
    return decorated_function
