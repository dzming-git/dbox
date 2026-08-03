#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一任务管理 API（运行在主服务 /api/tasks）。

前端「任务管理器」通过本蓝图读取所有后台任务的进度、状态与待处理红点计数。
- 脚本任务由下载器服务的 script_engine 镜像进统一任务表；
- 上传任务由 video_api 上传接口登记与更新。

脚本类任务的交互式处理仍走既有的 /api/scripts/jobs/<id>/interactive 与 /respond
（经网关转发到下载器），本蓝图只负责读取与红点计数。
"""
from flask import Blueprint, jsonify, request, g
from backend.access import auth_required, admin_required, resolve_identity
from core.models import UserRole
from unified_tasks import (
    init_task_manager, get_tasks, get_task, count_action_required,
    delete_task,
)

bp = Blueprint('task', __name__)


def _is_admin(role):
    """role 可能来自 resolve_identity（整数 UserRole）或字符串，统一判定管理员。"""
    if isinstance(role, str):
        return role in ('admin', 'root')
    try:
        return int(role) >= UserRole.ADMIN
    except (TypeError, ValueError):
        return False


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
    """任务详情。普通用户只能查看自己发起的任务。"""
    user_id, role = resolve_identity()
    is_admin = _is_admin(role)

    task = get_task(task_id)
    if not task:
        return jsonify({'success': False, 'message': '任务不存在'}), 404
    if not is_admin and task.get('owner_id') not in (None, user_id):
        return jsonify({'success': False, 'message': '无权查看该任务'}), 403
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
