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
    feedback_extra = Column(Text, nullable=True)  # 附加结构化数据（AI 任务队列、契约结果等，JSON）

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
    _migrate_feedback_extra_column()
    _migrate_legacy_json()


def _migrate_feedback_extra_column():
    """幂等迁移：为 feedback_issues 增加 feedback_extra 列（SQLite 加列安全）。

    直接尝试 ALTER，若列已存在则捕获 DuplicateColumn 错误忽略。
    """
    import sqlalchemy
    try:
        with _engine.connect() as conn:
            conn.execute(
                sqlalchemy.text('ALTER TABLE feedback_issues ADD COLUMN feedback_extra TEXT')
            )
            conn.commit()
    except Exception as e:
        # 列已存在 / 其他可忽略错误
        err = str(e).lower()
        if 'duplicate column' in err or 'already exists' in err:
            return
        _log.warning(f'feedback_extra 列迁移异常（可忽略）: {e}')


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


def _parse_extra(raw):
    """将 feedback_extra TEXT 解析为 dict（解析失败返回 {}）。"""
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


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
        'closed_reason': issue.classification,  # 关闭原因（resolved/dismissed），前端据此区分已解决/已关闭
        'processed_at': issue.processed_at.isoformat() if issue.processed_at else None,
        'created_at': issue.created_at.isoformat() if issue.created_at else None,
        'updated_at': issue.updated_at.isoformat() if issue.updated_at else None,
        'feedback_extra': _parse_extra(issue.feedback_extra),
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


def db_search_similar_issues(prompt: str = None, category: str = None,
                             statuses=('open', 'in_progress', 'pending_verification'),
                             limit: int = 50):
    """返回仍未关闭的反馈单候选（按类别筛选），供 AI 判定是否已有同类问题单。

    不做模糊匹配——相似度判定交由调用方（拓展宿主）按提示词/关键词评分，本函数只负责
    从数据库捞出「仍待处理」的同类候选，避免对已关闭/已验证单误续写。仅返回
    id / title / content / status 四个轻量字段，便于跨进程传输与评分。
    """
    init_feedback_db()
    with get_session() as session:
        q = session.query(FeedbackIssue)
        if category:
            q = q.filter(FeedbackIssue.category == category)
        if statuses:
            q = q.filter(FeedbackIssue.status.in_(statuses))
        q = q.order_by(FeedbackIssue.updated_at.desc())
        rows = q.limit(limit).all()
        return [
            {'id': r.id, 'title': r.title, 'content': r.content, 'status': r.status}
            for r in rows
        ]


def db_delete_issue(issue_id: str) -> bool:
    """删除一条反馈单（含其全部评论，依赖 comments 的 cascade 级联删除）。

    线程安全（独立 session）。仅管理员可调用，鉴权由 suggestion_api 负责。
    返回 True 表示已删除；单号不存在返回 False。
    """
    with get_session() as session:
        issue = session.get(FeedbackIssue, issue_id)
        if not issue:
            return False
        session.delete(issue)  # cascade='all, delete-orphan' 自动清理 feedback_comments
        session.commit()
        return True


def db_get_extra(issue_id: str) -> dict:
    """读取 feedback_extra（JSON）字段，不存在/为空时返回 {}。"""
    init_feedback_db()
    with get_session() as session:
        issue = session.get(FeedbackIssue, issue_id)
        if not issue:
            return {}
        raw = issue.feedback_extra
        if not raw:
            return {}
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def db_set_extra(issue_id: str, extra: dict) -> bool:
    """整体写回 feedback_extra（JSON）。仅覆盖整个字段，调用方需先 get 再 merge。"""
    init_feedback_db()
    with get_session() as session:
        issue = session.get(FeedbackIssue, issue_id)
        if not issue:
            return False
        issue.feedback_extra = json.dumps(extra, ensure_ascii=False)
        issue.updated_at = datetime.now()
        session.commit()
        return True


def db_update_extra(issue_id: str, patch: dict) -> bool:
    """局部合并写回 feedback_extra（JSON）。线程安全，每次独立 session。"""
    init_feedback_db()
    with get_session() as session:
        issue = session.get(FeedbackIssue, issue_id)
        if not issue:
            return False
        raw = issue.feedback_extra
        data = {}
        if raw:
            try:
                data = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except Exception:
                data = {}
        if not isinstance(data, dict):
            data = {}
        data.update(patch)
        issue.feedback_extra = json.dumps(data, ensure_ascii=False)
        issue.updated_at = datetime.now()
        session.commit()
        return True


# ============ 建单辅助（供 AI 助手 / 后端 / 自动处理共用） ============
def generate_issue_id(date=None):
    """生成 yyyymmdd + 4 位流水号，按当天最大序号 +1。"""
    date = date or datetime.now()
    date_str = date.strftime('%Y%m%d')
    max_seq = 0
    with get_session() as session:
        for issue in session.query(FeedbackIssue).all():
            iid = issue.id or ''
            if isinstance(iid, str) and iid.startswith(date_str) and len(iid) == 12:
                try:
                    seq = int(iid[8:12])
                    if seq > max_seq:
                        max_seq = seq
                except ValueError:
                    pass
    return f"{date_str}{max_seq + 1:04d}"


def db_create_issue(title: str, content: str, category: str = 'suggestion',
                    submitter: str = '游客', source: str = 'web',
                    auto_classified: bool = False, classification: str = None,
                    status: str = 'open', extra: dict = None,
                    comment: str = None, comments: list = None) -> str:
    """创建一条反馈，返回新单号（yyyymmdd+4 位）。

    线程安全（独立 session）。供 AI 助手与 suggestion_api 复用，避免重复建单逻辑。
    AI 助手提单时使用 submitter='自动助手'、source='assistant'、auto_classified=True，
    与项目「反馈中心交互使用自动助手身份」的准则一致。

    status / extra 为可选扩展：AI 助手处理完成后的「跟踪单」可传入
    status='pending_verification' 与 extra={'git_commit': ..., 'task_id': ...} 等，
    便于反馈中心展示「待验证」状态并关联处理动作。

    comment 为可选首条留言：传入后作为「自动助手」身份的首条 reply 写入 feedback_comments，
    用于承载「AI 做了什么 / 修复内容」等处理说明，使反馈单结构为
    「标题=概括、内容=问题描述、留言=AI 的处理动作」。
    """
    init_feedback_db()
    t = (title or '').strip()
    if not t:
        t = '(无标题)'
    if status not in ('open', 'pending', 'pending_verification', 'closed', 'rejected'):
        status = 'open'
    now = datetime.now()
    issue = FeedbackIssue(
        id=generate_issue_id(),
        title=t,
        content=(content or '').strip(),
        status=status,
        submitter=submitter,
        category=category if category in ('bug', 'suggestion', 'other') else 'suggestion',
        source=source,
        auto_classified=auto_classified,
        classification=classification,
        created_at=now,
        updated_at=now,
        feedback_extra=json.dumps(extra, ensure_ascii=False) if extra else None,
    )
    # 若存在首条留言（AI 的处理说明），以「自动助手」身份写入 feedback_comments。
    # 与项目准则一致：反馈中心交互使用自动助手身份（author_role=2）。
    if comment and comment.strip():
        issue.comments.append(FeedbackComment(
            author='自动助手',
            author_role=2,
            content=comment.strip(),
            created_at=now,
        ))
    # 额外的「自动助手」身份留言（如分析根因、解决说明），按序追加，使反馈单
    # 形成完整的「标题=概括、内容=问题描述、留言=分析+解决」处理记录。
    for c in (comments or []):
        if c and str(c).strip():
            issue.comments.append(FeedbackComment(
                author='自动助手',
                author_role=2,
                content=str(c).strip(),
                created_at=now,
            ))
    with get_session() as session:
        session.add(issue)
        session.commit()
        new_id = issue.id
    return new_id
