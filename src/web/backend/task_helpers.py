# -*- coding: utf-8 -*-
"""统一任务接入辅助（web 进程内共用）。

各后台任务（资源库扫描、批量缩略图生成、上传……）登记进统一任务表时都要做
同一套动作：初始化任务库、节流地检查取消请求、安全地更新/收尾。集中放这里，
避免在若干 helpers 里各抄一份而行为漂移。

注意：取消是**协作式**的——这里只提供「是否收到取消请求」的查询，真正停下
由调用方在自己的循环里决定。
"""
import time

from liblog import get_service_logger

log = get_service_logger('dbox-web')


def init_task_store():
    """初始化统一任务表（幂等）。失败不影响业务本身，只损失任务可见性。"""
    try:
        from backend.paths import DATA_DIR
        from unified_tasks import init_task_manager
        init_task_manager(DATA_DIR)
        return True
    except Exception as e:
        log.debug('WARN', f'统一任务表初始化失败，本次任务不登记: {e}')
        return False


def update_task_quiet(task_id, **kwargs):
    """更新任务但不允许异常打断业务流程。"""
    try:
        from unified_tasks import update_task
        update_task(task_id, **kwargs)
    except Exception:
        pass


def finish_task_quiet(task_id, status, **kwargs):
    """结束任务但不让异常影响业务结果。

    收尾失败只影响任务可见性（任务会一直显示为进行中），不能因此判定业务失败，
    但必须记 ERROR 级——这类失败是静默的，不记下来没人会发现。
    """
    try:
        from unified_tasks import finish_task
        finish_task(task_id, status, **kwargs)
    except Exception as e:
        log.debug('ERROR', f'更新任务状态失败({task_id}): {type(e).__name__}: {e}')


def cancel_watcher(task_id, min_interval=1.0):
    """构造「是否收到取消请求」回调。

    任务循环里可能每处理一项就问一次，直接查库会放大 IO，因此按 min_interval
    节流（默认最多每秒查一次），命中后结果缓存不再回源；第一次调用立即查库，
    保证「刚点取消」能被马上感知。
    """
    state = {'at': 0.0, 'stop': False}

    def _should_stop():
        if state['stop']:
            return True
        now = time.time()
        if now - state['at'] < min_interval:
            return False
        state['at'] = now
        try:
            from unified_tasks import is_cancel_requested
            state['stop'] = is_cancel_requested(task_id)
        except Exception:
            state['stop'] = False
        return state['stop']

    return _should_stop


def register_task(task_id, kind, title, owner_id=None, library_id=None, params=None):
    """登记（或重置）一条统一任务并标记为已开始。"""
    if not init_task_store():
        return False
    try:
        from unified_tasks import create_task, mark_started, STATUS_RUNNING
        create_task(
            task_id, kind, title, owner_id=owner_id, library_id=library_id,
            status=STATUS_RUNNING, progress=0, stage='准备中',
            detail='任务已排队，正在准备', params=params,
        )
        mark_started(task_id)
        return True
    except Exception as e:
        log.debug('ERROR', f'登记任务失败({task_id}): {e}')
        return False


def ensure_task(task_id, kind, title, owner_id=None, library_id=None, params=None):
    """确保任务存在且处于进行中；已在进行中则**不重置**。

    与 register_task 的区别：批量任务往往分两段（先登记、再在真正开始执行时补充
    参数）。若此时无条件重新登记，会连带把 `cancel_requested` 清零——用户在第一段
    期间点的取消会被悄悄抹掉，任务再也停不下来。所以只在这条任务不存在或已结束时
    才重新登记，进行中则只更新描述。
    """
    try:
        from unified_tasks import get_task
        cur = get_task(task_id)
    except Exception:
        cur = None
    if cur and cur.get('status') in ('pending', 'running', 'awaiting_input'):
        update_task_quiet(task_id, params=params)
        return False
    return register_task(task_id, kind, title, owner_id=owner_id,
                         library_id=library_id, params=params)
