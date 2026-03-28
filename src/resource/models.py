# -*- coding: utf-8 -*-
"""
资源管理模块 - 数据库模型
支持视频、图片、组图等多种资源类型
"""

import os
import sqlite3
import threading
from datetime import datetime
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum


class ResourceType(str, Enum):
    VIDEO = "video"
    IMAGE = "image"
    GALLERY = "gallery"


class ScanMode(str, Enum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    REALTIME = "realtime"


class PathType(str, Enum):
    FOLDER = "folder"
    FILE = "file"


# 数据库路径（主数据库）
_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'databases')
_DB_PATH = os.path.join(_DB_DIR, 'resource.db')


def _ensure_db_dir():
    """确保数据库目录存在"""
    os.makedirs(_DB_DIR, exist_ok=True)


@dataclass
class ResourceLibrary:
    """资源库模型"""
    id: Optional[int] = None
    name: str = ""
    path: str = ""  # 文件夹路径
    resource_type: ResourceType = ResourceType.VIDEO
    scan_mode: ScanMode = ScanMode.MANUAL
    scan_interval: int = 60  # 分钟
    is_active: bool = True
    is_watching: bool = False  # 是否在监控中
    last_scan_at: Optional[datetime] = None
    last_watch_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'path': self.path,
            'resource_type': self.resource_type.value if isinstance(self.resource_type, Enum) else self.resource_type,
            'scan_mode': self.scan_mode.value if isinstance(self.scan_mode, Enum) else self.scan_mode,
            'scan_interval': self.scan_interval,
            'is_active': self.is_active,
            'is_watching': self.is_watching,
            'last_scan_at': self.last_scan_at.isoformat() if self.last_scan_at else None,
            'last_watch_at': self.last_watch_at.isoformat() if self.last_watch_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'ResourceLibrary':
        rt = d.get('resource_type', 'video')
        sm = d.get('scan_mode', 'manual')
        return cls(
            id=d.get('id'),
            name=d.get('name', ''),
            path=d.get('path', ''),
            resource_type=ResourceType(rt) if isinstance(rt, str) else rt,
            scan_mode=ScanMode(sm) if isinstance(sm, str) else sm,
            scan_interval=d.get('scan_interval', 60),
            is_active=d.get('is_active', True),
            is_watching=d.get('is_watching', False),
            last_scan_at=datetime.fromisoformat(d['last_scan_at']) if d.get('last_scan_at') else None,
            last_watch_at=datetime.fromisoformat(d['last_watch_at']) if d.get('last_watch_at') else None,
            created_at=datetime.fromisoformat(d['created_at']) if d.get('created_at') else datetime.utcnow(),
            updated_at=datetime.fromisoformat(d['updated_at']) if d.get('updated_at') else datetime.utcnow(),
        )


@dataclass
class ResourceFolder:
    """文件夹/文件模型 - 视频库的下一级"""
    id: Optional[int] = None
    library_id: int = 0
    name: str = ""
    path: str = ""
    path_type: PathType = PathType.FOLDER  # folder 或 file
    is_active: bool = True
    scan_mode: ScanMode = ScanMode.MANUAL
    scan_interval: int = 60  # 分钟
    last_scan_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'library_id': self.library_id,
            'name': self.name,
            'path': self.path,
            'path_type': self.path_type.value if isinstance(self.path_type, Enum) else self.path_type,
            'is_active': self.is_active,
            'scan_mode': self.scan_mode.value if isinstance(self.scan_mode, Enum) else self.scan_mode,
            'scan_interval': self.scan_interval,
            'last_scan_at': self.last_scan_at.isoformat() if self.last_scan_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'ResourceFolder':
        pt = d.get('path_type', 'folder')
        sm = d.get('scan_mode', 'manual')
        return cls(
            id=d.get('id'),
            library_id=d.get('library_id', 0),
            name=d.get('name', ''),
            path=d.get('path', ''),
            path_type=PathType(pt) if isinstance(pt, str) else pt,
            is_active=d.get('is_active', True),
            scan_mode=ScanMode(sm) if isinstance(sm, str) else sm,
            scan_interval=d.get('scan_interval', 60),
            last_scan_at=datetime.fromisoformat(d['last_scan_at']) if d.get('last_scan_at') else None,
            created_at=datetime.fromisoformat(d['created_at']) if d.get('created_at') else datetime.utcnow(),
            updated_at=datetime.fromisoformat(d['updated_at']) if d.get('updated_at') else datetime.utcnow(),
        )


@dataclass
class ResourceItem:
    """资源条目模型 - 以 hash 为索引"""
    id: Optional[int] = None
    library_id: int = 0
    folder_id: Optional[int] = None  # 所属文件夹 ID
    hash: str = ""  # 文件内容 hash，作为唯一索引
    file_path: str = ""  # 文件相对路径（相对于库文件夹）
    file_name: str = ""  # 文件名
    file_ext: str = ""  # 扩展名
    file_size: int = 0  # 文件大小
    mime_type: str = ""  # MIME 类型
    width: Optional[int] = None  # 图片/视频宽度
    height: Optional[int] = None  # 图片/视频高度
    duration: Optional[float] = None  # 视频时长（秒）
    metadata: Dict[str, Any] = field(default_factory=dict)  # 其他元数据
    is_deleted: bool = False  # 软删除标记
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'library_id': self.library_id,
            'folder_id': self.folder_id,
            'hash': self.hash,
            'file_path': self.file_path,
            'file_name': self.file_name,
            'file_ext': self.file_ext,
            'file_size': self.file_size,
            'mime_type': self.mime_type,
            'width': self.width,
            'height': self.height,
            'duration': self.duration,
            'metadata': self.metadata,
            'is_deleted': self.is_deleted,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'ResourceItem':
        return cls(
            id=d.get('id'),
            library_id=d.get('library_id', 0),
            folder_id=d.get('folder_id'),
            hash=d.get('hash', ''),
            file_path=d.get('file_path', ''),
            file_name=d.get('file_name', ''),
            file_ext=d.get('file_ext', ''),
            file_size=d.get('file_size', 0),
            mime_type=d.get('mime_type', ''),
            width=d.get('width'),
            height=d.get('height'),
            duration=d.get('duration'),
            metadata=d.get('metadata', {}),
            is_deleted=d.get('is_deleted', False),
            created_at=datetime.fromisoformat(d['created_at']) if d.get('created_at') else datetime.utcnow(),
            updated_at=datetime.fromisoformat(d['updated_at']) if d.get('updated_at') else datetime.utcnow(),
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

    @classmethod
    def init_db(cls):
        """初始化数据库表"""
        _ensure_db_dir()
        with cls.get_cursor() as cursor:
            # 资源库表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS resource_libraries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    path TEXT NOT NULL,
                    resource_type TEXT NOT NULL DEFAULT 'video',
                    scan_mode TEXT NOT NULL DEFAULT 'manual',
                    scan_interval INTEGER DEFAULT 60,
                    is_active INTEGER DEFAULT 1,
                    is_watching INTEGER DEFAULT 0,
                    last_scan_at TEXT,
                    last_watch_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')

            # 文件夹/文件表（中间层）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS resource_folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    library_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    path_type TEXT NOT NULL DEFAULT 'folder',
                    is_active INTEGER DEFAULT 1,
                    scan_mode TEXT DEFAULT 'manual',
                    scan_interval INTEGER DEFAULT 60,
                    last_scan_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (library_id) REFERENCES resource_libraries(id) ON DELETE CASCADE
                )
            ''')

            # 资源条目表（hash 为索引）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS resource_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    library_id INTEGER NOT NULL,
                    folder_id INTEGER,
                    hash TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_ext TEXT,
                    file_size INTEGER DEFAULT 0,
                    mime_type TEXT,
                    width INTEGER,
                    height INTEGER,
                    duration REAL,
                    metadata TEXT,
                    is_deleted INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (library_id) REFERENCES resource_libraries(id) ON DELETE CASCADE,
                    FOREIGN KEY (folder_id) REFERENCES resource_folders(id) ON DELETE SET NULL,
                    UNIQUE(library_id, hash)
                )
            ''')

            # 创建 hash 索引（唯一索引加速查询）
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_resource_items_hash
                ON resource_items(hash)
            ''')

            # 创建 library_id 索引
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_resource_items_library
                ON resource_items(library_id)
            ''')

            # 创建 folder_id 索引
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_resource_items_folder
                ON resource_items(folder_id)
            ''')

            # 创建 folders library_id 索引
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_resource_folders_library
                ON resource_folders(library_id)
            ''')


class ResourceLibraryDB:
    """资源库数据库操作"""

    @staticmethod
    def create(library: ResourceLibrary) -> int:
        """创建资源库"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO resource_libraries
                (name, path, resource_type, scan_mode, scan_interval, is_active, is_watching, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                library.name,
                library.path,
                library.resource_type.value if isinstance(library.resource_type, Enum) else library.resource_type,
                library.scan_mode.value if isinstance(library.scan_mode, Enum) else library.scan_mode,
                library.scan_interval,
                1 if library.is_active else 0,
                1 if library.is_watching else 0,
                library.created_at.isoformat(),
                library.updated_at.isoformat(),
            ))
            return cursor.lastrowid

    @staticmethod
    def get_by_id(library_id: int) -> Optional[ResourceLibrary]:
        """根据 ID 获取资源库"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            cursor.execute('SELECT * FROM resource_libraries WHERE id = ?', (library_id,))
            row = cursor.fetchone()
            if row:
                return ResourceLibrary(
                    id=row['id'],
                    name=row['name'],
                    path=row['path'],
                    resource_type=row['resource_type'],
                    scan_mode=row['scan_mode'],
                    scan_interval=row['scan_interval'],
                    is_active=bool(row['is_active']),
                    is_watching=bool(row['is_watching']),
                    last_scan_at=datetime.fromisoformat(row['last_scan_at']) if row['last_scan_at'] else None,
                    last_watch_at=datetime.fromisoformat(row['last_watch_at']) if row['last_watch_at'] else None,
                    created_at=datetime.fromisoformat(row['created_at']),
                    updated_at=datetime.fromisoformat(row['updated_at']),
                )
            return None

    @staticmethod
    def get_all() -> List[ResourceLibrary]:
        """获取所有资源库"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            cursor.execute('SELECT * FROM resource_libraries ORDER BY id')
            rows = cursor.fetchall()
            return [
                ResourceLibrary(
                    id=row['id'],
                    name=row['name'],
                    path=row['path'],
                    resource_type=row['resource_type'],
                    scan_mode=row['scan_mode'],
                    scan_interval=row['scan_interval'],
                    is_active=bool(row['is_active']),
                    is_watching=bool(row['is_watching']),
                    last_scan_at=datetime.fromisoformat(row['last_scan_at']) if row['last_scan_at'] else None,
                    last_watch_at=datetime.fromisoformat(row['last_watch_at']) if row['last_watch_at'] else None,
                    created_at=datetime.fromisoformat(row['created_at']),
                    updated_at=datetime.fromisoformat(row['updated_at']),
                )
                for row in rows
            ]

    @staticmethod
    def update(library: ResourceLibrary) -> bool:
        """更新资源库"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            cursor.execute('''
                UPDATE resource_libraries SET
                    name = ?, path = ?, resource_type = ?, scan_mode = ?,
                    scan_interval = ?, is_active = ?, is_watching = ?,
                    last_scan_at = ?, last_watch_at = ?, updated_at = ?
                WHERE id = ?
            ''', (
                library.name,
                library.path,
                library.resource_type.value if isinstance(library.resource_type, Enum) else library.resource_type,
                library.scan_mode.value if isinstance(library.scan_mode, Enum) else library.scan_mode,
                library.scan_interval,
                1 if library.is_active else 0,
                1 if library.is_watching else 0,
                library.last_scan_at.isoformat() if library.last_scan_at else None,
                library.last_watch_at.isoformat() if library.last_watch_at else None,
                datetime.utcnow().isoformat(),
                library.id,
            ))
            return cursor.rowcount > 0

    @staticmethod
    def delete(library_id: int) -> bool:
        """删除资源库"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            cursor.execute('DELETE FROM resource_libraries WHERE id = ?', (library_id,))
            return cursor.rowcount > 0

    @staticmethod
    def get_by_hash(hash_value: str) -> Optional[ResourceItem]:
        """根据 hash 获取资源条目"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            cursor.execute('SELECT * FROM resource_items WHERE hash = ? AND is_deleted = 0', (hash_value,))
            row = cursor.fetchone()
            if row:
                return ResourceItem(
                    id=row['id'],
                    library_id=row['library_id'],
                    hash=row['hash'],
                    file_path=row['file_path'],
                    file_name=row['file_name'],
                    file_ext=row['file_ext'],
                    file_size=row['file_size'],
                    mime_type=row['mime_type'],
                    width=row['width'],
                    height=row['height'],
                    duration=row['duration'],
                    metadata=eval(row['metadata']) if row['metadata'] else {},
                    is_deleted=bool(row['is_deleted']),
                    created_at=datetime.fromisoformat(row['created_at']),
                    updated_at=datetime.fromisoformat(row['updated_at']),
                )
            return None


class ResourceFolderDB:
    """文件夹数据库操作"""

    @staticmethod
    def create(folder: ResourceFolder) -> int:
        """创建文件夹"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO resource_folders
                (library_id, name, path, path_type, is_active, scan_mode, scan_interval, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                folder.library_id,
                folder.name,
                folder.path,
                folder.path_type.value if isinstance(folder.path_type, Enum) else folder.path_type,
                1 if folder.is_active else 0,
                folder.scan_mode.value if isinstance(folder.scan_mode, Enum) else folder.scan_mode,
                folder.scan_interval,
                folder.created_at.isoformat(),
                folder.updated_at.isoformat(),
            ))
            return cursor.lastrowid

    @staticmethod
    def get_by_id(folder_id: int) -> Optional[ResourceFolder]:
        """根据 ID 获取文件夹"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            cursor.execute('SELECT * FROM resource_folders WHERE id = ?', (folder_id,))
            row = cursor.fetchone()
            if row:
                return ResourceFolderDB._row_to_folder(row)
            return None

    @staticmethod
    def get_by_library(library_id: int) -> List[ResourceFolder]:
        """获取库的所有文件夹"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            cursor.execute(
                'SELECT * FROM resource_folders WHERE library_id = ? ORDER BY name',
                (library_id,)
            )
            rows = cursor.fetchall()
            return [ResourceFolderDB._row_to_folder(row) for row in rows]

    @staticmethod
    def get_by_path(path: str, library_id: int = None) -> Optional[ResourceFolder]:
        """根据路径获取文件夹"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            if library_id:
                cursor.execute(
                    'SELECT * FROM resource_folders WHERE path = ? AND library_id = ?',
                    (path, library_id)
                )
            else:
                cursor.execute('SELECT * FROM resource_folders WHERE path = ?', (path,))
            row = cursor.fetchone()
            if row:
                return ResourceFolderDB._row_to_folder(row)
            return None

    @staticmethod
    def update(folder: ResourceFolder) -> bool:
        """更新文件夹"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            cursor.execute('''
                UPDATE resource_folders SET
                    name = ?, path = ?, path_type = ?, is_active = ?,
                    scan_mode = ?, scan_interval = ?, last_scan_at = ?, updated_at = ?
                WHERE id = ?
            ''', (
                folder.name,
                folder.path,
                folder.path_type.value if isinstance(folder.path_type, Enum) else folder.path_type,
                1 if folder.is_active else 0,
                folder.scan_mode.value if isinstance(folder.scan_mode, Enum) else folder.scan_mode,
                folder.scan_interval,
                folder.last_scan_at.isoformat() if folder.last_scan_at else None,
                datetime.utcnow().isoformat(),
                folder.id,
            ))
            return cursor.rowcount > 0

    @staticmethod
    def delete(folder_id: int) -> bool:
        """删除文件夹"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            cursor.execute('DELETE FROM resource_folders WHERE id = ?', (folder_id,))
            return cursor.rowcount > 0

    @staticmethod
    def get_item_count(folder_id: int) -> int:
        """统计文件夹的资源数量"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            cursor.execute(
                'SELECT COUNT(*) as cnt FROM resource_items WHERE folder_id = ? AND is_deleted = 0',
                (folder_id,)
            )
            return cursor.fetchone()['cnt']

    @staticmethod
    def _row_to_folder(row: sqlite3.Row) -> ResourceFolder:
        """将数据库行转换为 ResourceFolder 对象"""
        return ResourceFolder(
            id=row['id'],
            library_id=row['library_id'],
            name=row['name'],
            path=row['path'],
            path_type=row['path_type'],
            is_active=bool(row['is_active']),
            scan_mode=row['scan_mode'],
            scan_interval=row['scan_interval'],
            last_scan_at=datetime.fromisoformat(row['last_scan_at']) if row['last_scan_at'] else None,
            created_at=datetime.fromisoformat(row['created_at']),
            updated_at=datetime.fromisoformat(row['updated_at']),
        )


class ResourceItemDB:
    """资源条目数据库操作"""

    @staticmethod
    def upsert(item: ResourceItem) -> int:
        """插入或更新资源条目"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            # 先查询是否存在
            cursor.execute(
                'SELECT id FROM resource_items WHERE library_id = ? AND hash = ?',
                (item.library_id, item.hash)
            )
            existing = cursor.fetchone()

            now = datetime.utcnow().isoformat()
            metadata_str = str(item.metadata) if item.metadata else '{}'

            if existing:
                cursor.execute('''
                    UPDATE resource_items SET
                        file_path = ?, file_name = ?, file_ext = ?, file_size = ?,
                        mime_type = ?, width = ?, height = ?, duration = ?,
                        metadata = ?, is_deleted = 0, updated_at = ?
                    WHERE id = ?
                ''', (
                    item.file_path,
                    item.file_name,
                    item.file_ext,
                    item.file_size,
                    item.mime_type,
                    item.width,
                    item.height,
                    item.duration,
                    metadata_str,
                    now,
                    existing['id'],
                ))
                return existing['id']
            else:
                cursor.execute('''
                    INSERT INTO resource_items
                    (library_id, hash, file_path, file_name, file_ext, file_size,
                     mime_type, width, height, duration, metadata, is_deleted, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                ''', (
                    item.library_id,
                    item.hash,
                    item.file_path,
                    item.file_name,
                    item.file_ext,
                    item.file_size,
                    item.mime_type,
                    item.width,
                    item.height,
                    item.duration,
                    metadata_str,
                    now,
                    now,
                ))
                return cursor.lastrowid

    @staticmethod
    def soft_delete(hash_value: str) -> bool:
        """软删除资源条目"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            cursor.execute('''
                UPDATE resource_items SET is_deleted = 1, updated_at = ?
                WHERE hash = ?
            ''', (datetime.utcnow().isoformat(), hash_value))
            return cursor.rowcount > 0

    @staticmethod
    def get_by_library(library_id: int, include_deleted: bool = False) -> List[ResourceItem]:
        """获取库的所有资源条目"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            if include_deleted:
                cursor.execute(
                    'SELECT * FROM resource_items WHERE library_id = ? ORDER BY file_name',
                    (library_id,)
                )
            else:
                cursor.execute(
                    'SELECT * FROM resource_items WHERE library_id = ? AND is_deleted = 0 ORDER BY file_name',
                    (library_id,)
                )
            rows = cursor.fetchall()
            return [ResourceItem(
                id=row['id'],
                library_id=row['library_id'],
                hash=row['hash'],
                file_path=row['file_path'],
                file_name=row['file_name'],
                file_ext=row['file_ext'],
                file_size=row['file_size'],
                mime_type=row['mime_type'],
                width=row['width'],
                height=row['height'],
                duration=row['duration'],
                metadata=eval(row['metadata']) if row['metadata'] else {},
                is_deleted=bool(row['is_deleted']),
                created_at=datetime.fromisoformat(row['created_at']),
                updated_at=datetime.fromisoformat(row['updated_at']),
            ) for row in rows]

    @staticmethod
    def count_by_library(library_id: int) -> int:
        """统计库的资源数量"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            cursor.execute(
                'SELECT COUNT(*) as cnt FROM resource_items WHERE library_id = ? AND is_deleted = 0',
                (library_id,)
            )
            return cursor.fetchone()['cnt']
