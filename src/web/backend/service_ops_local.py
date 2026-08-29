"""服务运维面板（本地版，运行于主 Web 服务 dbox-web 进程，端口 8080）。

把原 extensions/service-ops 插件的能力下沉到核心：逻辑在 backend.service_ops_core，
本文件只承载 Flask 蓝图与路由，复用核心纯函数。不再 importlib 加载扩展文件，
因此可安全删除 extensions/service-ops 扩展（避免两份实现漂移）。

控制面常驻于 dbox-web，独立于被它管理的 dbox-extensions：停掉 dbox-extensions 后，
管理页仍能列出所有服务（含其自身为 STOPPED）并把它重新拉起。
"""
import os
import json
import time

from flask import Blueprint, request, jsonify, Response, stream_with_context

from backend.access import admin_required
from backend import service_ops_core as _core

# 启动与核心同源的后台扫描线程，保证 /services 始终有最新缓存
_core._ensure_scanner()

bp = Blueprint('service_ops_local', __name__, url_prefix='/api/admin')


@bp.route('/services', methods=['GET'])
@admin_required
def services():
    with _core._CACHE_LOCK:
        empty = not _core._CACHE
    if empty:
        _core._do_scan()
    svcs = _core._all_services()
    if not svcs:
        svcs = [{
            'name': n, 'service_name': n,
            'display_name': meta.get('display_name', n),
            'description': meta.get('description', ''),
            'status': 'unknown', 'system_status': 'unknown',
            'pid': None, 'memory_mb': None, 'cpu_percent': None,
            'port': meta.get('port'), 'health_status': 'unknown',
        } for n, meta in _core._SERVICE_META.items()]
    return jsonify({'success': True, 'services': svcs})


@bp.route('/health', methods=['GET'])
@admin_required
def health():
    svcs = _core._all_services()
    down = [s['name'] for s in svcs if s.get('status') not in _core._ONLINE_STATES]
    return jsonify({
        'success': True,
        'all_ok': len(down) == 0,
        'down': down,
        'services': svcs,
    })


@bp.route('/services/restart-all', methods=['POST'])
@admin_required
def restart_all():
    """重启所有非核心基础设施的 dbox 服务（模拟「重启整机」）。

    本接口运行在 dbox-web 进程，重启 dbox-extensions 不会中断本请求，
    因此可放心将其纳入重启范围（与扩展版不同，扩展版需排除自身宿主）。
    总线/服务管理/看门狗为基础设施，始终排除。
    """
    excluded = {'dbox-bus', 'dbox-servicemgr', 'dbox-watchdog'}
    names = _core._scan_nssm_services()
    order = ['dbox-thumbnail', 'dbox-systemd', 'dbox-resource', 'dbox-userd',
             'dbox-searchd', 'dbox-collectiond', 'dbox-historyd', 'dbox-downloader',
             'dbox-scheduler', 'dbox-extensions', 'dbox-webui', 'dbox-web']
    ordered = [n for n in order if n in names and n not in excluded]
    ordered += [n for n in names if n not in ordered and n not in excluded]
    results = {}
    for n in ordered:
        try:
            ok, msg = _core._control_service(n, 'restart')
        except Exception as e:
            ok, msg = False, str(e)
        results[n] = {'success': ok, 'message': msg}
        with _core._CACHE_LOCK:
            _core._CACHE[n] = _core._get_service_info(n)
        time.sleep(0.5)
    return jsonify({
        'success': True,
        'restarted': [n for n, v in results.items() if v['success']],
        'failed': [n for n, v in results.items() if not v['success']],
        'excluded': sorted(excluded),
        'results': results,
    })


@bp.route('/services/<name>/control', methods=['POST'])
@admin_required
def control(name):
    if name not in _core._SERVICE_META and name not in _core._scan_nssm_services():
        return jsonify({'success': False, 'message': '未知服务: ' + name}), 404
    data = request.get_json(silent=True) or {}
    action = data.get('action')
    if action not in ('start', 'stop', 'restart'):
        return jsonify({'success': False, 'message': 'action 需为 start/stop/restart'}), 400
    # 与看门狗协同：人工停止的服务在抑制窗口内不被自动拉起；
    # 人工启动/重启则恢复正常自愈（清除可能残留的抑制）。
    try:
        if action == 'stop':
            _core._set_suppress(name)
        else:
            _core._clear_suppress(name)
    except Exception:
        pass
    # 本接口运行在 dbox-web 进程，控制 dbox-extensions 不会中断当前请求，
    # 因此无需像扩展版那样「先返回、后延迟执行」。
    ok, msg = _core._control_service(name, action)
    with _core._CACHE_LOCK:
        _core._CACHE[name] = _core._get_service_info(name)
    return jsonify({'success': ok, 'message': msg, 'status': _core._CACHE.get(name)})


@bp.route('/logs', methods=['GET'])
@admin_required
def logs():
    cat = request.args.get('cat') or request.args.get('type') or 'runtime'
    try:
        limit = int(request.args.get('limit', 200))
    except ValueError:
        limit = 200
    module = request.args.get('module')
    level = request.args.get('level')
    keyword = request.args.get('keyword')
    lines, total, has_more, modules = _core._read_log(cat, limit=limit,
                                                      module=module, level=level, keyword=keyword)
    return jsonify({'success': True, 'cat': cat, 'lines': lines,
                    'total': total, 'has_more': has_more, 'modules': modules})


@bp.route('/logs/stream', methods=['GET'])
@admin_required
def logs_stream():
    cat = request.args.get('cat', 'runtime')
    env = os.environ.get('DBOX_DATA_DIR')
    base = env or os.path.join(_core._ROOT, 'data')
    paths = {
        'maintenance': os.path.join(base, 'logs', 'maintenance.log'),
        'runtime': os.path.join(base, 'logs', 'runtime.log'),
        'debug': os.path.join(base, 'logs', 'debug.log'),
        'operation': os.path.join(base, 'logs', 'operation.log'),
    }
    p = paths.get(cat)
    if not p or not os.path.exists(p):
        return Response('data: {"line":null}\n\n', mimetype='text/event-stream')

    def gen():
        with open(p, 'r', encoding='utf-8', errors='replace') as f:
            f.seek(0, os.SEEK_END)
            while True:
                line = f.readline()
                if not line:
                    time.sleep(1)
                    continue
                pl = _core._parse_log_line(line, cat)
                if not pl:
                    continue
                payload = {'ts': pl['timestamp'], 'level': pl['level'] or 'INFO',
                           'module': pl['service'], 'msg': pl['content']}
                yield 'data: ' + json.dumps(payload, ensure_ascii=False) + '\n\n'
    return Response(stream_with_context(gen()), mimetype='text/event-stream')
