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
# 被中断：进程重启 / 崩溃导致任务没跑完，但**不是业务失败**。
# 单独一个状态（而不是并入 failed）是为了让界面能区分「跑挂了」与「被打断」，
# 并据此给「继续 / 重试」而不是只显示一个红色的失败。
STATUS_INTERRUPTED = 'interrupted'

_VALID_STATUS = {
    STATUS_PENDING, STATUS_RUNNING, STATUS_AWAITING,
    STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED, STATUS_INTERRUPTED,
}

# 进行中（可请求取消、参与「任务结束后关机」的活跃计数）
_ACTIVE_STATUSES = frozenset({STATUS_PENDING, STATUS_RUNNING, STATUS_AWAITING})
# 终态（不可取消、可删除、可被清理）
_TERMINAL_STATUSES = frozenset({
    STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED, STATUS_INTERRUPTED})

_ACTION_KIND_SCRIPT_INTERACTIVE = 'script_interactive'  # 需到脚本交互接口处理
_ACTION_KIND_NAVIGATE = 'navigate'                       # 需跳转到某页面处理

# ============ 任务能力注册（capability registry） ============
# 任务类型（kind）向框架声明自己**支持哪些后续动作**以及**怎么调用**。
#
# 设计动机：像「继续（断点续跑）」这种能力，是否支持、怎么执行，只有任务的
# 实现方（插件或内置模块）知道。若框架里写 `if kind == 'x': ...`，每接入一种
# 任务就要改一次框架，插件知识还会泄漏进框架。
# 因此改为**注册制**：实现方自己登记，框架只负责查表：
#   - 查得到 → 转发/调用；
#   - 查不到 → 明确判定「该类型任务不支持此能力」，而不是硬编码一份白名单。
CAPABILITY_RESUME = 'resume'   # 断点续跑：从中断处继续，而非从头重来
CAPABILITY_RETRY = 'retry'     # 失败/取消后重跑一次

# 同一进程内登记的动作实现：kind -> callable(task_dict) -> (ok, message[, extra])
# 跨进程的任务（如插件）则通过 endpoint 由框架转发调用。
_RESUME_HANDLERS = {}
_RETRY_HANDLERS = {}

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
        # 能力注册表：某类任务支持哪些后续动作、由哪个服务执行、怎么调用
        conn.execute('''CREATE TABLE IF NOT EXISTS task_capabilities (
            kind TEXT NOT NULL,
            capability TEXT NOT NULL,
            service TEXT NOT NULL,
            endpoint TEXT,
            updated_at REAL,
            PRIMARY KEY (kind, capability)
        )''')
        # 兼容旧库：逐列补充（已存在的列会抛 OperationalError，忽略即可）
        for _ddl in (
            'ALTER TABLE tasks ADD COLUMN owner_service TEXT',
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
    # can_resume / can_retry：框架按注册表判定，**调用方不必知道任何具体任务类型**。
    # 没注册实现的类型一律为 False，界面据此不展示对应入口。
    try:
        d['can_resume'] = bool(
            (d.get('kind') in _RESUME_HANDLERS)
            or get_capability(d.get('kind'), CAPABILITY_RESUME)
        )
    except Exception:
        d['can_resume'] = False
    try:
        d['can_retry'] = bool(
            (d.get('kind') in _RETRY_HANDLERS)
            or get_capability(d.get('kind'), CAPABILITY_RETRY)
        )
    except Exception:
        d['can_retry'] = False
    return d


def create_task(task_id, kind, title, owner_id=None, library_id=None,
                status=STATUS_RUNNING, progress=0, stage=None, detail=None,
                params=None, service=None):
    """登记一个新任务，返回任务 dict。

    service：归属的服务（如 'web' / 'extensions' / 'downloader'）。
    进程重启后据此回收「属于自己、却还在 running」的僵尸任务（见 reclaim_interrupted）。
    """
    params_str = json.dumps(params, ensure_ascii=False) if params is not None else None
    with _lock:
        with _conn() as conn:
            now = _now()
            conn.execute(
                '''INSERT OR REPLACE INTO tasks
                   (task_id, kind, title, status, progress, stage, detail,
                    owner_id, library_id, action_required, action_role, action_kind,
                    action_hint, action_data, params, owner_service, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,0,NULL,NULL,NULL,NULL,?,?,?,?)''',
                (task_id, kind, title, status, progress, stage, detail,
                 owner_id, library_id, params_str, service, now, now),
            )
    return get_task(task_id)


def update_task(task_id, status=None, progress=None, stage=None, detail=None,
                error_code=None, params=None):
    """更新任务进度/状态。

    error_code 仅在显式传入时写入（传 '' 表示清空），用于前端区分失败原因。
    params 用于补充执行过程中才知道的信息（如实际待处理总数）。
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
            new_params = (row['params'] if params is None
                          else json.dumps(params, ensure_ascii=False))
            if new_status not in _VALID_STATUS:
                new_status = row['status']
            conn.execute(
                '''UPDATE tasks SET status=?, progress=?, stage=?, detail=?, error_code=?,
                   params=?, updated_at=? WHERE task_id=?''',
                (new_status, new_progress, new_stage, new_detail, new_error,
                 new_params, _now(), task_id),
            )
    return get_task(task_id)


def reclaim_interrupted(service, include_legacy=True):
    """服务启动时回收「属于自己的僵尸任务」。

    背景：任务执行在进程内的线程里，进程一重启，线程没了，但 tasks.db 里那条记录
    还停在 running —— 于是界面上永远显示「进行中 37%」，既不前进也不失败，
    用户除了干等没有任何办法（重启电脑后回来看到的就是这个）。

    判定依据：**本服务刚启动，它自己此刻不可能有任何任务在跑**，
    所以凡是标记为归属本服务、且处于进行中的任务，都是上一代进程留下的残骸。
    按服务名区分是为了不越界——web 重启不该误伤 downloader 正在跑的任务。

    include_legacy：是否一并回收「没有归属标记」的旧任务。升级前创建的任务没有
    owner_service，若不回收，它们会永远卡着；而回收它们最多误伤一次（升级后
    新建的任务都带标记了），因此默认开启。

    返回被回收的任务 id 列表。
    """
    if not service:
        return []
    if include_legacy:
        where = '(owner_service=? OR owner_service IS NULL)'
        args = (service,)
    else:
        where = 'owner_service=?'
        args = (service,)
    marks = ','.join('?' * len(_ACTIVE_STATUSES))
    with _lock:
        with _conn() as conn:
            rows = conn.execute(
                f'SELECT task_id, progress, detail FROM tasks '
                f'WHERE {where} AND status IN ({marks})',
                args + tuple(_ACTIVE_STATUSES),
            ).fetchall()
            now = _now()
            for r in rows:
                try:
                    prev = int(r['progress'] or 0)
                except (TypeError, ValueError):
                    prev = 0
                conn.execute(
                    '''UPDATE tasks SET status=?, error_code=?, detail=?,
                       finished_at=?, updated_at=? WHERE task_id=?''',
                    (STATUS_INTERRUPTED, 'interrupted',
                     f'服务重启导致中断（停在 {prev}%）：可重试或从中断处继续',
                     now, now, r['task_id']),
                )
    return [r['task_id'] for r in rows]


# ---------------------------------------------------------------- 能力注册

def register_capability(kind, capability, service, endpoint=None):
    """声明「某类任务支持某项能力」。

    kind        任务类型（如 'x' / 'scan'）
    capability  能力名（见 CAPABILITY_* 常量）
    service     由哪个服务执行（决定框架把请求转发到哪）
    endpoint    跨进程调用时的端点路径；同进程内有 handler 的可不填

    幂等：重复注册只更新。这样插件热重载、服务重启动都能安全重新登记。
    """
    if not kind or not capability or not service:
        return False
    with _lock:
        with _conn() as conn:
            conn.execute(
                '''INSERT INTO task_capabilities (kind, capability, service, endpoint, updated_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(kind, capability) DO UPDATE SET
                     service=excluded.service, endpoint=excluded.endpoint,
                     updated_at=excluded.updated_at''',
                (kind, capability, service, endpoint, _now()),
            )
    return True


def unregister_capability(kind, capability):
    """撤销某项能力声明（插件卸载 / 模块停用时）。"""
    with _lock:
        with _conn() as conn:
            conn.execute(
                'DELETE FROM task_capabilities WHERE kind=? AND capability=?',
                (kind, capability),
            )


def get_capability(kind, capability):
    """查询某类任务的某项能力，返回 {service, endpoint}；未注册返回 None。"""
    if not kind or not capability:
        return None
    try:
        with _lock:
            with _conn() as conn:
                row = conn.execute(
                    'SELECT service, endpoint FROM task_capabilities WHERE kind=? AND capability=?',
                    (kind, capability),
                ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def list_capabilities(capability=None):
    """列出已注册的能力。

    指定 capability → {kind: {service, endpoint}}（扁平，便于按能力查）
    不指定         → {kind: {capability: {service, endpoint}}}

    为什么全量查询要嵌套：同一种任务可以同时具备多个能力（如既能继续又能重试），
    若一律用 kind 做键，后写的能力会把先写的覆盖掉，看起来就像只剩一个能力。
    """
    try:
        with _lock:
            with _conn() as conn:
                if capability:
                    rows = conn.execute(
                        'SELECT kind, service, endpoint FROM task_capabilities WHERE capability=?',
                        (capability,),
                    ).fetchall()
                    return {
                        r['kind']: {'service': r['service'], 'endpoint': r['endpoint']}
                        for r in rows
                    }
                rows = conn.execute(
                    'SELECT kind, capability, service, endpoint FROM task_capabilities'
                ).fetchall()
        out = {}
        for r in rows:
            out.setdefault(r['kind'], {})[r['capability']] = {
                'service': r['service'], 'endpoint': r['endpoint'],
            }
        return out
    except Exception:
        return {}


def clear_service_capabilities(service):
    """清除某服务登记的全部能力（服务启动时调用）。

    目的：避免**僵尸能力**——插件被卸载/改名后，旧的声明还留在表里，
    框架会以为「支持继续」，转发到一个已不存在的端点。
    服务每次启动先清空自己名下的声明，再由当前加载的模块重新登记。
    """
    if not service:
        return 0
    with _lock:
        with _conn() as conn:
            cur = conn.execute(
                'DELETE FROM task_capabilities WHERE service=?', (service,))
            n = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    return n


def _register_local_handler(table, kind, fn, capability):
    if not kind or not callable(fn):
        return False
    table[kind] = fn
    register_capability(kind, capability, _handler_service(), endpoint=None)
    return True


def register_resume_handler(kind, fn):
    """在本进程内登记「继续」实现（无需跨进程转发）。

    fn(task_dict) -> (ok, message) 或 (ok, message, extra)
    与 register_capability 的区别：handler 只在**当前进程**有效，
    跨进程（插件）必须靠 endpoint；两者可并存，优先用同进程 handler。
    """
    return _register_local_handler(_RESUME_HANDLERS, kind, fn, CAPABILITY_RESUME)


def register_retry_handler(kind, fn):
    """在本进程内登记「重试」实现，签名同 register_resume_handler。"""
    return _register_local_handler(_RETRY_HANDLERS, kind, fn, CAPABILITY_RETRY)


def get_resume_handler(kind):
    return _RESUME_HANDLERS.get(kind)


def get_retry_handler(kind):
    return _RETRY_HANDLERS.get(kind)


def _handler_service():
    """当前进程在能力表里使用的服务名（供同进程 handler 登记用）。"""
    return _LOCAL_SERVICE or 'web'


def set_local_service(service):
    """设置本进程的服务名（各服务启动时调用一次）。"""
    global _LOCAL_SERVICE
    _LOCAL_SERVICE = service


_LOCAL_SERVICE = None


def resumable_kinds():
    """当前**支持继续**的任务类型集合（含同进程 handler 与跨进程 endpoint）。"""
    kinds = set(list_capabilities(CAPABILITY_RESUME).keys())
    kinds.update(_RESUME_HANDLERS.keys())
    return kinds


def retryable_kinds():
    """当前**支持重试**的任务类型集合。"""
    kinds = set(list_capabilities(CAPABILITY_RETRY).keys())
    kinds.update(_RETRY_HANDLERS.keys())
    return kinds



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


def count_tasks(role='user', user_id=None, status=None, kind=None):
    """按条件统计任务数（供分页使用，条件与 get_tasks 保持一致）。"""
    where, args = _build_filters(role, user_id, status, kind)
    with _conn() as conn:
        cnt = conn.execute(
            f'SELECT COUNT(*) FROM tasks{where}', args
        ).fetchone()[0]
    return int(cnt)


def _build_filters(role, user_id, status=None, kind=None):
    """拼装可见性 + 筛选条件。

    筛选值支持逗号分隔的多选（如 status='failed,cancelled'）；
    status 传 'active' 等价于「进行中的三类状态」。
    """
    clauses = []
    args = []
    if role != 'admin':
        if user_id is None:
            # 非管理员且无身份：看不到任何任务
            return ' WHERE 1=0', []
        clauses.append('owner_id=?')
        args.append(user_id)

    if status:
        wanted = [s for s in str(status).split(',') if s]
        if wanted:
            expanded = []
            for s in wanted:
                if s == 'active':
                    expanded.extend([STATUS_PENDING, STATUS_RUNNING, STATUS_AWAITING])
                elif s in _VALID_STATUS:
                    expanded.append(s)
            if expanded:
                clauses.append('status IN ({})'.format(','.join('?' * len(expanded))))
                args.extend(expanded)
    if kind:
        kinds = [k for k in str(kind).split(',') if k]
        if kinds:
            clauses.append('kind IN ({})'.format(','.join('?' * len(kinds))))
            args.extend(kinds)
    return (' WHERE ' + ' AND '.join(clauses)) if clauses else '', args


def get_tasks(role='user', user_id=None, limit=50, offset=0, status=None, kind=None):
    """返回当前用户可见的任务列表（按更新时间倒序）。

    - 普通用户：仅看到自己发起的任务（owner_id == user_id）。
    - 管理员：看到全部任务。
    - 支持按 status / kind 筛选（逗号分隔多选，status='active' 表示进行中），
      以及 offset/limit 分页；与 count_tasks 使用同一套条件，避免页数与数据不一致。
    """
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    where, args = _build_filters(role, user_id, status, kind)
    with _conn() as conn:
        rows = conn.execute(
            f'SELECT * FROM tasks{where} ORDER BY updated_at DESC LIMIT ? OFFSET ?',
            tuple(args) + (limit, offset),
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
