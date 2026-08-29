"""服务运维面板（本地版，运行于主 Web 服务 dbox-web 进程，端口 8080）。

背景与动机：
    原 service-ops 插件运行在 extensions_host（dbox-extensions，8093）进程内。
    服务管理页要管理「基础设施服务」，其中就包括 dbox-extensions 自身——
    一旦用户停掉它，管理接口随之不可用，页面既读不到服务列表，也没法用它把
    dbox-extensions 重新拉起（鸡生蛋问题）。用户视角下这就是 bug。

    本模块把服务管理接口下沉到始终在线的 dbox-web 主服务进程，彻底去掉对
    dbox-extensions 的依赖：停掉 dbox-extensions 后，管理页仍能列出所有服务
    （含 dbox-extensions 自身为 STOPPED），并能通过本页把它重新启动。

实现：
    与 extensions/service-ops/backend/server.py 共用同一套 NSSM 扫描/控制纯函数
    （_scan_nssm_services / _get_service_info / _control_service 等）。为避免重复
    实现导致逻辑漂移，这里用 importlib 直接加载扩展文件并复用其函数，仅替换
    鉴权装饰器（使用主服务 backend.access.admin_required）。
"""
import os
import json
import importlib.util

from flask import Blueprint, request, jsonify, Response, stream_with_context

from backend.access import admin_required

# ---------------------------------------------------------------------------
# 复用扩展中的纯函数级实现（扫描 / 状态 / 控制 / 日志解析）
# ---------------------------------------------------------------------------
_THIS = os.path.dirname(os.path.abspath(__file__))            # .../src/web/backend
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS)))   # dbox 根
_EXT_SERVER = os.path.join(_PROJECT_ROOT, 'extensions', 'service-ops',
                           'backend', 'server.py')

_ext = None


def _load_ext():
    """加载扩展 server.py 模块（进程内只加载一次），复用其 NSSM 逻辑。"""
    global _ext
    if _ext is not None:
        return _ext
    spec = importlib.util.spec_from_file_location('dbox_ext_service_ops_shim', _EXT_SERVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _ext = mod
    # 启动与扩展同源的后台扫描线程，保证 /services 始终有最新缓存
    try:
        mod._ensure_scanner()
    except Exception:
        pass
    return _ext


# 延迟引用（在蓝图创建时确保模块已加载）
def _m():
    return _load_ext()


bp = Blueprint('service_ops_local', __name__, url_prefix='/api/ext/service-ops')


@bp.route('/services', methods=['GET'])
@admin_required
def services():
    m = _m()
    with m._CACHE_LOCK:
        empty = not m._CACHE
    if empty:
        m._do_scan()
    svcs = m._all_services()
    if not svcs:
        svcs = [{
            'name': n, 'service_name': n,
            'display_name': meta.get('display_name', n),
            'description': meta.get('description', ''),
            'status': 'unknown', 'system_status': 'unknown',
            'pid': None, 'memory_mb': None, 'cpu_percent': None,
            'port': meta.get('port'), 'health_status': 'unknown',
        } for n, meta in m._SERVICE_META.items()]
    return jsonify({'success': True, 'services': svcs})


@bp.route('/health', methods=['GET'])
@admin_required
def health():
    m = _m()
    svcs = m._all_services()
    down = [s['name'] for s in svcs if s.get('status') not in m._ONLINE_STATES]
    return jsonify({
        'success': True,
        'all_ok': len(down) == 0,
        'down': down,
        'services': svcs,
    })


@bp.route('/restart-all', methods=['POST'])
@admin_required
def restart_all():
    """重启所有非核心基础设施的 dbox 服务（模拟「重启整机」）。

    本接口运行在 dbox-web 进程，重启 dbox-extensions 不会中断本请求，
    因此可放心将其纳入重启范围（与扩展版不同，扩展版需排除自身宿主）。
    总线/服务管理/看门狗为基础设施，始终排除。
    """
    m = _m()
    excluded = {'dbox-bus', 'dbox-servicemgr', 'dbox-watchdog'}
    names = m._scan_nssm_services()
    order = ['dbox-thumbnail', 'dbox-systemd', 'dbox-resource', 'dbox-userd',
             'dbox-searchd', 'dbox-collectiond', 'dbox-historyd', 'dbox-downloader',
             'dbox-scheduler', 'dbox-extensions', 'dbox-webui', 'dbox-web']
    ordered = [n for n in order if n in names and n not in excluded]
    ordered += [n for n in names if n not in ordered and n not in excluded]
    results = {}
    for n in ordered:
        try:
            ok, msg = m._control_service(n, 'restart')
        except Exception as e:
            ok, msg = False, str(e)
        results[n] = {'success': ok, 'message': msg}
        with m._CACHE_LOCK:
            m._CACHE[n] = m._get_service_info(n)
        import time as _t
        _t.sleep(0.5)
    return jsonify({
        'success': True,
        'restarted': [n for n, v in results.items() if v['success']],
        'failed': [n for n, v in results.items() if not v['success']],
        'excluded': sorted(excluded),
        'results': results,
    })


@bp.route('/<name>/control', methods=['POST'])
@admin_required
def control(name):
    m = _m()
    if name not in m._SERVICE_META and name not in m._scan_nssm_services():
        return jsonify({'success': False, 'message': '未知服务: ' + name}), 404
    data = request.get_json(silent=True) or {}
    action = data.get('action')
    if action not in ('start', 'stop', 'restart'):
        return jsonify({'success': False, 'message': 'action 需为 start/stop/restart'}), 400
    # 与看门狗协同：人工停止的服务在抑制窗口内不被自动拉起；
    # 人工启动/重启则恢复正常自愈（清除可能残留的抑制）。
    try:
        if action == 'stop':
            m._set_suppress(name)
        else:
            m._clear_suppress(name)
    except Exception:
        pass
    # 本接口运行在 dbox-web 进程，控制 dbox-extensions 不会中断当前请求，
    # 因此无需像扩展版那样「先返回、后延迟执行」。
    ok, msg = m._control_service(name, action)
    with m._CACHE_LOCK:
        m._CACHE[name] = m._get_service_info(name)
    return jsonify({'success': ok, 'message': msg, 'status': m._CACHE.get(name)})


@bp.route('/logs', methods=['GET'])
@admin_required
def logs():
    m = _m()
    cat = request.args.get('cat') or request.args.get('type') or 'runtime'
    try:
        limit = int(request.args.get('limit', 200))
    except ValueError:
        limit = 200
    module = request.args.get('module')
    level = request.args.get('level')
    keyword = request.args.get('keyword')
    lines, total, has_more, modules = m._read_log(cat, limit=limit,
                                                  module=module, level=level, keyword=keyword)
    return jsonify({'success': True, 'cat': cat, 'lines': lines,
                    'total': total, 'has_more': has_more, 'modules': modules})


@bp.route('/logs/stream', methods=['GET'])
@admin_required
def logs_stream():
    m = _m()
    cat = request.args.get('cat', 'runtime')
    env = os.environ.get('DBOX_DATA_DIR')
    base = env or os.path.join(m._ROOT, 'data')
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
                    import time as _t
                    _t.sleep(1)
                    continue
                pl = m._parse_log_line(line, cat)
                if not pl:
                    continue
                payload = {'ts': pl['timestamp'], 'level': pl['level'] or 'INFO',
                           'module': pl['service'], 'msg': pl['content']}
                yield 'data: ' + json.dumps(payload, ensure_ascii=False) + '\n\n'
    return Response(stream_with_context(gen()), mimetype='text/event-stream')
