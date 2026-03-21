# -*- coding: utf-8 -*-
"""
AuthMiddleware - 认证中间件

提供基于Token和Session的认证功能。
"""

import time
import hmac
import base64
from typing import Dict, Optional

from ..core import TaskContext


class AuthMiddleware:
    """
    认证中间件

    提供基于Token和Session的认证功能。
    """

    def __init__(self, secret_key: str = None):
        """
        初始化认证中间件

        Args:
            secret_key: 用于JWT签名的密钥
        """
        self._secret_key = secret_key or 'default-secret-key'
        self._token_cache = {}  # token -> user_id 映射

    def generate_token(self, user_id: str, expiry_seconds: int = 3600) -> str:
        """
        生成认证Token

        Args:
            user_id: 用户ID
            expiry_seconds: 过期时间（秒）

        Returns:
            Token字符串
        """
        expiry = int(time.time()) + expiry_seconds
        payload = f"{user_id}:{expiry}"

        # 简单HMAC签名
        signature = hmac.new(
            self._secret_key.encode(),
            payload.encode(),
            'sha256'
        ).hexdigest()[:16]

        token = base64.b64encode(f"{payload}:{signature}".encode()).decode()
        return token

    def verify_token(self, token: str) -> Optional[str]:
        """
        验证Token并返回用户ID

        Args:
            token: Token字符串

        Returns:
            用户ID，无效返回None
        """
        try:
            # 解码Token
            decoded = base64.b64decode(token.encode()).decode()
            parts = decoded.rsplit(':', 2)

            if len(parts) != 3:
                return None

            payload, _, signature = parts
            user_id, expiry_str = payload.rsplit(':', 1)
            expiry = int(expiry_str)

            # 检查是否过期
            if time.time() > expiry:
                return None

            # 验证签名
            expected_signature = hmac.new(
                self._secret_key.encode(),
                payload.encode(),
                'sha256'
            ).hexdigest()[:16]

            if not hmac.compare_digest(signature, expected_signature):
                return None

            return user_id

        except Exception:
            return None

    def extract_token_from_header(self, headers: Dict[str, str]) -> Optional[str]:
        """
        从请求头提取Token

        Args:
            headers: 请求头字典

        Returns:
            Token字符串
        """
        auth_header = headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            return auth_header[7:]
        return None

    def authenticate(self, context: TaskContext) -> Optional[str]:
        """
        认证请求

        Args:
            context: TaskContext

        Returns:
            用户ID，认证失败返回None
        """
        # 从请求头获取Token
        token = self.extract_token_from_header(context.headers)
        if token:
            user_id = self.verify_token(token)
            if user_id:
                return user_id

        # 尝试从Cookie获取
        cookie = context.headers.get('Cookie', '')
        if 'token=' in cookie:
            start = cookie.find('token=') + 6
            end = cookie.find(';', start) if ';' in cookie[start:] else len(cookie)
            token = cookie[start:end].strip()
            user_id = self.verify_token(token)
            if user_id:
                return user_id

        return None
