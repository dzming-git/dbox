# JWT工具类 - 使用Authlib实现
from authlib.jose import jwt
import datetime
from functools import wraps
from flask import request, jsonify, g
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

# JWT配置
SECRET_KEY = 'dplayer-jwt-secret-key-change-in-production-2024'
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
    """创建刷新token"""
    expire = datetime.datetime.utcnow() + datetime.timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        'user_id': user_id,
        'exp': expire,
        'iat': datetime.datetime.utcnow(),
        'type': 'refresh'
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
        logger.warning(f'Token验证失败: {e}')
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
        
        # 将用户信息存储到g对象
        g.user_id = payload.get('user_id')
        g.user_role = payload.get('role')
        g.username = payload.get('username')
        
        return f(*args, **kwargs)
    
    return decorated_function


def admin_required(f):
    """管理员权限装饰器 - 需要管理员权限"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 检查用户角色
        user_role = getattr(g, 'user_role', 0)
        if user_role < 2:  # 角色等级：0=访客, 1=普通用户, 2=管理员, 3=超级管理员
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
        user_role = getattr(g, 'user_role', 0)
        if user_role < 3:
            return jsonify({
                'success': False,
                'data': None,
                'message': '需要超级管理员权限',
                'code': 403
            }), 403
        
        return f(*args, **kwargs)
    
    return decorated_function
