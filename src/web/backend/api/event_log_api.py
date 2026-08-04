"""事件监听器日志 API（管理后台查看反馈事件处理日志）。

读取 scripts/event_listener/.listener.log（监听器进程持久化的日志），
并附带监听器运行状态（来自 .listener_state.json 中的 pid）。
该日志文件由用户在本地手动启动监听器时产生，属于本地运行数据，不纳入 git。
"""
import os
import json
import psutil

from flask import Blueprint, request, jsonify

from backend.access import admin_required
from liblog import get_service_logger

log = get_service_logger('dbox-web')

bp = Blueprint('event_log_api', __name__)

# 监听器目录与日志/状态文件路径（相对项目根）
_SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'scripts')
_LISTENER_DIR = os.path.join(_SCRIPTS_DIR, 'event_listener')
LOG_PATH = os.path.join(_LISTENER_DIR, '.listener.log')
STATE_PATH = os.path.join(_LISTENER_DIR, '.listener_state.json')


def _listener_running():
    """根据 .listener_state.json 中的 pid 判断监听器是否在运行。

    除 pid 存活外，额外校验该进程命令行确实包含 listener.py，
    避免 pid 复用导致误判为运行中。
    """
    if not os.path.exists(STATE_PATH):
        return False
    try:
        with open(STATE_PATH, 'r', encoding='utf-8') as f:
            state = json.load(f)
        pid = state.get('pid')
        if not pid:
            return False
        if not psutil.pid_exists(pid):
            return False
        try:
            proc = psutil.Process(pid)
            cmd = ' '.join(proc.cmdline())
            return 'event_listener/listener.py' in cmd or 'listener.py' in cmd
        except Exception:
            # 无法读取命令行时退回到仅 pid 判断
            return True
    except Exception:
        return False


def _read_log_lines(tail=None, page=1, limit=200):
    """读取日志文件。tail>0 取末尾 N 行；否则按 page/limit 分页（倒序展示较新在前）。"""
    if not os.path.exists(LOG_PATH):
        return [], 0
    try:
        with open(LOG_PATH, 'r', encoding='utf-8') as f:
            lines = [ln.rstrip('\n') for ln in f if ln.strip() != '']
    except Exception:
        return [], 0
    total = len(lines)
    if tail and tail > 0:
        return lines[-tail:], total
    limit = max(1, min(limit, 1000))
    page = max(1, page)
    start = max(0, total - page * limit)
    end = max(0, total - (page - 1) * limit)
    # 返回较新在前
    window = lines[start:end]
    window.reverse()
    return window, total


@bp.route('/api/admin/event-log', methods=['GET'])
@admin_required
def get_event_log():
    """
    获取事件监听器日志。

    参数:
    - tail:   取末尾 N 行（优先于分页），如 tail=200
    - page:   页码（默认 1）
    - limit:  每页条数（默认 200，最大 1000）
    """
    tail = request.args.get('tail', type=int)
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 200, type=int)

    lines, total = _read_log_lines(tail=tail, page=page, limit=limit)
    return jsonify({
        'success': True,
        'lines': lines,
        'total': total,
        'page': page,
        'limit': limit,
        'running': _listener_running(),
        'log_path': LOG_PATH,
    })
