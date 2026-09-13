# -*- coding: utf-8 -*-
"""统一任务管理器（主服务兼容入口）。

实现已收敛到 ``shared.unified_tasks`` 单一真源：主服务、扩展宿主、下载器
共用同一份代码与同一张 tasks.db，避免两份副本各自漂移。

本模块只做转发，新增能力请直接改 ``src/shared/unified_tasks.py``。
"""
from shared.unified_tasks import *  # noqa: F401,F403
from shared.unified_tasks import (  # noqa: F401  显式声明，便于静态检查与 IDE 跳转
    STATUS_PENDING, STATUS_RUNNING, STATUS_AWAITING,
    STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED,
    init_task_manager, create_task, update_task,
    get_task, get_tasks, delete_task,
    set_action_required, clear_action_required, count_action_required,
    request_cancel, is_cancel_requested, bump_attempts,
    mark_started, finish_task, list_active_tasks, prune_old,
)
