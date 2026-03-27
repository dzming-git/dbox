# -*- coding: utf-8 -*-
"""
用户管理模块 - 数据库模型
支持用户的增删改查、密码验证等操作
"""

import os
import sqlite3
import hashlib
import threading
import secrets
from contextlib import contextmanager
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum


class UserRole(int, Enum):
    """用户角色"""
    ROOT = 0      # 超级管理员
    ADMIN = 1     # 管理员
    USER = 2      # 普通用户
    GUEST = 3     # 访客


# 数据库路径（主数据库 - 复用 dplayer.db）
_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'databases')
_DB_PATH = os.path.join(_DB_DIR, 'dplayer.db')


def _ensure_db_dir():
    """确保数据库目录存在"""
    os.makedirs(_DB_DIR, exist_ok=True)


def hash_password(password: str, salt: Optional[str] = None) -> tuple:
    """
    密码哈希
    
    Returns:
        (hash, salt) 元组
    """
    if salt is None:
        salt = secrets.token_hex(16)
    pwd_hash = hashlib.sha256((salt + password).encode()).hexdigest()
    return pwd_hash, salt


def verify_password(password: str, pwd_hash: str, salt: str) -> bool:
    """验证密码"""
    computed, _ = hash_password(password, salt)
    return computed == pwd_hash


@dataclass
class User:
    """用户模型"""
    id: Optional[int] = None
    username: str = ""
    password_hash: str = ""
    password_salt: str = ""  # 密码盐
    role: UserRole = UserRole.USER
    email: str = ""
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = None

    def to_dict(self, include_password: bool = False) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            'id': self.id,
            'username': self.username,
            'role': self.role.value if isinstance(self.role, Enum) else self.role,
            'role_name': self.role.name if isinstance(self.role, Enum) else 'USER',
            'email': self.email,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
        }
        if include_password:
            result['password_hash'] = self.password_hash
            result['password_salt'] = self.password_salt
        return result

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'User':
        """从字典创建"""
        role = d.get('role', 2)
        if isinstance(role, str):
            role = UserRole[role.upper()].value if hasattr(UserRole, role.upper()) else int(role)
        
        return cls(
            id=d.get('id'),
            username=d.get('username', ''),
            password_hash=d.get('password_hash', ''),
            password_salt=d.get('password_salt', ''),
            role=UserRole(role) if isinstance(role, int) else role,
            email=d.get('email', ''),
            is_active=d.get('is_active', True),
            created_at=datetime.fromisoformat(d['created_at']) if d.get('created_at') else datetime.utcnow(),
            updated_at=datetime.fromisoformat(d['updated_at']) if d.get('updated_at') else datetime.utcnow(),
            last_login=datetime.fromisoformat(d['last_login']) if d.get('last_login') else None,
        )

    def check_password(self, password: str) -> bool:
        """验证密码"""
        return verify_password(password, self.password_hash, self.password_salt)

    def set_password(self, password: str):
        """设置密码"""
        self.password_hash, self.password_salt = hash_password(password)


class Database:
    """数据库管理器"""
    _local = threading.local()

    @classmethod
    def get_conn(cls) -> sqlite3.Connection:
        """获取线程本地连接"""
        if not hasattr(cls._local, 'conn') or cls._local.conn is None:
            _ensure_db_dir()
            cls._local.conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
            cls._local.conn.row_factory = sqlite3.Row
        return cls._local.conn

    @classmethod
    @contextmanager
    def get_cursor(cls):
        """获取游标的上下文管理器"""
        conn = cls.get_conn()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


class UserDB:
    """用户数据库操作"""

    @staticmethod
    def init_table():
        """确保 users 表存在（从 dplayer.db 复用）"""
        with Database.get_cursor() as cursor:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username VARCHAR(50) NOT NULL UNIQUE,
                    password_hash VARCHAR(256) NOT NULL,
                    role INTEGER NOT NULL DEFAULT 2,
                    email VARCHAR(120),
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    last_login DATETIME
                )
            ''')

            # 如果 password_salt 列不存在，添加它
            cursor.execute("PRAGMA table_info(users)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'password_salt' not in columns:
                cursor.execute('ALTER TABLE users ADD COLUMN password_salt VARCHAR(64) DEFAULT \'\'')

    @staticmethod
    def create(user: User) -> int:
        """创建用户"""
        UserDB.init_table()
        now = datetime.utcnow().isoformat()
        with Database.get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO users
                (username, password_hash, password_salt, role, email, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                user.username,
                user.password_hash,
                user.password_salt,
                user.role.value if isinstance(user.role, Enum) else user.role,
                user.email,
                1 if user.is_active else 0,
                now,
                now,
            ))
            return cursor.lastrowid

    @staticmethod
    def get_by_id(user_id: int) -> Optional[User]:
        """根据 ID 获取用户"""
        UserDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
            row = cursor.fetchone()
            if row:
                return User(
                    id=row['id'],
                    username=row['username'],
                    password_hash=row['password_hash'],
                    password_salt=row['password_salt'] or '',
                    role=UserRole(row['role']),
                    email=row['email'] or '',
                    is_active=bool(row['is_active']),
                    created_at=datetime.fromisoformat(row['created_at']),
                    updated_at=datetime.fromisoformat(row['updated_at']),
                    last_login=datetime.fromisoformat(row['last_login']) if row['last_login'] else None,
                )
            return None

    @staticmethod
    def get_by_username(username: str) -> Optional[User]:
        """根据用户名获取用户"""
        UserDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
            row = cursor.fetchone()
            if row:
                return User(
                    id=row['id'],
                    username=row['username'],
                    password_hash=row['password_hash'],
                    password_salt=row['password_salt'] or '',
                    role=UserRole(row['role']),
                    email=row['email'] or '',
                    is_active=bool(row['is_active']),
                    created_at=datetime.fromisoformat(row['created_at']),
                    updated_at=datetime.fromisoformat(row['updated_at']),
                    last_login=datetime.fromisoformat(row['last_login']) if row['last_login'] else None,
                )
            return None

    @staticmethod
    def get_all(include_inactive: bool = False) -> List[User]:
        """获取所有用户"""
        UserDB.init_table()
        with Database.get_cursor() as cursor:
            if include_inactive:
                cursor.execute('SELECT * FROM users ORDER BY id')
            else:
                cursor.execute('SELECT * FROM users WHERE is_active = 1 ORDER BY id')
            rows = cursor.fetchall()
            return [User(
                id=row['id'],
                username=row['username'],
                password_hash=row['password_hash'],
                password_salt=row['password_salt'] or '',
                role=UserRole(row['role']),
                email=row['email'] or '',
                is_active=bool(row['is_active']),
                created_at=datetime.fromisoformat(row['created_at']),
                updated_at=datetime.fromisoformat(row['updated_at']),
                last_login=datetime.fromisoformat(row['last_login']) if row['last_login'] else None,
            ) for row in rows]

    @staticmethod
    def update(user: User) -> bool:
        """更新用户"""
        UserDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute('''
                UPDATE users SET
                    username = ?, role = ?, email = ?, is_active = ?,
                    password_hash = ?, password_salt = ?,
                    updated_at = ?, last_login = ?
                WHERE id = ?
            ''', (
                user.username,
                user.role.value if isinstance(user.role, Enum) else user.role,
                user.email,
                1 if user.is_active else 0,
                user.password_hash,
                user.password_salt,
                datetime.utcnow().isoformat(),
                user.last_login.isoformat() if user.last_login else None,
                user.id,
            ))
            return cursor.rowcount > 0

    @staticmethod
    def delete(user_id: int) -> bool:
        """删除用户（软删除 - 设置 is_active=0）"""
        UserDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute('''
                UPDATE users SET is_active = 0, updated_at = ?
                WHERE id = ?
            ''', (datetime.utcnow().isoformat(), user_id))
            return cursor.rowcount > 0

    @staticmethod
    def hard_delete(user_id: int) -> bool:
        """硬删除用户（不可恢复）"""
        UserDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
            return cursor.rowcount > 0

    @staticmethod
    def verify_login(username: str, password: str) -> Optional[User]:
        """验证登录"""
        user = UserDB.get_by_username(username)
        if not user:
            return None
        if not user.is_active:
            return None
        if user.check_password(password):
            # 更新最后登录时间
            user.last_login = datetime.utcnow()
            UserDB.update(user)
            return user
        return None

    @staticmethod
    def count() -> int:
        """统计用户数量"""
        UserDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM users WHERE is_active = 1')
            return cursor.fetchone()[0]

    @staticmethod
    def exists_username(username: str, exclude_id: int = None) -> bool:
        """检查用户名是否存在"""
        UserDB.init_table()
        with Database.get_cursor() as cursor:
            if exclude_id:
                cursor.execute(
                    'SELECT 1 FROM users WHERE username = ? AND id != ?',
                    (username, exclude_id)
                )
            else:
                cursor.execute('SELECT 1 FROM users WHERE username = ?', (username,))
            return cursor.fetchone() is not None