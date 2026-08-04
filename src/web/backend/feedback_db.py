"""反馈建议独立数据库模块。

将反馈/建议数据从原本的 issues.json 单文件存储，迁移到独立的 SQLite 数据库
（{runtime_dir}/databases/feedback.db），与主应用数据库（dbox.db）完全解耦。

本模块持有自己独立的 SQLAlchemy engine / session，不依赖 Flask-SQLAlchemy 的 db，
确保反馈数据在物理上、逻辑上都处于一个单独的数据库中。
"""
import os
import sys
import json
import threading
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, Boolean, ForeignKey
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, scoped_session

try:
    from liblog import get_service_logger as _get_service_logger

    def get_service_logger(name=''):
        return _get_service_logger(name)
except Exception:  # pragma: no cover - 运行时由 main 注入
    from logging import getLogger as _getLogger

    def get_service_logger(name=''):  # type: ignore
        return _getLogger(name)

_log = get_service_logger('dbox-web')


def get_runtime_dir():
    """获取运行时目录（与 system_info_api.get_runtime_dir 保持一致）。

    项目根的 data/ 为唯一权威数据存储位置。
    """
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    # 防止命中 src/data：当 base 解析到 src 目录时，再向上一层到项目根
    if os.path.basename(base) == 'src':
        base = os.path.dirname(base)
    candidates = [
        os.path.join(base, 'data'),
        os.path.join(base, 'runtime'),
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return candidates[0]


# 反馈独立数据库路径：{runtime_dir}/databases/feedback.db
FEEDBACK_DB_PATH = os.path.join(get_runtime_dir(), 'databases', 'feedback.db')
FEEDBACK_DB_URI = 'sqlite:///' + FEEDBACK_DB_PATH

# 独立的引擎与会话（不属于主应用的 db）
_engine = create_engine(FEEDBACK_DB_URI, connect_args={'check_same_thread': False})
_Base = declarative_base()
_SessionFactory = sessionmaker(bind=_engine)
_Session = scoped_session(_SessionFactory)
_db_lock = threading.Lock()


class FeedbackIssue(_Base):
    """反馈/建议主表。"""
    __tablename__ = 'feedback_issues'

    id = Column(String(32), primary_key=True)          # 反馈单号，如 202608040001
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default='open')
    submitter = Column(String(64), nullable=True)
    category = Column(String(32), nullable=True)
    source = Column(String(32), nullable=True, default='web')
    auto_classified = Column(Boolean, default=False)
    classification = Column(String(32), nullable=True)
    processed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now)

    comments = relationship(
        'FeedbackComment', back_populates='issue',
        cascade='all, delete-orphan', order_by='FeedbackComment.created_at'
    )


class FeedbackComment(_Base):
    """反馈评论/留言表。"""
    __tablename__ = 'feedback_comments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    issue_id = Column(String(32), ForeignKey('feedback_issues.id'), nullable=False, index=True)
    author = Column(String(64), nullable=False)
    author_role = Column(Integer, nullable=False, default=1)  # 1=用户, 2=自动助手, 3=管理员
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    issue = relationship('FeedbackIssue', back_populates='comments')


def init_feedback_db():
    """创建表结构并自动迁移旧的 issues.json 数据（幂等）。"""
    os.makedirs(os.path.dirname(FEEDBACK_DB_PATH), exist_ok=True)
    _Base.metadata.create_all(_engine)
    _migrate_legacy_json()


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _migrate_legacy_json():
    """将旧的 issues.json / suggestions.json 数据一次性迁移进独立数据库。

    迁移后保留原文件为 .bak，避免误删。已迁移过（数据库非空）则跳过。
    """
    runtime_dir = get_runtime_dir()
    legacy_files = [
        os.path.join(runtime_dir, 'issues.json'),
        os.path.join(runtime_dir, 'suggestions.json'),
    ]
    with _db_lock:
        with _Session() as session:
            if session.query(FeedbackIssue).first() is not None:
                return  # 数据库已有数据，不再迁移
            all_issues = []
            for path in legacy_files:
                if not os.path.exists(path):
                    continue
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception as e:
                    _log.warning(f'读取旧反馈文件失败 {path}: {e}')
                    continue
                if isinstance(data, dict):
                    data = data.get('issues', [])
                if isinstance(data, list):
                    all_issues.extend(data)
            if not all_issues:
                return
            for raw in all_issues:
                issue = FeedbackIssue(
                    id=raw.get('id'),
                    title=raw.get('title', ''),
                    content=raw.get('content', ''),
                    status=raw.get('status', 'open'),
                    submitter=raw.get('submitter'),
                    category=raw.get('category'),
                    source=raw.get('source', 'web'),
                    auto_classified=bool(raw.get('auto_classified', False)),
                    classification=raw.get('classification'),
                    processed_at=_parse_dt(raw.get('processed_at')),
                    created_at=_parse_dt(raw.get('created_at')) or datetime.now(),
                    updated_at=_parse_dt(raw.get('updated_at')) or datetime.now(),
                )
                for c in raw.get('comments', []) or []:
                    issue.comments.append(FeedbackComment(
                        author=c.get('author', ''),
                        author_role=c.get('author_role', 1),
                        content=c.get('content', ''),
                        created_at=_parse_dt(c.get('created_at')) or datetime.now(),
                    ))
                session.add(issue)
            session.commit()
            _log.info(f'已从 issues.json/suggestions.json 迁移 {len(all_issues)} 条反馈到独立数据库')
            # 迁移完成后备份旧文件，避免重复迁移与误删
            for path in legacy_files:
                if os.path.exists(path):
                    try:
                        os.rename(path, path + '.bak')
                    except Exception as e:
                        _log.warning(f'备份旧反馈文件失败 {path}: {e}')


def get_session():
    """返回一个受作用域管理的 session（每次调用线程安全）。"""
    return _Session()


# ============ 对外数据访问辅助 ============
STATUS_MAP = {
    'open': 'open',
    'in_progress': 'in_progress',
    'pending_verification': 'pending_verification',
    'verified': 'verified',
    'closed': 'closed',
    'rejected': 'rejected',
}


def issue_to_dict(issue: FeedbackIssue):
    return {
        'id': issue.id,
        'title': issue.title,
        'content': issue.content,
        'status': issue.status,
        'submitter': issue.submitter,
        'category': issue.category,
        'source': issue.source,
        'auto_classified': issue.auto_classified,
        'classification': issue.classification,
        'processed_at': issue.processed_at.isoformat() if issue.processed_at else None,
        'created_at': issue.created_at.isoformat() if issue.created_at else None,
        'updated_at': issue.updated_at.isoformat() if issue.updated_at else None,
        'comments': [
            {
                'author': c.author,
                'author_role': c.author_role,
                'content': c.content,
                'created_at': c.created_at.isoformat() if c.created_at else None,
            }
            for c in issue.comments
        ],
    }


# ============ 写操作辅助（供自动处理脚本 / 后端共用） ============
def db_set_status(issue_id: str, status: str, classification: str = None) -> bool:
    """更新反馈状态（幂等）。"""
    with get_session() as session:
        issue = session.get(FeedbackIssue, issue_id)
        if not issue:
            return False
        issue.status = status
        if classification is not None:
            issue.classification = classification
        issue.updated_at = datetime.now()
        session.commit()
        return True


def db_append_comment(issue_id: str, author: str, author_role: int, content: str) -> bool:
    """追加一条评论（幂等由调用方负责去重）。"""
    with get_session() as session:
        issue = session.get(FeedbackIssue, issue_id)
        if not issue:
            return False
        issue.comments.append(FeedbackComment(
            author=author,
            author_role=author_role,
            content=content,
            created_at=datetime.now(),
        ))
        issue.updated_at = datetime.now()
        session.commit()
        return True
