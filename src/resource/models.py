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


def get_db_dir() -> str:
    """获取数据库目录路径"""
    return _DB_DIR


def get_db_path(db_file: str) -> str:
    """获取数据库文件完整路径"""
    return os.path.join(_DB_DIR, db_file)


@dataclass
class ResourceLibrary:
    """资源库模型"""
    id: Optional[int] = None
    name: str = ""
    db_file: str = ""  # 数据库文件名（与 name 一一对应，如 "porn.db"）
    path: str = ""  # 主文件夹路径（兼容旧字段）
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
            'db_file': self.db_file,
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
            db_file=d.get('db_file', ''),
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
    """文件夹/文件模型 - 资源库的下一级"""
    id: Optional[int] = None
    library_id: int = 0
    name: str = ""
    path: str = ""
    path_type: PathType = PathType.FOLDER  # folder 或 file
    is_active: bool = True
    is_default: bool = False  # 是否为默认上传路径
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
            'is_default': self.is_default,
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
            is_default=d.get('is_default', False),
            scan_mode=ScanMode(sm) if isinstance(sm, str) else sm,
            scan_interval=d.get('scan_interval', 60),
            last_scan_at=datetime.fromisoformat(d['last_scan_at']) if d.get('last_scan_at') else None,
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
                    db_file TEXT NOT NULL DEFAULT '',
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

            # 迁移：为已有记录添加 db_file 字段
            cursor.execute("PRAGMA table_info(resource_libraries)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'db_file' not in columns:
                cursor.execute("ALTER TABLE resource_libraries ADD COLUMN db_file TEXT NOT NULL DEFAULT ''")

            # 文件夹/文件表（中间层）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS resource_folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    library_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    path_type TEXT NOT NULL DEFAULT 'folder',
                    is_active INTEGER DEFAULT 1,
                    is_default INTEGER DEFAULT 0,
                    scan_mode TEXT DEFAULT 'manual',
                    scan_interval INTEGER DEFAULT 60,
                    last_scan_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (library_id) REFERENCES resource_libraries(id) ON DELETE CASCADE
                )
            ''')

            # 迁移：为已有记录添加 is_default 字段
            cursor.execute("PRAGMA table_info(resource_folders)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'is_default' not in columns:
                cursor.execute("ALTER TABLE resource_folders ADD COLUMN is_default INTEGER DEFAULT 0")

            # 注：resource_items 表已废弃（双索引的死数据，索引权威源统一为 web 的 Video 表）。
            # 2026-07-12 迁移：DROP 该表并停止写入，resourced 仅保留「库/文件夹路径注册表」职责。

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
                    db_file=row['db_file'],
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
                    db_file=row['db_file'],
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
                    name = ?, db_file = ?, path = ?, resource_type = ?, scan_mode = ?,
                    scan_interval = ?, is_active = ?, is_watching = ?,
                    last_scan_at = ?, last_watch_at = ?, updated_at = ?
                WHERE id = ?
            ''', (
                library.name,
                library.db_file,
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
    def rename_library(library_id: int, new_name: str, new_db_file: str) -> bool:
        """
        重命名资源库，同时更新数据库文件名

        Args:
            library_id: 库 ID
            new_name: 新名称
            new_db_file: 新数据库文件名

        Returns:
            bool: 是否成功
        """
        Database.init_db()
        with Database.get_cursor() as cursor:
            cursor.execute('''
                UPDATE resource_libraries SET
                    name = ?, db_file = ?, updated_at = ?
                WHERE id = ?
            ''', (
                new_name,
                new_db_file,
                datetime.utcnow().isoformat(),
                library_id,
            ))
            return cursor.rowcount > 0

    @staticmethod
    def delete(library_id: int) -> bool:
        """删除资源库"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            cursor.execute('DELETE FROM resource_libraries WHERE id = ?', (library_id,))
            return cursor.rowcount > 0

class ResourceFolderDB:
    """文件夹数据库操作"""

    @staticmethod
    def create(folder: ResourceFolder) -> int:
        """创建文件夹"""
        Database.init_db()

        # 如果设置为默认，先取消该库其他文件夹的默认状态
        if folder.is_default:
            ResourceFolderDB._clear_default(folder.library_id)

        with Database.get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO resource_folders
                (library_id, name, path, path_type, is_active, is_default, scan_mode, scan_interval, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                folder.library_id,
                folder.name,
                folder.path,
                folder.path_type.value if isinstance(folder.path_type, Enum) else folder.path_type,
                1 if folder.is_active else 0,
                1 if folder.is_default else 0,
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
                'SELECT * FROM resource_folders WHERE library_id = ? ORDER BY is_default DESC, name',
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
    def get_default_folder(library_id: int) -> Optional[ResourceFolder]:
        """获取库的默认文件夹"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            cursor.execute(
                'SELECT * FROM resource_folders WHERE library_id = ? AND is_default = 1',
                (library_id,)
            )
            row = cursor.fetchone()
            if row:
                return ResourceFolderDB._row_to_folder(row)
            return None

    @staticmethod
    def set_default(folder_id: int) -> bool:
        """设置文件夹为默认上传路径"""
        Database.init_db()
        folder = ResourceFolderDB.get_by_id(folder_id)
        if not folder:
            return False

        # 清除该库其他文件夹的默认状态
        ResourceFolderDB._clear_default(folder.library_id)

        # 设置新的默认
        folder.is_default = True
        return ResourceFolderDB.update(folder)

    @staticmethod
    def _clear_default(library_id: int):
        """清除库的默认路径设置"""
        Database.init_db()
        with Database.get_cursor() as cursor:
            cursor.execute(
                'UPDATE resource_folders SET is_default = 0 WHERE library_id = ? AND is_default = 1',
                (library_id,)
            )

    @staticmethod
    def update(folder: ResourceFolder) -> bool:
        """更新文件夹"""
        Database.init_db()

        # 如果设置为默认，先取消该库其他文件夹的默认状态
        if folder.is_default:
            ResourceFolderDB._clear_default(folder.library_id)

        with Database.get_cursor() as cursor:
            cursor.execute('''
                UPDATE resource_folders SET
                    name = ?, path = ?, path_type = ?, is_active = ?, is_default = ?,
                    scan_mode = ?, scan_interval = ?, last_scan_at = ?, updated_at = ?
                WHERE id = ?
            ''', (
                folder.name,
                folder.path,
                folder.path_type.value if isinstance(folder.path_type, Enum) else folder.path_type,
                1 if folder.is_active else 0,
                1 if folder.is_default else 0,
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
        """统计文件夹的资源数量

        注：resource_items 表已于 2026-07-12 废弃（索引权威源统一为 web 的 Video 表）。
        resourced 不再维护文件级索引，故此处恒返回 0；若需按文件夹统计真实视频数，
        应在 web 侧基于 Video.local_path 前缀匹配实现。
        """
        return 0

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
            is_default=bool(row['is_default']),
            scan_mode=row['scan_mode'],
            scan_interval=row['scan_interval'],
            last_scan_at=datetime.fromisoformat(row['last_scan_at']) if row['last_scan_at'] else None,
            created_at=datetime.fromisoformat(row['created_at']),
            updated_at=datetime.fromisoformat(row['updated_at']),
        )



