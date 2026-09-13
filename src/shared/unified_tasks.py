#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一任务管理器（唯一真源）

中立能力：将「资源库扫描」「上传」「缩略图生成」「插件」等后台异步任务收敛到
同一张任务表中，供前端的「任务管理器」统一展示进度、状态、取消与重试。

不依赖任何业务模块，仅操作 data/tasks.db（WAL 模式 + 进程锁）。
被主 Web 服务、扩展宿主、下载器共同复用。

约定：
- 本模块只负责**记录与协调**，不负责执行。执行方负责在循环中调用
  ``is_cancel_requested()`` 主动检查取消信号，并在收尾时调用 ``finish_task()``；
- ``cancel_requested`` 是「请求」，不是「已停止」。任务是否真的停下取决于执行方
  有没有检查点，因此取消后状态可能仍是 running 一小段时间。
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

# 进行中（可请求取消、参与「任务结束后关机」的活跃计数）
_ACTIVE_STATUSES = frozenset({STATUS_PENDING, STATUS_RUNNING, STATUS_AWAITING})
# 终态（不可取消、可删除、可被清理）
_TERMINAL_STATUSES = frozenset({STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED})

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
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            error_code TEXT,
            started_at REAL,
            finished_at REAL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_owner ON tasks(owner_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_action ON tasks(action_required, action_role)')
        # 兼容旧库：逐列补充（已存在的列会抛 OperationalError，忽略即可）
        for _ddl in (
            'ALTER TABLE tasks ADD COLUMN params TEXT',
            'ALTER TABLE tasks ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0',
            'ALTER TABLE tasks ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0',
            'ALTER TABLE tasks ADD COLUMN error_code TEXT',
            'ALTER TABLE tasks ADD COLUMN started_at REAL',
            'ALTER TABLE tasks ADD COLUMN finished_at REAL',
        ):
            try:
                conn.execute(_ddl)
            except sqlite3.OperationalError:
                pass
    _initialized = True
    # 进程启动时清理过期终态任务，避免 tasks.db 只增不删
    try:
        prune_old()
    except Exception:
        pass


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
    d['cancel_requested'] = bool(d.get('cancel_requested'))
    d['attempts'] = int(d.get('attempts') or 0)
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


def update_task(task_id, status=None, progress=None, stage=None, detail=None,
                error_code=None):
    """更新任务进度/状态。

    error_code 仅在显式传入时写入（传 '' 表示清空），用于前端区分失败原因。
    """
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
            new_error = row['error_code'] if error_code is None else (error_code or None)
            if new_status not in _VALID_STATUS:
                new_status = row['status']
            conn.execute(
                '''UPDATE tasks SET status=?, progress=?, stage=?, detail=?, error_code=?,
                   updated_at=? WHERE task_id=?''',
                (new_status, new_progress, new_stage, new_detail, new_error,
                 _now(), task_id),
            )
    return get_task(task_id)


def mark_started(task_id):
    """标记任务开始执行（写入 started_at，幂等）。"""
    with _lock:
        with _conn() as conn:
            conn.execute(
                '''UPDATE tasks SET status=?, started_at=COALESCE(started_at, ?), updated_at=?
                   WHERE task_id=? AND status NOT IN (?, ?, ?)''',
                (STATUS_RUNNING, _now(), _now(), task_id,
                 STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED),
            )
    return get_task(task_id)


def finish_task(task_id, status, progress=None, stage=None, detail=None,
                error_code=None):
    """结束任务：写入终态与 finished_at。

    status 必须是 completed / failed / cancelled 之一，其它值会被忽略（返回 None），
    避免调用方误把 running 写进来导致任务永远不结束。
    """
    if status not in _TERMINAL_STATUSES:
        return None
    with _lock:
        with _conn() as conn:
            row = conn.execute(
                'SELECT progress, stage, detail, error_code FROM tasks WHERE task_id=?',
                (task_id,),
            ).fetchone()
            if not row:
                return None
            new_progress = row['progress'] if progress is None else progress
            new_stage = row['stage'] if stage is None else stage
            new_detail = row['detail'] if detail is None else detail
            if status == STATUS_COMPLETED:
                new_error = None
            else:
                new_error = row['error_code'] if error_code is None else (error_code or None)
            conn.execute(
                '''UPDATE tasks SET status=?, progress=?, stage=?, detail=?, error_code=?,
                   finished_at=?, updated_at=? WHERE task_id=?''',
                (status, new_progress, new_stage, new_detail, new_error,
                 _now(), _now(), task_id),
            )
    return get_task(task_id)


def request_cancel(task_id):
    """请求取消任务。

    只置 cancel_requested 标记，**不直接把状态改成 cancelled** —— 是否停下由执行方
    在检查点决定（它会在停下时调用 finish_task(..., 'cancelled')）。已结束的任务忽略。
    """
    task = get_task(task_id)
    if not task:
        return None
    if task.get('status') in _TERMINAL_STATUSES:
        return task
    with _lock:
        with _conn() as conn:
            conn.execute(
                'UPDATE tasks SET cancel_requested=1, updated_at=? WHERE task_id=?',
                (_now(), task_id),
            )
    return get_task(task_id)


def is_cancel_requested(task_id):
    """执行方在检查点调用：是否收到取消请求。"""
    with _conn() as conn:
        row = conn.execute(
            'SELECT cancel_requested FROM tasks WHERE task_id=?', (task_id,)
        ).fetchone()
    return bool(row and row['cancel_requested'])


def bump_attempts(task_id):
    """重试计数 +1（用于展示「已重试 N 次」）。"""
    with _lock:
        with _conn() as conn:
            conn.execute(
                'UPDATE tasks SET attempts=COALESCE(attempts, 0) + 1, updated_at=? WHERE task_id=?',
                (_now(), task_id),
            )
    return get_task(task_id)


def list_active_tasks(limit=500):
    """返回仍在进行中的任务（供「任务结束后关机」等场景判定）。"""
    with _conn() as conn:
        rows = conn.execute(
            '''SELECT * FROM tasks WHERE status IN (?, ?, ?)
               ORDER BY created_at ASC LIMIT ?''',
            (STATUS_PENDING, STATUS_RUNNING, STATUS_AWAITING, limit),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


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
_DELETABLE_STATUSES = _TERMINAL_STATUSES


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
