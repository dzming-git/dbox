"""事件监听器配置 API（管理后台可视化配置事件监听参数）。

提供：
- GET  /api/admin/event-listener/config  读取当前配置（含默认结构与可选脚本列表）
- PUT  /api/admin/event-listener/config  保存配置并自动重启监听器服务使其生效
- POST /api/admin/event-listener/restart 仅重启监听器服务

配置保存在 scripts/event_listener/event_listener_config.json（gitignore，属用户本地数据）。
"""
import os
import sys
import json
import subprocess

from flask import Blueprint, request, jsonify

from backend.access import admin_required
from liblog import get_service_logger

log = get_service_logger('dbox-web')

bp = Blueprint('event_listener_api', __name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_LISTENER_DIR = os.path.join(_ROOT, 'scripts', 'event_listener')
_CONFIG_PATH = os.path.join(_LISTENER_DIR, 'event_listener_config.json')
_HANDLERS_DIR = os.path.join(_LISTENER_DIR, 'handlers')

# 框架不再硬编码事件类型；事件由「事件注册中心」动态提供（见 src/web/core/event_registry.py）

DEFAULT_CONFIG = {
    'interval': 30,
    'events': {},
}


def _registered_events():
    """读取事件注册中心中的已注册事件列表。"""
    try:
        sys.path.insert(0, os.path.join(_ROOT, 'src', 'web'))
        from core.event_registry import list_events
        return list_events()
    except Exception as e:
        log.warning('读取事件注册中心失败: %s', e)
        return []


def _read_config():
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            log.warning('读取事件监听器配置失败: %s', e)
    return DEFAULT_CONFIG


def _available_scripts():
    """列出 handlers 目录下可用脚本，供前端下拉选择。"""
    out = []
    if os.path.isdir(_HANDLERS_DIR):
        for fn in sorted(os.listdir(_HANDLERS_DIR)):
            if fn.endswith('.py') or fn.endswith('.ps1') or fn.endswith('.bat') or fn.endswith('.sh'):
                out.append('handlers/' + fn)
    return out


def _restart_listener_service():
    """通过服务管理器重启监听器服务。返回 (success, message)。"""
    try:
        proc = subprocess.run(
            ['python', os.path.join(_ROOT, 'scripts', 'service_manager.py'), 'restart', 'listener'],
            cwd=_ROOT, capture_output=True, text=True, timeout=60,
        )
        ok = proc.returncode == 0
        msg = (proc.stdout or proc.stderr or '').strip().splitlines()[-1] if (proc.stdout or proc.stderr) else ''
        return ok, msg or ('重启成功' if ok else '重启失败')
    except Exception as e:
        return False, f'重启异常: {e}'


@bp.route('/api/admin/event-listener/config', methods=['GET'])
@admin_required
def get_listener_config():
    cfg = _read_config()
    registered = _registered_events()
    # 仅保留注册中心中存在的事件配置，避免过期事件残留
    valid_events = {ev['name']: ev for ev in registered}
    filtered_events = {k: v for k, v in cfg.get('events', {}).items() if k in valid_events}
    return jsonify({
        'success': True,
        'config': {'interval': cfg.get('interval', 30), 'events': filtered_events},
        'registered_events': registered,
        'available_scripts': _available_scripts(),
        'editable': True,
    })


@bp.route('/api/admin/event-listener/config', methods=['PUT'])
@admin_required
def save_listener_config():
    data = request.get_json(silent=True) or {}
    cfg = data.get('config')
    if not isinstance(cfg, dict):
        return jsonify({'success': False, 'message': '配置格式错误'}), 400

    interval = cfg.get('interval', 30)
    try:
        interval = int(interval)
    except Exception:
        interval = 30
    interval = max(5, min(interval, 3600))

    events = cfg.get('events', {})
    registered_names = {ev['name'] for ev in _registered_events()}
    normalized = {}
    # 只保存注册中心中存在的事件配置（用户可自由配置任意已注册事件）
    for ev in registered_names:
        handlers = events.get(ev, [])
        if not isinstance(handlers, list):
            handlers = []
        norm_list = []
        for h in handlers:
            if isinstance(h, str):
                norm_list.append({'script': h, 'args': []})
            elif isinstance(h, dict) and h.get('script'):
                args = h.get('args', []) or []
                if isinstance(args, str):
                    args = [a.strip() for a in args.split(',') if a.strip()]
                norm_list.append({'script': h['script'], 'args': args})
        normalized[ev] = norm_list

    new_cfg = {'interval': interval, 'events': normalized}
    try:
        with open(_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(new_cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return jsonify({'success': False, 'message': f'写入配置失败: {e}'}), 500

    ok, msg = _restart_listener_service()
    return jsonify({
        'success': True,
        'message': f'配置已保存{"" if ok else "，但重启服务失败: " + msg}',
        'restarted': ok,
    })


@bp.route('/api/admin/event-listener/restart', methods=['POST'])
@admin_required
def restart_listener():
    ok, msg = _restart_listener_service()
    return jsonify({'success': ok, 'message': msg})
