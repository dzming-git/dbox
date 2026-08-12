#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一任务管理器

中立能力：将「外置脚本任务」「上传任务」「缩略图生成任务」等后台异步任务收敛到
同一张任务表中，供前端的「任务管理器」统一展示进度、状态与待处理红点。

不依赖任何业务模块，仅操作 data/tasks.db（WAL 模式 + 进程锁）。
被主 Web 服务、扩展宿主、下载器共同复用。
"""
import os
import json
import time
import sqlite3
import threading
from contextlib import contextmanager

# 任务状态
STATUS_PENDING = 'pending'
STATUS_RUNNING = 'running'
STATUS_AWAITING = 'awaiting_input'
STATUS_COMPLETED = 'completed'
STATUS_FAILED = 'failed'
STATUS_CANCELLED = 'cancelled'

_VALID_STATUS = {
    STATUS_PENDING, STATUS_RUNNING, STATUS_AWAITING,
    STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED,
}

_ACTION_KIND_SCRIPT_INTERACTIVE = 'script_interactive'  # 需到脚本交互接口处理
_ACTION_KIND_NAVIGATE = 'navigate'                       # 需跳转到某页面处理

_lock = threading.Lock()
_db_path = None
_initialized = False


def init_task_manager(data_dir):
    """初始化任务管理器，创建数据表。data_dir 为项目 data 目录。"""
    global _db_path, _initialized
    if _initialized and _db_path:
        return
    _db_path = os.path.join(data_dir, 'tasks.db')
    os.makedirs(os.path.dirname(_db_path), exist_ok=True)
    with _conn() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            progress INTEGER NOT NULL DEFAULT 0,
            stage TEXT,
            detail TEXT,
            owner_id INTEGER,
            library_id INTEGER,
            action_required INTEGER NOT NULL DEFAULT 0,
            action_role TEXT,
            action_kind TEXT,
            action_hint TEXT,
            action_data TEXT,
            params TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_owner ON tasks(owner_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_action ON tasks(action_required, action_role)')
        # 兼容旧库：补充 params 列（存储可重放的任务参数，供失败重试使用）
        try:
            conn.execute('ALTER TABLE tasks ADD COLUMN params TEXT')
        except sqlite3.OperationalError:
            pass
    _initialized = True


@contextmanager
def _conn():
    if not _db_path:
        raise RuntimeError('task_manager 未初始化，请先调用 init_task_manager')
    conn = sqlite3.connect(_db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now():
    return time.time()


def _row_to_dict(row):
    d = dict(row)
    d['action_required'] = bool(d.get('action_required'))
    for k in ('created_at', 'updated_at'):
        d[k] = d[k]
    try:
        d['action_data'] = json.loads(d['action_data']) if d.get('action_data') else None
    except (ValueError, TypeError):
        d['action_data'] = None
    try:
        d['params'] = json.loads(d['params']) if d.get('params') else None
    except (ValueError, TypeError):
        d['params'] = None
    return d


def create_task(task_id, kind, title, owner_id=None, library_id=None,
                status=STATUS_RUNNING, progress=0, stage=None, detail=None, params=None):
    """登记一个新任务，返回任务 dict。"""
    params_str = json.dumps(params, ensure_ascii=False) if params is not None else None
    with _lock:
        with _conn() as conn:
            now = _now()
            conn.execute(
                '''INSERT OR REPLACE INTO tasks
                   (task_id, kind, title, status, progress, stage, detail,
                    owner_id, library_id, action_required, action_role, action_kind,
                    action_hint, action_data, params, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,0,NULL,NULL,NULL,NULL,?,?,?)''',
                (task_id, kind, title, status, progress, stage, detail,
                 owner_id, library_id, params_str, now, now),
            )
    return get_task(task_id)


def update_task(task_id, status=None, progress=None, stage=None, detail=None):
    """更新任务进度/状态。"""
    with _lock:
        with _conn() as conn:
            cur = conn.execute('SELECT * FROM tasks WHERE task_id=?', (task_id,))
            row = cur.fetchone()
            if not row:
                return None
            new_status = status if status is not None else row['status']
            new_progress = progress if progress is not None else row['progress']
            new_stage = stage if stage is not None else row['stage']
            new_detail = detail if detail is not None else row['detail']
            if new_status not in _VALID_STATUS:
                new_status = row['status']
            conn.execute(
                '''UPDATE tasks SET status=?, progress=?, stage=?, detail=?, updated_at=?
                   WHERE task_id=?''',
                (new_status, new_progress, new_stage, new_detail, _now(), task_id),
            )
    return get_task(task_id)


def set_action_required(task_id, action_role, action_kind, action_hint, action_data=None):
    """标记任务需要用户/管理员处理（用于红点）。"""
    if action_kind not in (_ACTION_KIND_SCRIPT_INTERACTIVE, _ACTION_KIND_NAVIGATE):
        raise ValueError(f'未知 action_kind: {action_kind}')
    data_str = json.dumps(action_data, ensure_ascii=False) if action_data is not None else None
    with _lock:
        with _conn() as conn:
            conn.execute(
                '''UPDATE tasks SET action_required=1, action_role=?, action_kind=?,
                   action_hint=?, action_data=?, status=?, updated_at=?
                   WHERE task_id=?''',
                (action_role, action_kind, action_hint, data_str,
                 STATUS_AWAITING, _now(), task_id),
            )
    return get_task(task_id)


def clear_action_required(task_id, resume_status=STATUS_RUNNING):
    """用户/管理员处理完毕后清除红点，并将任务状态恢复为进行中。"""
    with _lock:
        with _conn() as conn:
            conn.execute(
                '''UPDATE tasks SET action_required=0, action_role=NULL, action_kind=NULL,
                   action_hint=NULL, action_data=NULL, status=?, updated_at=?
                   WHERE task_id=?''',
                (resume_status, _now(), task_id),
            )
    return get_task(task_id)


def sync_job(job):
    """从脚本任务（ScriptJobManager 的任务 dict）同步到统一任务表。"""
    task_id = 'script:' + str(job.get('id'))
    interactive = job.get('interactive')
    if interactive:
        action_role = 'admin'
        action_kind = _ACTION_KIND_SCRIPT_INTERACTIVE
        action_hint = (interactive.get('prompt') or '脚本等待处理')[:200]
        action_data = {'job_id': job.get('id')}
        status = STATUS_AWAITING
    else:
        action_role = None
        action_kind = None
        action_hint = None
        action_data = None
        status = job.get('status', STATUS_RUNNING)

    # 记录可重放参数，供失败重试：脚本任务的 script_id + 原始运行参数 + 发起人
    retry_params = {
        'script_id': job.get('script_id'),
        'params': job.get('params'),
        'owner_id': job.get('owner_id'),
    }
    with _lock:
        with _conn() as conn:
            now = _now()
            conn.execute(
                '''INSERT OR REPLACE INTO tasks
                   (task_id, kind, title, status, progress, stage, detail,
                    owner_id, library_id, action_required, action_role, action_kind,
                    action_hint, action_data, params, created_at, updated_at)
                   VALUES (?, 'script', ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?,
                           ?, COALESCE((SELECT created_at FROM tasks WHERE task_id=?), ?), ?)''',
                (
                    task_id,
                    job.get('name') or job.get('script_id') or '脚本任务',
                    status,
                    int(job.get('progress', 0) or 0),
                    job.get('stage'),
                    job.get('detail') or job.get('error'),
                    1 if interactive else 0,
                    action_role, action_kind, action_hint,
                    json.dumps(action_data, ensure_ascii=False) if action_data else None,
                    json.dumps(retry_params, ensure_ascii=False),
                    task_id, now, now,
                ),
            )
    return get_task(task_id)


def get_task(task_id):
    with _conn() as conn:
        row = conn.execute('SELECT * FROM tasks WHERE task_id=?', (task_id,)).fetchone()
    return _row_to_dict(row) if row else None


def get_tasks(role='user', user_id=None, limit=50):
    """返回当前用户可见的任务列表（按更新时间倒序）。

    - 普通用户：仅看到自己发起的任务（owner_id == user_id）。
    - 管理员：看到全部脚本任务 + 自己发起的上传任务。
    """
    with _conn() as conn:
        if role == 'admin':
            rows = conn.execute(
                '''SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?''', (limit,)
            ).fetchall()
        else:
            if user_id is None:
                rows = []
            else:
                rows = conn.execute(
                    '''SELECT * FROM tasks WHERE owner_id=? ORDER BY updated_at DESC LIMIT ?''',
                    (user_id, limit),
                ).fetchall()
    return [_row_to_dict(r) for r in rows]


def count_action_required(role='user', user_id=None):
    """红点计数：当前用户/角色下需要处理的任务数。"""
    with _conn() as conn:
        if role == 'admin':
            cnt = conn.execute(
                'SELECT COUNT(*) FROM tasks WHERE action_required=1 AND action_role=?',
                ('admin',),
            ).fetchone()[0]
        else:
            if user_id is None:
                cnt = 0
            else:
                cnt = conn.execute(
                    '''SELECT COUNT(*) FROM tasks
                       WHERE action_required=1 AND action_role=? AND owner_id=?''',
                    ('user', user_id),
                ).fetchone()[0]
    return int(cnt)


def prune_old(keep_days=7):
    """清理已完成且超过 keep_days 天的旧任务（保留近期记录供查看）。"""
    cutoff = _now() - keep_days * 86400
    with _lock:
        with _conn() as conn:
            conn.execute(
                '''DELETE FROM tasks
                   WHERE status IN (?, ?, ?) AND updated_at < ?''',
                (STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED, cutoff),
            )


# 允许用户主动删除的「终态」状态：进行中的任务不允许被前端直接删，避免误删
_DELETABLE_STATUSES = frozenset({STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED})


def delete_task(task_id, is_admin=False, owner_id=None):
    """删除一条任务记录。

    - 普通用户（is_admin=False）：仅允许删除自己发起的、且处于终态的任务；
    - 管理员（is_admin=True）：可删除任意任务（仍仅限终态，保护进行中的任务）。
    - 返回值：True 表示成功删除；False 表示任务不存在或无权删除；
            None 表示任务仍处于进行中，不允许删除。
    """
    task = get_task(task_id)
    if not task:
        return False
    status = task.get('status')
    if status not in _DELETABLE_STATUSES:
        # 进行中（含等待处理）的任务不允许删除，防止误删仍在执行的任务
        return None
    if not is_admin and task.get('owner_id') not in (None, owner_id):
        return False
    with _lock:
        with _conn() as conn:
            conn.execute('DELETE FROM tasks WHERE task_id=?', (task_id,))
    return True
