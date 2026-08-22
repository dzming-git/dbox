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
import sqlite3

from flask import Blueprint, jsonify, request, g
from backend.access import auth_required, admin_required, resolve_identity
from core.models import UserRole
from unified_tasks import (
    init_task_manager, get_tasks, get_task, count_action_required,
    delete_task, create_task, STATUS_RUNNING,
)

bp = Blueprint('task', __name__)

# 资源下载器服务地址（脚本任务真正执行的进程）。主服务作为网关将 /api/scripts
# 转发过去；重试脚本任务时本蓝图直接向内网地址发起 run 请求。
_DOWNLOADER_BASE_URL = 'http://127.0.0.1:8092'

# 任务详情接口单次返回的最大日志条数（避免长任务把接口拉爆）
_TASK_LOG_LIMIT = 500


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
    """返回当前用户可见的任务列表与待处理红点计数。"""
    user_id, role = resolve_identity()
    is_admin = _is_admin(role)

    # 初始化（幂等），保证只读场景下表也存在
    try:
        from backend.paths import DATA_DIR
        init_task_manager(DATA_DIR)
    except Exception:
        pass

    tasks = get_tasks(role='admin' if is_admin else 'user', user_id=user_id, limit=100)
    action_count = count_action_required(
        role='admin' if is_admin else 'user', user_id=user_id
    )
    return jsonify({
        'success': True,
        'tasks': tasks,
        'action_required_count': action_count,
    })


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


@bp.route('/api/tasks/<path:task_id>/retry', methods=['POST'])
@auth_required
def retry_task(task_id):
    """重试一个最终失败的任务。

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
