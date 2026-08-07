"""事件监听器日志 API（管理后台查看反馈事件处理日志）。

读取 scripts/event_listener/.listener.log（监听器进程持久化的日志），
并附带监听器运行状态（来自 .listener_state.json 中的 pid）。
该日志文件由用户在本地手动启动监听器时产生，属于本地运行数据，不纳入 git。
"""
import os
import sys
import json
import psutil
import subprocess

from flask import Blueprint, request, jsonify

from backend.access import admin_required
from liblog import get_service_logger

log = get_service_logger('dbox-web')

bp = Blueprint('event_log_api', __name__)

# 监听器目录与日志/状态文件路径（相对项目根）
# 文件位于 <root>/src/web/backend/api/event_log_api.py，向上 5 层到项目根
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
_SCRIPTS_DIR = os.path.join(_ROOT_DIR, 'scripts')
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


import re

_EVENT_RE = re.compile(r'事件触发:\s*(\S+)|事件\s+(\S+)\s+的探针|(\S+)/\S+\s+重试')


def _extract_event(line):
    """从日志行中提取事件名（用于按事件筛选）。"""
    m = _EVENT_RE.search(line)
    if not m:
        return None
    return next((g for g in m.groups() if g), None)


def _read_log_lines(tail=None, page=1, limit=200, event=None):
    """读取日志文件。tail>0 取末尾 N 行；否则按 page/limit 分页（倒序展示较新在前）。

    若 event 非空，则只保留包含该事件名的日志行。
    """
    if not os.path.exists(LOG_PATH):
        return [], 0
    try:
        with open(LOG_PATH, 'r', encoding='utf-8') as f:
            lines = [ln.rstrip('\n') for ln in f if ln.strip() != '']
    except Exception:
        return [], 0
    if event:
        lines = [ln for ln in lines if _extract_event(ln) == event]
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


@bp.route('/api/event-listener/status', methods=['GET'])
def get_event_listener_status_public():
    """公开（无需登录）的监听器运行状态接口。

    监听器已作为独立常驻服务（dbox-listener）运行，状态直接取自
    service_manager，保证前端始终能正确显示，不依赖管理员登录态。
    """
    running = False
    try:
        proc = subprocess.run(
            ['python', os.path.join(_SCRIPTS_DIR, 'service_manager.py'), 'status', 'listener'],
            cwd=_ROOT_DIR, capture_output=True, text=True, timeout=30,
        )
        out = (proc.stdout or '') + (proc.stderr or '')
        if proc.returncode == 0 and 'RUNNING' in out:
            running = True
        else:
            running = _listener_running()
    except Exception:
        running = _listener_running()
    return jsonify({
        'success': True,
        'running': running,
    })


@bp.route('/api/admin/event-log/status', methods=['GET'])
@admin_required
def get_event_log_status():
    """轻量级状态接口：仅返回监听器是否运行中，供前端轮询展示。"""
    return jsonify({
        'success': True,
        'running': _listener_running(),
    })


@bp.route('/api/admin/event-log', methods=['GET'])
@admin_required
def get_event_log():
    """
    获取事件监听器日志。

    参数:
    - tail:   取末尾 N 行（优先于分页），如 tail=200
    - page:   页码（默认 1）
    - limit:  每页条数（默认 200，最大 1000）
    - event:  按事件名筛选（可选）
    """
    tail = request.args.get('tail', type=int)
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 200, type=int)
    event = request.args.get('event', type=str) or None

    lines, total = _read_log_lines(tail=tail, page=page, limit=limit, event=event)
    return jsonify({
        'success': True,
        'lines': lines,
        'total': total,
        'page': page,
        'limit': limit,
        'event': event,
        'running': _listener_running(),
        'log_path': LOG_PATH,
    })


@bp.route('/api/admin/event-handlers', methods=['GET'])
@admin_required
def get_event_handlers():
    """返回当前注册的事件处理器清单（事件 -> handler 列表）。

    数据来自事件注册中心（已注册事件）与事件监听器配置（每个事件绑定的处理器）。
    """
    try:
        sys.path.insert(0, os.path.join(_ROOT_DIR, 'src', 'web'))
        from core.event_registry import list_events
        events = list_events()
    except Exception as e:
        log.warning('读取事件注册中心失败: %s', e)
        events = []

    cfg_path = os.path.join(_LISTENER_DIR, 'event_listener_config.json')
    cfg = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    configured = cfg.get('events', {}) or {}

    handlers = []
    for ev in events:
        name = ev.get('name')
        ev_handlers = configured.get(name, []) or []
        normalized = []
        for h in ev_handlers:
            if isinstance(h, str):
                normalized.append({'script': h, 'args': []})
            elif isinstance(h, dict) and h.get('script'):
                normalized.append({'script': h.get('script'), 'args': h.get('args', []) or []})
        handlers.append({
            'event': name,
            'description': ev.get('description', ''),
            'source': ev.get('source', ''),
            'params': ev.get('params', []),
            'handlers': normalized,
            'enabled': len(normalized) > 0,
        })

    return jsonify({
        'success': True,
        'handlers': handlers,
    })
