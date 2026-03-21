# -*- coding: utf-8 -*-
"""
SessionManager - 会话管理器

提供基于内存的会话存储和管理功能。
"""

import threading
import time
import uuid
from typing import Dict, Any, Optional


class SessionManager:
    """
    会话管理器

    提供基于内存的会话存储和管理功能。
    """

    def __init__(self, max_sessions: int = 1000, session_timeout: int = 3600):
        """
        初始化会话管理器

        Args:
            max_sessions: 最大会话数
            session_timeout: 会话超时时间（秒）
        """
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._max_sessions = max_sessions
        self._session_timeout = session_timeout
        self._session_counter = 0

    def create_session(self, user_id: str, data: Dict[str, Any] = None) -> str:
        """
        创建新会话

        Args:
            user_id: 用户ID
            data: 初始会话数据

        Returns:
            session_id
        """
        session_id = str(uuid.uuid4())

        with self._lock:
            # 如果会话已满，清理过期会话
            if len(self._sessions) >= self._max_sessions:
                self._cleanup_expired()

            self._sessions[session_id] = {
                'user_id': user_id,
                'data': data or {},
                'created_at': time.time(),
                'last_accessed': time.time(),
                'ip_address': None,
                'user_agent': None
            }
            self._session_counter += 1

        return session_id

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取会话

        Args:
            session_id: 会话ID

        Returns:
            会话数据，不存在返回None
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None

            # 检查是否过期
            if time.time() - session['last_accessed'] > self._session_timeout:
                self.delete_session(session_id)
                return None

            # 更新最后访问时间
            session['last_accessed'] = time.time()
            return session

    def update_session(self, session_id: str, data: Dict[str, Any]) -> bool:
        """
        更新会话数据

        Args:
            session_id: 会话ID
            data: 要更新的数据

        Returns:
            是否成功
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            session['data'].update(data)
            session['last_accessed'] = time.time()
            return True

    def delete_session(self, session_id: str) -> bool:
        """
        删除会话

        Args:
            session_id: 会话ID

        Returns:
            是否成功
        """
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False

    def _cleanup_expired(self):
        """清理过期会话"""
        now = time.time()
        expired = [
            sid for sid, session in self._sessions.items()
            if now - session['last_accessed'] > self._session_timeout
        ]
        for sid in expired:
            del self._sessions[sid]

    def get_stats(self) -> Dict[str, Any]:
        """获取会话统计"""
        with self._lock:
            return {
                'total_sessions': len(self._sessions),
                'max_sessions': self._max_sessions,
                'session_timeout': self._session_timeout,
                'total_created': self._session_counter
            }
