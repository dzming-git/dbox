# -*- coding: utf-8 -*-
"""
播放历史模块 - 数据库模型
支持播放进度记录、断点续播、观看历史等操作
"""

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


# 数据库路径
_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'databases')
_DB_PATH = os.path.join(_DB_DIR, 'history.db')


def _ensure_db_dir():
    """确保数据库目录存在"""
    os.makedirs(_DB_DIR, exist_ok=True)


@dataclass
class WatchHistory:
    """播放历史模型"""
    id: Optional[int] = None
    video_hash: str = ""
    user_id: int = 0
    progress: float = 0.0  # 播放进度（秒）
    duration: float = 0.0   # 视频总时长（秒）
    completed: bool = False  # 是否已看完
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    last_watch_time: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'id': self.id,
            'video_hash': self.video_hash,
            'user_id': self.user_id,
            'progress': self.progress,
            'duration': self.duration,
            'progress_percent': round(self.progress / self.duration * 100, 1) if self.duration > 0 else 0,
            'completed': self.completed,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_watch_time': self.last_watch_time.isoformat() if self.last_watch_time else None,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'WatchHistory':
        """从字典创建"""
        return cls(
            id=d.get('id'),
            video_hash=d.get('video_hash', ''),
            user_id=d.get('user_id', 0),
            progress=d.get('progress', 0.0),
            duration=d.get('duration', 0.0),
            completed=d.get('completed', False),
            created_at=datetime.fromisoformat(d['created_at']) if d.get('created_at') else datetime.utcnow(),
            updated_at=datetime.fromisoformat(d['updated_at']) if d.get('updated_at') else datetime.utcnow(),
            last_watch_time=datetime.fromisoformat(d['last_watch_time']) if d.get('last_watch_time') else datetime.utcnow(),
        )


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


class WatchHistoryDB:
    """播放历史数据库操作"""

    @staticmethod
    def init_table():
        """确保 watch_history 表存在"""
        with Database.get_cursor() as cursor:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS watch_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_hash VARCHAR(128) NOT NULL,
                    user_id INTEGER NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    duration REAL NOT NULL DEFAULT 0,
                    completed BOOLEAN NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    last_watch_time DATETIME NOT NULL,
                    UNIQUE(video_hash, user_id)
                )
            ''')
            # 创建索引加速查询
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_history_user ON watch_history(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_history_hash ON watch_history(video_hash)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_history_time ON watch_history(last_watch_time DESC)')

    @staticmethod
    def get_or_create(video_hash: str, user_id: int) -> WatchHistory:
        """获取或创建播放历史记录"""
        WatchHistoryDB.init_table()
        history = WatchHistoryDB.get_by_hash_user(video_hash, user_id)
        if history:
            return history

        # 创建新记录
        now = datetime.utcnow()
        history = WatchHistory(
            video_hash=video_hash,
            user_id=user_id,
            progress=0.0,
            duration=0.0,
            completed=False,
            created_at=now,
            updated_at=now,
            last_watch_time=now,
        )
        history.id = WatchHistoryDB.create(history)
        return history

    @staticmethod
    def create(history: WatchHistory) -> int:
        """创建播放历史"""
        WatchHistoryDB.init_table()
        now = datetime.utcnow().isoformat()
        with Database.get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO watch_history
                (video_hash, user_id, progress, duration, completed, created_at, updated_at, last_watch_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                history.video_hash,
                history.user_id,
                history.progress,
                history.duration,
                1 if history.completed else 0,
                history.created_at.isoformat() if history.created_at else now,
                history.updated_at.isoformat() if history.updated_at else now,
                history.last_watch_time.isoformat() if history.last_watch_time else now,
            ))
            return cursor.lastrowid

    @staticmethod
    def get_by_id(history_id: int) -> Optional[WatchHistory]:
        """根据 ID 获取播放历史"""
        WatchHistoryDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute('SELECT * FROM watch_history WHERE id = ?', (history_id,))
            row = cursor.fetchone()
            if row:
                return WatchHistoryDB._row_to_history(row)
            return None

    @staticmethod
    def get_by_hash_user(video_hash: str, user_id: int) -> Optional[WatchHistory]:
        """根据 video_hash 和 user_id 获取播放历史"""
        WatchHistoryDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute(
                'SELECT * FROM watch_history WHERE video_hash = ? AND user_id = ?',
                (video_hash, user_id)
            )
            row = cursor.fetchone()
            if row:
                return WatchHistoryDB._row_to_history(row)
            return None

    @staticmethod
    def get_by_hash(video_hash: str) -> Optional[WatchHistory]:
        """根据 video_hash 获取任意用户的最新播放历史（用于匿名续播）"""
        WatchHistoryDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute(
                'SELECT * FROM watch_history WHERE video_hash = ? ORDER BY last_watch_time DESC LIMIT 1',
                (video_hash,)
            )
            row = cursor.fetchone()
            if row:
                return WatchHistoryDB._row_to_history(row)
            return None

    @staticmethod
    def get_watch_history(user_id: int, limit: int = 50, offset: int = 0) -> List[WatchHistory]:
        """获取用户的观看历史列表"""
        WatchHistoryDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute('''
                SELECT * FROM watch_history
                WHERE user_id = ?
                ORDER BY last_watch_time DESC
                LIMIT ? OFFSET ?
            ''', (user_id, limit, offset))
            rows = cursor.fetchall()
            return [WatchHistoryDB._row_to_history(row) for row in rows]

    @staticmethod
    def get_continue_watch(user_id: int, limit: int = 10) -> List[WatchHistory]:
        """获取用户未看完的视频（继续观看）"""
        WatchHistoryDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute('''
                SELECT * FROM watch_history
                WHERE user_id = ? AND completed = 0 AND progress > 0
                ORDER BY last_watch_time DESC
                LIMIT ?
            ''', (user_id, limit))
            rows = cursor.fetchall()
            return [WatchHistoryDB._row_to_history(row) for row in rows]

    @staticmethod
    def update(history: WatchHistory) -> bool:
        """更新播放历史"""
        WatchHistoryDB.init_table()
        now = datetime.utcnow()
        history.updated_at = now
        history.last_watch_time = now
        with Database.get_cursor() as cursor:
            cursor.execute('''
                UPDATE watch_history SET
                    progress = ?,
                    duration = ?,
                    completed = ?,
                    updated_at = ?,
                    last_watch_time = ?
                WHERE id = ?
            ''', (
                history.progress,
                history.duration,
                1 if history.completed else 0,
                history.updated_at.isoformat(),
                history.last_watch_time.isoformat(),
                history.id,
            ))
            return cursor.rowcount > 0

    @staticmethod
    def delete(history_id: int) -> bool:
        """删除播放历史"""
        WatchHistoryDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute('DELETE FROM watch_history WHERE id = ?', (history_id,))
            return cursor.rowcount > 0

    @staticmethod
    def delete_by_user(user_id: int) -> int:
        """删除用户的所有播放历史"""
        WatchHistoryDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute('DELETE FROM watch_history WHERE user_id = ?', (user_id,))
            return cursor.rowcount

    @staticmethod
    def count(user_id: int = None) -> int:
        """统计播放历史数量"""
        WatchHistoryDB.init_table()
        with Database.get_cursor() as cursor:
            if user_id:
                cursor.execute('SELECT COUNT(*) FROM watch_history WHERE user_id = ?', (user_id,))
            else:
                cursor.execute('SELECT COUNT(*) FROM watch_history')
            return cursor.fetchone()[0]

    @staticmethod
    def _row_to_history(row: sqlite3.Row) -> WatchHistory:
        """将数据库行转换为 WatchHistory 对象"""
        return WatchHistory(
            id=row['id'],
            video_hash=row['video_hash'],
            user_id=row['user_id'],
            progress=row['progress'],
            duration=row['duration'],
            completed=bool(row['completed']),
            created_at=datetime.fromisoformat(row['created_at']),
            updated_at=datetime.fromisoformat(row['updated_at']),
            last_watch_time=datetime.fromisoformat(row['last_watch_time']),
        )
