# -*- coding: utf-8 -*-
"""JWT 工具（中立能力）。

与主 Web 服务使用相同的密钥与算法（HS256 + DBOX_JWT_SECRET），
供扩展宿主、下载器等独立进程校验主服务下发的 Bearer 令牌，实现跨进程鉴权一致。

不依赖 Flask 或任何业务模块，仅依赖 authlib（与主服务一致）。
"""
import os
import logging

from authlib.jose import jwt

logger = logging.getLogger('dbox-shared-jwt')

DEFAULT_SECRET = 'dbox-jwt-secret-key-change-in-production-2024'
ALGORITHM = 'HS256'


def get_secret() -> str:
    """读取与主服务一致的 JWT 密钥（环境变量优先）。"""
    return os.environ.get('DBOX_JWT_SECRET', DEFAULT_SECRET)


def decode_token(token: str, secret: str = None) -> dict:
    """解码并校验 JWT，返回 payload；失败返回 None。"""
    secret = secret or get_secret()
    try:
        return jwt.decode(token, secret)
    except Exception as e:
        logger.debug('Token 校验失败: %s', e)
        return None


def verify_access(token: str, secret: str = None) -> dict:
    """校验访问令牌，要求 type=='access' 且未过期，返回 payload 或 None。"""
    payload = decode_token(token, secret)
    if not payload:
        return None
    if payload.get('type') != 'access':
        return None
    return payload


def role_of(token: str, secret: str = None) -> int:
    """返回令牌中的角色等级（数值越小权限越高：0=ROOT,1=ADMIN,2=USER,3=GUEST）；无效返回 -1。"""
    payload = verify_access(token, secret)
    if not payload:
        return -1
    return int(payload.get('role', 3) or 3)  # 3 = GUEST，未登录默认最低权限


def user_id_of(token: str, secret: str = None) -> int:
    """返回令牌中的用户 ID；无效返回 None。"""
    payload = verify_access(token, secret)
    if not payload:
        return None
    return payload.get('user_id')
