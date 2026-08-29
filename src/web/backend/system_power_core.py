"""系统电源控制核心逻辑（运行于主 Web 服务 dbox-web 进程，端口 8080）。

原 extensions/system-power 插件已并入核心：系统电源管控是平台系统功能，
不应寄宿在被它管理的 dbox-extensions 进程。关机动作直接调用操作系统命令，
不依赖任何业务模块。鉴权由 local 蓝图层的 admin_required 统一处理。

提供：立即关机 / 按分钟定时关机（可取消）/ 任务结束后关机。
"""
import os
import sys
import time
import threading
import subprocess
import logging

logger = logging.getLogger('system_power')

_POWER_STATE = {
    'shutdown_after_tasks': False,
    'timer': None,
    'scheduled_at': None,
    'lock': threading.Lock(),
}


def _shutdown_command():
    if sys.platform.startswith('win'):
        return ['shutdown.exe', '/s', '/f', '/t', '0']
    return ['shutdown', '-h', 'now']


def _cancel_scheduled():
    with _POWER_STATE['lock']:
        if _POWER_STATE['timer'] is not None:
            _POWER_STATE['timer'].cancel()
            _POWER_STATE['timer'] = None
        _POWER_STATE['scheduled_at'] = None
    if sys.platform.startswith('win'):
        try:
            subprocess.run(['shutdown.exe', '/a'], capture_output=True, check=False)
        except Exception as e:
            logger.warning('取消 Windows 定时关机失败: %s', e)


def _do_shutdown(operator='unknown'):
    logger.info('执行关机，平台=%s，操作者=%s', sys.platform, operator)
    try:
        subprocess.Popen(_shutdown_command(),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, close_fds=True)
        return True
    except Exception as e:
        logger.error('关机命令启动失败: %s', e)
        return False


def _count_active_tasks():
    """统计当前活跃业务任务数，用于「任务结束后关机」。

    优先复用核心统一任务表；取不到时返回 None（调用方据此保持等待，不误关机）。
    """
    try:
        from backend.tasks import task_store  # 核心统一任务存储
        active = task_store.list_active_tasks(limit=500) if hasattr(task_store, 'list_active_tasks') else None
        if active is None:
            return None
        return len([t for t in active
                    if str(t.get('kind', '')).split(':')[0] != 'ext'
                    and t.get('status') in ('pending', 'running')])
    except Exception as e:
        logger.warning('统计活跃任务失败: %s', e)
        return None


def _watch_tasks_then_shutdown():
    def _loop():
        while True:
            with _POWER_STATE['lock']:
                if not _POWER_STATE['shutdown_after_tasks']:
                    return
            n = _count_active_tasks()
            if n is not None and n <= 0:
                _do_shutdown()
                return
            time.sleep(15)
    threading.Thread(target=_loop, daemon=True).start()


def create_blueprint(admin_required):
    """构造 Flask 蓝图。admin_required 由调用方（local）传入。"""
    from flask import Blueprint, request, jsonify, g
    bp = Blueprint('system_power_local', __name__, url_prefix='/api/admin/system-power')

    @bp.route('/shutdown', methods=['POST'])
    @admin_required
    def shutdown():
        data = request.get_json(silent=True) or {}
        if data.get('immediate') is not True:
            return jsonify({'success': False, 'message': '需 immediate=true'}), 400
        ok = _do_shutdown(getattr(g, 'username', 'unknown'))
        return jsonify({'success': ok, 'message': '已发起关机' if ok else '关机失败'})

    @bp.route('/shutdown/scheduled', methods=['POST'])
    @admin_required
    def scheduled():
        data = request.get_json(silent=True) or {}
        minutes = data.get('minutes')
        if not isinstance(minutes, int) or minutes <= 0:
            return jsonify({'success': False, 'message': 'minutes 必须为正整数'}), 400
        _cancel_scheduled()
        secs = minutes * 60
        if sys.platform.startswith('win'):
            try:
                subprocess.Popen(['shutdown.exe', '/s', '/f', '/t', str(secs)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 stdin=subprocess.DEVNULL, close_fds=True)
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)}), 500
        else:
            t = threading.Timer(secs, _do_shutdown)
            t.daemon = True
            t.start()
            with _POWER_STATE['lock']:
                _POWER_STATE['timer'] = t
        with _POWER_STATE['lock']:
            _POWER_STATE['scheduled_at'] = time.time() + secs
        return jsonify({'success': True, 'message': f'{minutes} 分钟后关机已安排',
                        'scheduled_at': _POWER_STATE['scheduled_at']})

    @bp.route('/shutdown/cancel', methods=['POST'])
    @admin_required
    def cancel():
        _cancel_scheduled()
        with _POWER_STATE['lock']:
            _POWER_STATE['shutdown_after_tasks'] = False
        return jsonify({'success': True, 'message': '已取消定时/任务后关机'})

    @bp.route('/shutdown/after-tasks', methods=['POST'])
    @admin_required
    def after_tasks():
        data = request.get_json(silent=True) or {}
        enable = bool(data.get('enable', True))
        with _POWER_STATE['lock']:
            _POWER_STATE['shutdown_after_tasks'] = enable
        if enable:
            _watch_tasks_then_shutdown()
            return jsonify({'success': True, 'message': '已开启：所有任务完成后自动关机'})
        return jsonify({'success': True, 'message': '已关闭任务完成后关机'})

    @bp.route('/shutdown/status', methods=['GET'])
    @admin_required
    def status():
        with _POWER_STATE['lock']:
            return jsonify({
                'success': True,
                'shutdown_after_tasks': _POWER_STATE['shutdown_after_tasks'],
                'scheduled_at': _POWER_STATE['scheduled_at'],
                'has_timer': _POWER_STATE['timer'] is not None,
            })

    return bp
