# -*- coding: utf-8 -*-
"""
搜索模块 - 数据库模型
使用 SQLite FTS5 进行全文搜索
"""

import os
import sqlite3
import threading
import re
from contextlib import contextmanager
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


# 数据库路径
_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'databases')
_DB_PATH = os.path.join(_DB_DIR, 'search.db')


def _ensure_db_dir():
    """确保数据库目录存在"""
    os.makedirs(_DB_DIR, exist_ok=True)


@dataclass
class SearchIndex:
    """搜索索引模型"""
    id: Optional[int] = None
    video_hash: str = ""
    title: str = ""
    description: str = ""
    tags: str = ""  # 逗号分隔的标签
    duration: float = 0.0
    library_id: int = 0
    path: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'id': self.id,
            'video_hash': self.video_hash,
            'title': self.title,
            'description': self.description,
            'tags': self.tags,
            'duration': self.duration,
            'library_id': self.library_id,
            'path': self.path,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'SearchIndex':
        """从字典创建"""
        return cls(
            id=d.get('id'),
            video_hash=d.get('video_hash', ''),
            title=d.get('title', ''),
            description=d.get('description', ''),
            tags=d.get('tags', ''),
            duration=d.get('duration', 0.0),
            library_id=d.get('library_id', 0),
            path=d.get('path', ''),
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


class SearchDB:
    """搜索数据库操作"""

    @staticmethod
    def init_table():
        """确保搜索表和 FTS5 虚拟表存在"""
        with Database.get_cursor() as cursor:
            # FTS5 虚拟表用于全文搜索
            cursor.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
                    video_hash,
                    title,
                    description,
                    tags,
                    content='search_index',
                    content_rowid='id'
                )
            ''')

            # 原始数据表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS search_index (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_hash VARCHAR(128) NOT NULL UNIQUE,
                    title TEXT NOT NULL DEFAULT '',
                    description TEXT DEFAULT '',
                    tags TEXT DEFAULT '',
                    duration REAL DEFAULT 0,
                    library_id INTEGER DEFAULT 0,
                    path TEXT DEFAULT '',
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
            ''')

            # 创建索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_search_hash ON search_index(video_hash)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_search_library ON search_index(library_id)')

            # 触发器：保持 FTS5 和原始表同步
            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS search_ai AFTER INSERT ON search_index BEGIN
                    INSERT INTO search_fts(rowid, video_hash, title, description, tags)
                    VALUES (new.id, new.video_hash, new.title, new.description, new.tags);
                END
            ''')

            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS search_ad AFTER DELETE ON search_index BEGIN
                    INSERT INTO search_fts(search_fts, rowid, video_hash, title, description, tags)
                    VALUES ('delete', old.id, old.video_hash, old.title, old.description, old.tags);
                END
            ''')

            cursor.execute('''
                CREATE TRIGGER IF NOT EXISTS search_au AFTER UPDATE ON search_index BEGIN
                    INSERT INTO search_fts(search_fts, rowid, video_hash, title, description, tags)
                    VALUES ('delete', old.id, old.video_hash, old.title, old.description, old.tags);
                    INSERT INTO search_fts(rowid, video_hash, title, description, tags)
                    VALUES (new.id, new.video_hash, new.title, new.description, new.tags);
                END
            ''')

    # ============ 索引操作 ============

    @staticmethod
    def index_video(index: SearchIndex) -> int:
        """索引视频（创建或更新）"""
        SearchDB.init_table()
        now = datetime.utcnow().isoformat()

        # 检查是否已存在
        existing = SearchDB.get_by_hash(index.video_hash)
        if existing:
            # 更新
            with Database.get_cursor() as cursor:
                cursor.execute('''
                    UPDATE search_index SET
                        title = ?,
                        description = ?,
                        tags = ?,
                        duration = ?,
                        library_id = ?,
                        path = ?,
                        updated_at = ?
                    WHERE video_hash = ?
                ''', (
                    index.title,
                    index.description,
                    index.tags,
                    index.duration,
                    index.library_id,
                    index.path,
                    now,
                    index.video_hash,
                ))
            return existing.id
        else:
            # 创建
            with Database.get_cursor() as cursor:
                cursor.execute('''
                    INSERT INTO search_index
                    (video_hash, title, description, tags, duration, library_id, path, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    index.video_hash,
                    index.title,
                    index.description,
                    index.tags,
                    index.duration,
                    index.library_id,
                    index.path,
                    now,
                    now,
                ))
                return cursor.lastrowid

    @staticmethod
    def get_by_hash(video_hash: str) -> Optional[SearchIndex]:
        """根据 hash 获取索引"""
        SearchDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute('SELECT * FROM search_index WHERE video_hash = ?', (video_hash,))
            row = cursor.fetchone()
            if row:
                return SearchDB._row_to_index(row)
            return None

    @staticmethod
    def delete_by_hash(video_hash: str) -> bool:
        """删除索引"""
        SearchDB.init_table()
        with Database.get_cursor() as cursor:
            cursor.execute('DELETE FROM search_index WHERE video_hash = ?', (video_hash,))
            return cursor.rowcount > 0

    @staticmethod
    def bulk_index(indices: List[SearchIndex]) -> int:
        """批量索引"""
        count = 0
        for index in indices:
            SearchDB.index_video(index)
            count += 1
        return count

    # ============ 搜索操作 ============

    @staticmethod
    def search(query: str, library_id: int = None, limit: int = 50, offset: int = 0) -> tuple:
        """
        全文搜索

        Args:
            query: 搜索关键词
            library_id: 可选，限制在某个资源库
            limit: 返回数量
            offset: 偏移量

        Returns:
            (results, total) 元组
        """
        SearchDB.init_table()

        if not query or not query.strip():
            return [], 0

        # 处理搜索词，支持中文分词
        query = query.strip()

        with Database.get_cursor() as cursor:
            # 构建 WHERE 子句
            where_clauses = ["search_fts MATCH ?"]
            params = [query]

            if library_id is not None:
                where_clauses.append("si.library_id = ?")
                params.append(library_id)

            where_sql = " AND ".join(where_clauses)

            # 搜索查询
            sql = f'''
                SELECT si.*,
                       bm25(search_fts) as rank,
                       highlight(search_fts, 1, '<mark>', '</mark>') as title_highlight,
                       snippet(search_fts, 2, '<mark>', '</mark>', '...', 20) as desc_snippet
                FROM search_fts fts
                JOIN search_index si ON fts.rowid = si.id
                WHERE {where_sql}
                ORDER BY rank
                LIMIT ? OFFSET ?
            '''
            params.extend([limit, offset])

            cursor.execute(sql, params)
            rows = cursor.fetchall()

            # 获取总数
            count_sql = f'''
                SELECT COUNT(*) FROM search_fts fts
                JOIN search_index si ON fts.rowid = si.id
                WHERE {where_sql}
            '''
            cursor.execute(count_sql, params[:-2])  # 去掉 limit/offset
            total = cursor.fetchone()[0]

            results = []
            for row in rows:
                index = SearchDB._row_to_index(row)
                result = index.to_dict()
                result['rank'] = row['rank']
                result['title_highlight'] = row['title_highlight']
                result['desc_snippet'] = row['desc_snippet']
                results.append(result)

            return results, total

    @staticmethod
    def suggest(keyword: str, limit: int = 10) -> List[str]:
        """获取搜索建议（自动补全）"""
        SearchDB.init_table()

        if not keyword or not keyword.strip():
            return []

        keyword = keyword.strip()

        with Database.get_cursor() as cursor:
            # 从标题中匹配
            cursor.execute('''
                SELECT DISTINCT title FROM search_index
                WHERE title LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
            ''', (f'%{keyword}%', limit))

            suggestions = [row[0] for row in cursor.fetchall()]

            # 也从标签中匹配
            cursor.execute('''
                SELECT DISTINCT value FROM search_index, json_each(tags)
                WHERE value LIKE ?
                LIMIT ?
            ''', (f'%{keyword}%', limit // 2))

            for row in cursor.fetchall():
                if row[0] not in suggestions:
                    suggestions.append(row[0])

            return suggestions[:limit]

    @staticmethod
    def get_all_tags(library_id: int = None) -> List[str]:
        """获取所有标签"""
        SearchDB.init_table()
        with Database.get_cursor() as cursor:
            if library_id is not None:
                cursor.execute('''
                    SELECT DISTINCT tags FROM search_index
                    WHERE library_id = ? AND tags != ''
                ''', (library_id,))
            else:
                cursor.execute('SELECT DISTINCT tags FROM search_index WHERE tags != ""')

            all_tags = set()
            for row in cursor.fetchall():
                if row[0]:
                    # 逗号分隔的标签
                    for tag in row[0].split(','):
                        tag = tag.strip()
                        if tag:
                            all_tags.add(tag)
            return sorted(all_tags)

    @staticmethod
    def rebuild_index():
        """重建 FTS5 索引"""
        with Database.get_cursor() as cursor:
            # 删除并重建 FTS 表
            cursor.execute('INSERT INTO search_fts(search_fts) VALUES("rebuild")')

    # ============ 辅助方法 ============

    @staticmethod
    def _row_to_index(row: sqlite3.Row) -> SearchIndex:
        """将数据库行转换为 SearchIndex 对象"""
        return SearchIndex(
            id=row['id'],
            video_hash=row['video_hash'],
            title=row['title'] or '',
            description=row['description'] or '',
            tags=row['tags'] or '',
            duration=row['duration'] or 0.0,
            library_id=row['library_id'] or 0,
            path=row['path'] or '',
            created_at=datetime.fromisoformat(row['created_at']) if row.get('created_at') else datetime.utcnow(),
            updated_at=datetime.fromisoformat(row['updated_at']) if row.get('updated_at') else datetime.utcnow(),
        )
