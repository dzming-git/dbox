# -*- coding: utf-8 -*-
"""
收藏夹模块 - 数据库模型
支持创建收藏夹、添加/移除视频、收藏夹管理等操作
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
_DB_PATH = os.path.join(_DB_DIR, 'collection.db')


def _ensure_db_dir():
    """确保数据库目录存在"""
    os.makedirs(_DB_DIR, exist_ok=True)


@dataclass
class Collection:
    """收藏夹模型"""
    id: Optional[int] = None
    name: str = ""
    description: str = ""
    user_id: int = 0  # 创建者
    is_public: bool = False  # 是否公开
    item_count: int = 0  # 视频数量（冗余字段，加速查询）
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'user_id': self.user_id,
            'is_public': self.is_public,
            'item_count': self.item_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'Collection':
        """从字典创建"""
        return cls(
            id=d.get('id'),
            name=d.get('name', ''),
            description=d.get('description', ''),
            user_id=d.get('user_id', 0),
            is_public=d.get('is_public', False),
            item_count=d.get('item_count', 0),
            created_at=datetime.fromisoformat(d['created_at']) if d.get('created_at') else datetime.utcnow(),
            updated_at=datetime.fromisoformat(d['updated_at']) if d.get('updated_at') else datetime.utcnow(),
        )


@dataclass
class CollectionItem:
    """收藏夹条目模型"""
    id: Optional[int] = None
    collection_id: int = 0
    video_hash: str = ""
    added_at: datetime = field(default_factory=datetime.utcnow)
    note: str = ""  # 用户对这条收藏的备注

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'id': self.id,
            'collection_id': self.collection_id,
            'video_hash': self.video_hash,
            'added_at': self.added_at.isoformat() if self.added_at else None,
            'note': self.note,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'CollectionItem':
        """从字典创建"""
        return cls(
            id=d.get('id'),
            collection_id=d.get('collection_id', 0),
            video_hash=d.get('video_hash', ''),
            added_at=datetime.fromisoformat(d['added_at']) if d.get('added_at') else datetime.utcnow(),
            note=d.get('note', ''),
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


class CollectionDB:
    """收藏夹数据库操作"""

    @staticmethod
    def init_table():
        """确保收藏夹表存在"""
        with Database.get_cursor() as cursor:
            # 收藏夹表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS collections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(100) NOT NULL,
                    description TEXT DEFAULT '',
                    user_id INTEGER NOT NULL,
                    is_public BOOLEAN NOT NULL DEFAULT 0,
                    item_count INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
            ''')

            # 收藏夹条目表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS collection_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection_id INTEGER NOT NULL,
                    video_hash VARCHAR(128) NOT NULL,
                    added_at DATETIME NOT NULL,
                    note TEXT DEFAULT '',
                    UNIQUE(collection_id, video_hash),
                    FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
                )
            ''')

            # 创建索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_col_user ON collections(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_item_collection ON collection_items(collection_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_item_hash ON collection_items(video_hash)')

    # ============ 收藏夹操作 ============

    @staticmethod
    def create_collection(collection: Collection) -> int:
        """创建收藏夹"""
        CollectionDB.init_table()
        now = datetime.utcnow().isoformat()
        with Database.get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO collections (name, description, user_id, is_public, item_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                collection.name,
                collection.description,
                collection.user_id,
                1 if collection.is_public else 0,
                0,
                now,
                now,
            ))
            return cursor.lastrowid

    @staticmethod
    def get_collection_by_id(collection_id: int) -> Optional[Collection]:
        """根据 ID 获取收藏夹"""
        CollectionDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute('SELECT * FROM collections WHERE id = ?', (collection_id,))
            row = cursor.fetchone()
            if row:
                return CollectionDB._row_to_collection(row)
            return None

    @staticmethod
    def get_collections_by_user(user_id: int, include_public: bool = True) -> List[Collection]:
        """获取用户的所有收藏夹"""
        CollectionDB.init_table()
        with Database.get_cursor() as cursor:
            if include_public:
                cursor.execute(
                    'SELECT * FROM collections WHERE user_id = ? OR is_public = 1 ORDER BY updated_at DESC',
                    (user_id,)
                )
            else:
                cursor.execute(
                    'SELECT * FROM collections WHERE user_id = ? ORDER BY updated_at DESC',
                    (user_id,)
                )
            rows = cursor.fetchall()
            return [CollectionDB._row_to_collection(row) for row in rows]

    @staticmethod
    def update_collection(collection: Collection) -> bool:
        """更新收藏夹"""
        CollectionDB.init_table()
        now = datetime.utcnow().isoformat()
        with Database.get_cursor() as cursor:
            cursor.execute('''
                UPDATE collections SET
                    name = ?,
                    description = ?,
                    is_public = ?,
                    updated_at = ?
                WHERE id = ?
            ''', (
                collection.name,
                collection.description,
                1 if collection.is_public else 0,
                now,
                collection.id,
            ))
            return cursor.rowcount > 0

    @staticmethod
    def delete_collection(collection_id: int) -> bool:
        """删除收藏夹（级联删除条目）"""
        CollectionDB.init_table()
        with Database.get_cursor() as cursor:
            # 先删除条目
            cursor.execute('DELETE FROM collection_items WHERE collection_id = ?', (collection_id,))
            # 再删除收藏夹
            cursor.execute('DELETE FROM collections WHERE id = ?', (collection_id,))
            return cursor.rowcount > 0

    @staticmethod
    def refresh_item_count(collection_id: int):
        """刷新收藏夹的视频数量"""
        CollectionDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute(
                'SELECT COUNT(*) FROM collection_items WHERE collection_id = ?',
                (collection_id,)
            )
            count = cursor.fetchone()[0]
            cursor.execute(
                'UPDATE collections SET item_count = ?, updated_at = ? WHERE id = ?',
                (count, datetime.utcnow().isoformat(), collection_id)
            )

    # ============ 收藏夹条目操作 ============

    @staticmethod
    def add_to_collection(collection_id: int, video_hash: str, note: str = "") -> int:
        """添加视频到收藏夹"""
        CollectionDB.init_table()
        now = datetime.utcnow().isoformat()
        with Database.get_cursor() as cursor:
            cursor.execute('''
                INSERT OR IGNORE INTO collection_items (collection_id, video_hash, added_at, note)
                VALUES (?, ?, ?, ?)
            ''', (collection_id, video_hash, now, note))
            item_id = cursor.lastrowid
            if item_id == 0:
                # 已存在，更新备注
                cursor.execute('''
                    UPDATE collection_items SET note = ? WHERE collection_id = ? AND video_hash = ?
                ''', (note, collection_id, video_hash))
                cursor.execute('SELECT id FROM collection_items WHERE collection_id = ? AND video_hash = ?', (collection_id, video_hash))
                row = cursor.fetchone()
                item_id = row['id'] if row else 0

            # 刷新数量
            CollectionDB.refresh_item_count(collection_id)
            return item_id

    @staticmethod
    def remove_from_collection(collection_id: int, video_hash: str) -> bool:
        """从收藏夹移除视频"""
        CollectionDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute(
                'DELETE FROM collection_items WHERE collection_id = ? AND video_hash = ?',
                (collection_id, video_hash)
            )
            deleted = cursor.rowcount > 0
            if deleted:
                CollectionDB.refresh_item_count(collection_id)
            return deleted

    @staticmethod
    def get_collection_items(collection_id: int, page: int = 1, limit: int = 50) -> tuple:
        """获取收藏夹中的视频列表"""
        CollectionDB.init_table()
        offset = (page - 1) * limit
        with Database.get_cursor() as cursor:
            # 获取总数
            cursor.execute(
                'SELECT COUNT(*) FROM collection_items WHERE collection_id = ?',
                (collection_id,)
            )
            total = cursor.fetchone()[0]

            # 获取列表
            cursor.execute('''
                SELECT * FROM collection_items
                WHERE collection_id = ?
                ORDER BY added_at DESC
                LIMIT ? OFFSET ?
            ''', (collection_id, limit, offset))
            rows = cursor.fetchall()
            items = [CollectionDB._row_to_item(row) for row in rows]
            return items, total

    @staticmethod
    def is_in_collection(collection_id: int, video_hash: str) -> bool:
        """检查视频是否在收藏夹中"""
        CollectionDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute(
                'SELECT 1 FROM collection_items WHERE collection_id = ? AND video_hash = ?',
                (collection_id, video_hash)
            )
            return cursor.fetchone() is not None

    @staticmethod
    def get_collections_for_video(video_hash: str, user_id: int = None) -> List[Collection]:
        """获取包含指定视频的所有收藏夹"""
        CollectionDB.init_table()
        with Database.get_cursor() as cursor:
            if user_id:
                cursor.execute('''
                    SELECT DISTINCT c.* FROM collections c
                    JOIN collection_items i ON c.id = i.collection_id
                    WHERE i.video_hash = ? AND (c.user_id = ? OR c.is_public = 1)
                    ORDER BY c.updated_at DESC
                ''', (video_hash, user_id))
            else:
                cursor.execute('''
                    SELECT DISTINCT c.* FROM collections c
                    JOIN collection_items i ON c.id = i.collection_id
                    WHERE i.video_hash = ? AND c.is_public = 1
                    ORDER BY c.updated_at DESC
                ''', (video_hash,))
            rows = cursor.fetchall()
            return [CollectionDB._row_to_collection(row) for row in rows]

    @staticmethod
    def update_item_note(collection_id: int, video_hash: str, note: str) -> bool:
        """更新收藏条目的备注"""
        CollectionDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute('''
                UPDATE collection_items SET note = ? WHERE collection_id = ? AND video_hash = ?
            ''', (note, collection_id, video_hash))
            return cursor.rowcount > 0

    # ============ 辅助方法 ============

    @staticmethod
    def _row_to_collection(row: sqlite3.Row) -> Collection:
        """将数据库行转换为 Collection 对象"""
        return Collection(
            id=row['id'],
            name=row['name'],
            description=row['description'] or '',
            user_id=row['user_id'],
            is_public=bool(row['is_public']),
            item_count=row['item_count'] or 0,
            created_at=datetime.fromisoformat(row['created_at']),
            updated_at=datetime.fromisoformat(row['updated_at']),
        )

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> CollectionItem:
        """将数据库行转换为 CollectionItem 对象"""
        return CollectionItem(
            id=row['id'],
            collection_id=row['collection_id'],
            video_hash=row['video_hash'],
            added_at=datetime.fromisoformat(row['added_at']),
            note=row['note'] or '',
        )
