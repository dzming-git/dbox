#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一任务管理 API（运行在主服务 /api/tasks）。

前端「任务管理器」通过本蓝图读取所有后台任务的进度、状态与待处理红点计数。
- 脚本任务由下载器服务的 script_engine 镜像进统一任务表；
- 上传任务由 video_api 上传接口登记与更新。

脚本类任务的交互式处理仍走既有的 /api/scripts/jobs/<id>/interactive 与 /respond
（经网关转发到下载器），本蓝图只负责读取与红点计数。
"""
import os
import json
import sqlite3
import time

from flask import Blueprint, jsonify, request, g, Response, stream_with_context
from backend.access import auth_required, admin_required, resolve_identity
from backend.db_guard import release_db
from core.models import UserRole
from unified_tasks import (
    init_task_manager, get_tasks, get_task, count_tasks, count_action_required,
    delete_task, create_task, request_cancel, bump_attempts,
    STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED,
    CAPABILITY_RESUME, get_capability, get_resume_handler,
    list_capabilities, resumable_kinds,
)

bp = Blueprint('task', __name__)

# 资源下载器服务地址（脚本任务真正执行的进程）。主服务作为网关将 /api/scripts
# 转发过去；重试脚本任务时本蓝图直接向内网地址发起 run 请求。
_DOWNLOADER_BASE_URL = 'http://127.0.0.1:8092'

# 各服务的内网地址：框架按能力注册表里登记的 service 把「继续」请求转发过去。
# 这里只描述**基础设施拓扑**（哪个服务在哪个端口），不涉及任何具体任务类型。
_SERVICE_BASE_URLS = {
    'web': '',                              # 本进程：走同进程 handler
    'extensions': 'http://127.0.0.1:8093',  # 扩展管理宿主
    'downloader': _DOWNLOADER_BASE_URL,
}

# 任务详情接口单次返回的最大日志条数（避免长任务把接口拉爆）
_TASK_LOG_LIMIT = 500

# SSE 单条连接的最长存活时间：到点主动结束，由浏览器按 retry 重连。
# 目的是避免长连接无限期存在（前端异常未关闭时会越积越多）。
STREAM_MAX_SECONDS = 1800


def _is_admin(role):
    """role 可能来自 resolve_identity（整数 UserRole）或字符串，统一判定管理员。"""
    if isinstance(role, str):
        return role in ('admin', 'root')
    try:
        return int(role) <= UserRole.ADMIN
    except (TypeError, ValueError):
        return False


def _script_jobs_db_path():
    """定位 script_jobs.db 的绝对路径。

    script_engine 把它建在 <DATA_DIR>/script_jobs.db，由下载器服务持有写入权。
    主服务以只读方式直连，避免跨服务 HTTP 鉴权开销。
    """
    try:
        from backend.paths import DATA_DIR
        return os.path.join(DATA_DIR, 'script_jobs.db')
    except Exception:
        return None


def _fetch_script_logs(job_id, limit=_TASK_LOG_LIMIT):
    """从 script_jobs.db 读取指定 job_id 的日志（按 id 倒序）。

    返回 None 表示数据库不可用（下载器未运行或未建库），调用方决定是否降级为空列表。
    """
    db_path = _script_jobs_db_path()
    if not db_path or not os.path.exists(db_path):
        return None
    try:
        # uri=True + mode=ro：只读连接，避免与下载器进程的写入锁冲突
        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=5)
        try:
            cur = conn.execute(
                'SELECT level, message, ts FROM job_logs '
                'WHERE job_id=? ORDER BY id DESC LIMIT ?',
                (job_id, limit),
            )
            # 翻转成「正序」，前端从最早展示到最后
            rows = list(cur.fetchall())[::-1]
        finally:
            conn.close()
        return [
            {'level': r[0], 'message': r[1], 'ts': r[2]}
            for r in rows
        ]
    except Exception:
        # 直连失败（文件被独占、损坏等），不要让详情接口 500，降级为空
        return []


def _enrich_task_with_logs(task):
    """为 script: 前缀的任务追加 logs 字段，供前端「点开查看实时日志」使用。"""
    if not task:
        return task
    task_id = task.get('task_id') or ''
    if not task_id.startswith('script:'):
        return task
    job_id = task_id[len('script:'):]
    if not job_id:
        return task
    logs = _fetch_script_logs(job_id)
    if logs is not None:
        task['logs'] = logs
        task['script_job_id'] = job_id
    return task


@bp.route('/api/tasks', methods=['GET'])
@auth_required
def list_tasks():
    """返回当前用户可见的任务列表与待处理红点计数。

    查询参数：
      status —— 状态筛选，逗号分隔多选；`active` 表示进行中（排队/运行/等待处理）
      kind   —— 类型筛选，逗号分隔多选（scan / thumbnail / upload / gallery …）
      limit  —— 每页条数（1~200，默认 50）
      offset —— 偏移量（默认 0）

    返回额外带上 total / has_more，供前端分页；total 与列表使用同一套筛选条件，
    避免出现「显示有下一页但点开是空的」。
    """
    user_id, role = resolve_identity()
    is_admin = _is_admin(role)
    role_arg = 'admin' if is_admin else 'user'

    # 初始化（幂等），保证只读场景下表也存在
    try:
        from backend.paths import DATA_DIR
        init_task_manager(DATA_DIR)
    except Exception:
        pass

    status = request.args.get('status') or None
    kind = request.args.get('kind') or None
    try:
        limit = int(request.args.get('limit', 50))
    except (TypeError, ValueError):
        limit = 50
    try:
        offset = int(request.args.get('offset', 0))
    except (TypeError, ValueError):
        offset = 0

    tasks = get_tasks(role=role_arg, user_id=user_id, limit=limit, offset=offset,
                      status=status, kind=kind)
    total = count_tasks(role=role_arg, user_id=user_id, status=status, kind=kind)
    action_count = count_action_required(role=role_arg, user_id=user_id)
    return jsonify({
        'success': True,
        'tasks': tasks,
        'total': total,
        'has_more': offset + len(tasks) < total,
        'action_required_count': action_count,
    })


@bp.route('/api/tasks/stream', methods=['GET'])
@auth_required
def task_stream():
    """任务状态变化的实时推送（SSE）。

    浏览器原生 EventSource 不能自定义请求头，因此鉴权走 `?token=` 查询参数
    （与 resolve_identity 的 URL token 回退一致），前端把登录态里的 JWT 带上即可。

    推送策略：**只推变化**。服务端每 2 秒比对一次快照，任务的状态/进度/阶段/详情
    任一变化才发一条 `task` 事件；无变化时发注释行保活，避免长连接被中间层掐断。
    """
    user_id, role = resolve_identity()
    is_admin = _is_admin(role)
    role_arg = 'admin' if is_admin else 'user'

    try:
        from backend.paths import DATA_DIR
        init_task_manager(DATA_DIR)
    except Exception:
        pass

    def _signature(t):
        return (t.get('status'), t.get('progress'), t.get('stage'), t.get('detail'))

    def _gen():
        last = {}
        yield 'retry: 5000\n\n'
        # 给连接一个上限：到点主动结束，让浏览器重连。
        # 长连接若无限期存在，一旦前端没关干净就会越积越多。
        deadline = time.time() + STREAM_MAX_SECONDS
        while time.time() < deadline:
            events = []
            try:
                current = get_tasks(role=role_arg, user_id=user_id, limit=200)
                seen = set()
                for t in current:
                    tid = t.get('task_id')
                    if not tid:
                        continue
                    seen.add(tid)
                    sig = _signature(t)
                    if last.get(tid) != sig:
                        events.append(t)
                    last[tid] = sig
                # 已被删除的任务从快照里移除，避免重新出现时重复推送
                for tid in [k for k in last if k not in seen]:
                    last.pop(tid, None)
            except Exception:
                # 单次比对失败不打断连接，下一轮继续
                events = []

            if events:
                for t in events:
                    yield 'event: task\ndata: ' + json.dumps(
                        t, ensure_ascii=False, default=str) + '\n\n'
            else:
                yield ': ping\n\n'

            time.sleep(2)

    # ⚠️ 长连接绝不能持有数据库连接（详见 backend/db_guard.py）：
    # resolve_identity() 里的 User.query 会借出连接，而流式响应不结束就不会归还，
    # 连接池被占满后全站请求都会排队超时。这里在进入流之前主动归还；
    # _gen() 内部只用统一任务表的独立 sqlite 连接，不再触碰 SQLAlchemy。
    release_db()

    return Response(
        stream_with_context(_gen()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache, no-transform',
            'Connection': 'keep-alive',
            # 关闭反向代理的响应缓冲，否则事件会被攒着一起发
            'X-Accel-Buffering': 'no',
        },
    )


@bp.route('/api/tasks/action-count', methods=['GET'])
@auth_required
def action_count():
    """轻量级红点计数接口（供导航栏轮询）。"""
    user_id, role = resolve_identity()
    is_admin = _is_admin(role)
    try:
        from backend.paths import DATA_DIR
        init_task_manager(DATA_DIR)
    except Exception:
        pass
    cnt = count_action_required(role='admin' if is_admin else 'user', user_id=user_id)
    return jsonify({'success': True, 'count': cnt})


@bp.route('/api/tasks/<path:task_id>', methods=['GET'])
@auth_required
def task_detail(task_id):
    """任务详情。普通用户只能查看自己发起的任务。

    script: 前缀的任务会额外附带 logs（来自 script_jobs.db.job_logs）。
    """
    user_id, role = resolve_identity()
    is_admin = _is_admin(role)

    try:
        from backend.paths import DATA_DIR
        init_task_manager(DATA_DIR)
    except Exception:
        pass

    task = get_task(task_id)
    if not task:
        return jsonify({'success': False, 'message': '任务不存在'}), 404
    if not is_admin and task.get('owner_id') not in (None, user_id):
        return jsonify({'success': False, 'message': '无权查看该任务'}), 403
    _enrich_task_with_logs(task)
    return jsonify({'success': True, 'task': task})


@bp.route('/api/tasks/<path:task_id>', methods=['DELETE'])
@auth_required
def delete_task_route(task_id):
    """删除一条已结束的任务。进行中的任务不允许删除。

    - 普通用户：仅可删除自己发起的任务；
    - 管理员：可删除任意已结束任务。
    """
    user_id, role = resolve_identity()
    is_admin = _is_admin(role)

    try:
        from backend.paths import DATA_DIR
        init_task_manager(DATA_DIR)
    except Exception:
        pass

    result = delete_task(task_id, is_admin=is_admin, owner_id=user_id)
    if result is True:
        return jsonify({'success': True})
    if result is False:
        # 区分「任务不存在」与「无权删除」，便于前端提示
        task = get_task(task_id)
        if not task:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        return jsonify({'success': False, 'message': '无权删除该任务'}), 403
    # result is None：任务仍处于进行中
    return jsonify({
        'success': False,
        'message': '任务进行中，无法删除；等待完成后再操作',
    }), 409


@bp.route('/api/tasks/<path:task_id>/cancel', methods=['POST'])
@auth_required
def cancel_task(task_id):
    """请求取消一个进行中的任务。

    取消是「协作式」的：这里只置 cancel_requested 标记，执行方在下一个检查点
    检测到后自行停止并写入 cancelled 终态。因此接口返回后状态可能仍是 running，
    前端应继续轮询而不是立刻认为已停止。
    """
    user_id, role = resolve_identity()
    is_admin = _is_admin(role)

    try:
        from backend.paths import DATA_DIR
        init_task_manager(DATA_DIR)
    except Exception:
        pass

    task = get_task(task_id)
    if not task:
        return jsonify({'success': False, 'message': '任务不存在'}), 404
    if not is_admin and task.get('owner_id') not in (None, user_id):
        return jsonify({'success': False, 'message': '无权取消该任务'}), 403
    if task.get('status') in (STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED):
        return jsonify({'success': False, 'message': '任务已结束，无需取消'}), 400

    updated = request_cancel(task_id)
    return jsonify({
        'success': True,
        'task': updated,
        'message': '已请求取消，任务会在下一个检查点停止',
    })


@bp.route('/api/tasks/<path:task_id>/resume', methods=['POST'])
@auth_required
def resume_task(task_id):
    """从中断处继续一个任务（框架统一入口）。

    框架**不认识任何具体任务类型**：谁能继续、怎么继续，由任务实现方在注册表中
    声明（同进程内登记 handler，或跨进程登记 endpoint）。本函数只做三件事：
      1. 查注册表确认这个 kind 有没有注册「继续」；
      2. 有 → 转交实现方（同进程直接调，跨进程转发）；
      3. 没有 → 明确返回「该类型任务不支持继续」，而不是猜一个接口去调。

    这样新增一种可续跑的任务，只需实现方自己注册，框架零改动。
    """
    user_id = getattr(g, 'user_id', None)
    is_admin = _is_admin(getattr(g, 'role', None))

    task = get_task(task_id)
    if not task:
        return jsonify({'success': False, 'message': '任务不存在'}), 404

    if not is_admin and task.get('owner_id') not in (None, user_id):
        return jsonify({'success': False, 'message': '无权继续该任务'}), 403

    kind = task.get('kind')

    # 同进程内登记的继续实现优先：省一次跨进程转发
    handler = get_resume_handler(kind)
    if handler:
        try:
            ok, message = handler(task)
        except Exception as e:
            return jsonify({'success': False, 'message': f'继续失败: {e}'}), 500
        if not ok:
            return jsonify({'success': False, 'message': message}), 400
        bump_attempts(task_id)
        return jsonify({'success': True, 'message': message, 'task_id': task_id})

    # 否则查注册表：由登记该能力的服务执行
    cap = get_capability(kind, CAPABILITY_RESUME)
    if not cap:
        # 框架感知到「没人注册继续函数」——这是正常情况，不是错误：
        # 多数任务本就无法断点续跑，界面据此不展示「继续」入口。
        return jsonify({
            'success': False,
            'message': f'该类型任务（{kind}）未注册继续实现，不支持从中断处继续',
            'not_supported': True,
        }), 400

    service = cap.get('service')
    endpoint = cap.get('endpoint')
    base = _SERVICE_BASE_URLS.get(service)
    if not endpoint or not base:
        return jsonify({
            'success': False,
            'message': f'该类型任务的继续实现注册不完整（service={service}）',
            'not_supported': True,
        }), 500

    # 转发给实现方：带上用户鉴权，避免越权续跑别人的任务
    try:
        import requests as _rq
        headers = {'Content-Type': 'application/json'}
        auth = request.headers.get('Authorization')
        if auth:
            headers['Authorization'] = auth
        device = request.headers.get('X-Dbox-Device-Id')
        if device:
            headers['X-Dbox-Device-Id'] = device
        r = _rq.post(f'{base}{endpoint}', json={'task_id': task_id},
                     headers=headers, timeout=30)
    except Exception as e:
        return jsonify({'success': False, 'message': f'转发继续请求失败: {e}'}), 502

    try:
        payload = r.json()
    except Exception:
        payload = {'success': False, 'message': (r.text or '')[:200]}
    bump_attempts(task_id)
    return jsonify(payload if isinstance(payload, dict) else {'success': True}), r.status_code


@bp.route('/api/tasks/capabilities', methods=['GET'])
@auth_required
def task_capabilities():
    """列出各任务类型已注册的能力（前端据此决定展示哪些操作）。

    界面不该硬编码「哪种任务能继续」——那份知识属于实现方，这里统一查表返回。
    """
    return jsonify({
        'success': True,
        'capabilities': list_capabilities(),
        'resumable': sorted(resumable_kinds()),
    })


@bp.route('/api/tasks/<path:task_id>/retry', methods=['POST'])
@auth_required
def retry_task(task_id):
    """重试一个最终失败的任务。

    - 扫描任务（scan:*）：按登记的参数（scope / library_id / mode）重新发起一次扫描；
    - 脚本任务（script:*）：读取登记时的可重放参数（script_id + 原始 params），
      向内网下载器服务重新提交 run 请求，由下载器创建新 job 并同步回统一任务表，
      用户可在任务列表看到新任务。
    - 上传 / 缩略图任务：这类失败（如文件已存在、指纹计算失败）通常无法脱离
      原始请求体无感重放，返回明确提示，由前端引导用户重新发起。
    """
    user_id = getattr(g, 'user_id', None)
    is_admin = _is_admin(getattr(g, 'role', None))

    task = get_task(task_id)
    if not task:
        return jsonify({'success': False, 'message': '任务不存在'}), 404

    # 权限：只能重试自己的任务；管理员可重试全部
    if not is_admin and task.get('owner_id') not in (None, user_id):
        return jsonify({'success': False, 'message': '无权重试该任务'}), 403

    kind = task.get('kind')
    status = task.get('status')
    if status not in ('failed', 'cancelled'):
        return jsonify({'success': False, 'message': '仅失败/已取消的任务可重试'}), 400

    if kind == 'scan':
        # 扫描任务自带完整可重放参数（scope / library_id / mode），直接重放即可
        try:
            from backend.library_helpers import restart_scan_from_params
        except Exception as e:
            return jsonify({'success': False, 'message': f'扫描模块不可用：{e}'}), 500
        ok, message = restart_scan_from_params(task.get('params'), owner_id=task.get('owner_id'))
        if not ok:
            return jsonify({'success': False, 'message': message}), 400
        bump_attempts(task_id)
        return jsonify({'success': True, 'message': message, 'task_id': task_id})

    if kind == 'thumbnail':
        # 批量生成缺失缩略图：参数可重放（重新扫一遍缺失项即可），直接再跑一次
        try:
            from backend.thumbnail_helpers import start_thumbnail_batch
        except Exception as e:
            return jsonify({'success': False, 'message': f'缩略图模块不可用：{e}'}), 500
        ok, message = start_thumbnail_batch(owner_id=task.get('owner_id'))
        if not ok:
            return jsonify({'success': False, 'message': message}), 400
        bump_attempts(task_id)
        return jsonify({'success': True, 'message': message, 'task_id': task_id})

    if kind == 'meta':
        # 补齐缺失的时长/大小：无额外参数，直接再跑一次（已补齐的会被跳过）
        try:
            from backend.library_helpers import start_metadata_backfill
        except Exception as e:
            return jsonify({'success': False, 'message': f'补齐模块不可用：{e}'}), 500
        ok, message = start_metadata_backfill(owner_id=task.get('owner_id'))
        if not ok:
            return jsonify({'success': False, 'message': message}), 400
        bump_attempts(task_id)
        return jsonify({'success': True, 'message': message, 'task_id': task_id})

    if kind == 'script':
        params = task.get('params') or {}
        script_id = params.get('script_id')
        run_params = params.get('params') or {}
        if not script_id:
            return jsonify({'success': False, 'message': '该任务缺少脚本标识，无法重试'}), 400
        try:
            import requests
            fwd = {'host', 'content-length', 'connection', 'transfer-encoding'}
            fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in fwd}
            try:
                resp = requests.post(
                    f'{_DOWNLOADER_BASE_URL}/api/scripts/{script_id}/run',
                    json=run_params,
                    headers=fwd_headers,
                    cookies=request.cookies,
                    timeout=30,
                )
                data = resp.json() if resp.content else {}
            except Exception as e:
                return jsonify({
                    'success': False,
                    'message': f'资源下载器服务不可用，请检查下载器进程是否运行：{e}',
                    'code': 503,
                }), 503
            if data.get('success'):
                return jsonify({
                    'success': True,
                    'message': '已重新提交，请在任务列表查看新任务',
                    'job_id': data.get('job_id'),
                })
            return jsonify({
                'success': False,
                'message': data.get('error') or data.get('message') or '重新提交失败',
            }), (resp.status_code if 'status_code' in dir(resp) else 400)
        except Exception as e:
            return jsonify({'success': False, 'message': f'重试失败：{e}'}), 500

    if kind == 'upload':
        return jsonify({
            'success': False,
            'message': '上传任务需重新选择文件发起，无法自动重试',
            'need_reupload': True,
        }), 400

    # thumbnail 等其他类型：无可靠重放参数
    return jsonify({
        'success': False,
        'message': '该类型任务无法自动重试，请重新发起',
    }), 400
