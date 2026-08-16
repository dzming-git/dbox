"""Auto-split blueprint: system_api (moved from main.py)."""
from backend.paths import DATA_DIR
import threading
from backend.system_helpers import SETTINGS_DEFAULTS
from backend.system_helpers import _do_windows_shutdown
import time
from core.models import Tag
from backend.audit import log_operation
from backend.system_helpers import parse_log_line
from core.models import User
from backend.system_helpers import _SERVICE_META
from backend.system_helpers import _svc_control_locks
from backend.system_helpers import _count_active_tasks
from backend.system_helpers import _SHUTDOWN_LOCK
from backend.system_helpers import _SHUTDOWN_CANCEL
from backend.system_helpers import _shutdown_threading
from core.models import db
from backend.system_helpers import save_config
import os
from core.models import UserRole
from core.models import ResourceLibrary
from core.models import LibraryPermission
from core.models import LibraryUserGroupMember
from core.models import Video
from core.models import AppSetting
from datetime import datetime, timedelta
from backend.runtime import runtime
from backend.access import get_allowed_library_ids
from backend.access import resolve_identity
from backend.access import admin_required, auth_required
from backend.access import _perm_allows_write
from flask import Blueprint, request, jsonify, send_file, send_from_directory, session, g, abort, Response, current_app
from liblog import get_service_logger
log = get_service_logger('dbox-web')

bp = Blueprint('system_api', __name__)

@bp.route('/api/system/shutdown', methods=['POST'])
@admin_required
def system_shutdown():
    data = request.get_json(silent=True) or {}
    action = data.get('action', 'immediate')
    try:
        if action == 'scheduled':
            minutes = int(data.get('minutes', 0))
            if minutes <= 0:
                return jsonify({'success': False, 'message': '定时关机分钟数必须大于 0'}), 400
            _do_windows_shutdown(seconds=minutes * 60)
            return jsonify({'success': True, 'message': f'已安排 {minutes} 分钟后关机'})
        elif action == 'after_tasks':
            with _SHUTDOWN_LOCK:
                _SHUTDOWN_CANCEL['after_tasks'] = False

            def _wait():
                import time
                while True:
                    with _SHUTDOWN_LOCK:
                        if _SHUTDOWN_CANCEL['after_tasks']:
                            return
                    if _count_active_tasks() == 0:
                        _do_windows_shutdown(seconds=30)
                        return
                    time.sleep(15)

            _t = _shutdown_threading.Thread(target=_wait, daemon=True)
            _t.start()
            return jsonify({'success': True, 'message': '将在所有任务结束后关机（空闲后约 30 秒执行）'})
        else:  # immediate
            _do_windows_shutdown(seconds=0)
            return jsonify({'success': True, 'message': '正在关机…'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'关机指令执行失败: {e}'}), 500

@bp.route('/api/system/shutdown/cancel', methods=['POST'])
@admin_required
def system_shutdown_cancel():
    try:
        import subprocess
        subprocess.run('shutdown /a /f', shell=True, capture_output=True)
        with _SHUTDOWN_LOCK:
            _SHUTDOWN_CANCEL['after_tasks'] = True
        return jsonify({'success': True, 'message': '已取消关机计划'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'取消失败: {e}'}), 500

@bp.route('/api/settings', methods=['GET'])
def api_get_settings():
    """获取当前用户可见的分层设置（游客仅返回全局层与默认值）。

    返回 defaults / global / user 三层原始数据，浏览器层由前端自行合并。
    无需登录即可访问，以便游客也能继承管理员的全局默认。
    """
    user_id, role = resolve_identity()
    global_setting = AppSetting.query.filter_by(scope='global', owner='').first()
    global_data = global_setting.get_data() if global_setting else {}
    user_data = {}
    if user_id:
        user_setting = AppSetting.query.filter_by(scope='user', owner=str(user_id)).first()
        user_data = user_setting.get_data() if user_setting else {}
    return jsonify({
        'success': True,
        'defaults': SETTINGS_DEFAULTS,
        'global': global_data,
        'user': user_data,
        'is_admin': role >= UserRole.ADMIN,
    })

@bp.route('/api/settings', methods=['POST'])
@auth_required
def api_save_settings():
    """保存设置。

    body: { scope: 'user'|'global', settings: {...partial}, reset?: [keys] }
    - scope='global' 需要管理员权限，写入全站默认（owner=''）
    - scope='user'   写入当前登录用户（owner=用户ID），跨设备生效
    - reset 中的键会从该层删除（回落到下一层）
    """
    user_id, role = resolve_identity()
    body = request.get_json(silent=True) or {}
    scope = body.get('scope')
    settings = body.get('settings') or {}
    reset_keys = body.get('reset') or []

    if not isinstance(settings, dict):
        return jsonify({'success': False, 'message': 'settings 必须是对象', 'code': 400}), 400

    if scope == 'global':
        if role < UserRole.ADMIN:
            return jsonify({'success': False, 'message': '需要管理员权限', 'code': 403}), 403
        owner = ''
    elif scope == 'user':
        if not user_id:
            return jsonify({'success': False, 'message': '未登录', 'code': 401}), 401
        owner = str(user_id)
    else:
        return jsonify({'success': False, 'message': 'scope 必须是 user 或 global', 'code': 400}), 400

    record = AppSetting.query.filter_by(scope=scope, owner=owner).first()
    existing = record.get_data() if record else {}
    existing.update(settings)
    # 仅保留白名单内的键
    existing = {k: v for k, v in existing.items() if k in SETTINGS_DEFAULTS}
    for k in (reset_keys or []):
        existing.pop(k, None)

    if record is None:
        record = AppSetting(scope=scope, owner=owner)
        db.session.add(record)
    record.set_data(existing)
    db.session.commit()
    log_operation('save settings', target=f'层={scope}', detail=f'键={list(settings.keys())}', success=True)
    return jsonify({'success': True, 'scope': scope, 'data': record.get_data()})

@bp.route('/api/admin/config', methods=['GET'])
@admin_required
def get_system_config():
    """获取系统配置"""
    try:
        # 从数据库或配置文件读取
        config = {
            'max_upload_size': 1024,  # MB
            'thumbnail_quality': 85,
            'auto_sync': True,
            'allow_register': False
        }
        return jsonify({'success': True, 'config': config})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/config', methods=['POST'])
@admin_required
def update_system_config():
    """更新系统配置"""
    try:
        data = request.get_json()
        # 这里可以保存到数据库或配置文件
        return jsonify({'success': True, 'message': '配置已保存'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/config', methods=['GET'])
def get_config():
    return jsonify({'success': True, 'config': runtime.app_config})

@bp.route('/api/config', methods=['PUT'])
def update_config():
    try:
        data = request.get_json()
        changed_keys = set(data.keys()) & {
            'library_watch_enabled', 'auto_scan_on_startup',
            'scan_directories', 'watch_poll_interval', 'supported_formats',
        }
        for k, v in data.items():
            runtime.app_config[k] = v
        if save_config(runtime.app_config):
            log.maintenance('INFO', f"更新配置文件: {list(data.keys())}")
            # 与资源库扫描相关的开关变更时，重建监控器/触发扫描（后台执行，避免阻塞响应）
            if changed_keys:
                try:
                    import threading as _tw
                    from backend.library_helpers import _restart_library_watchers, _initial_library_scan

                    def _apply_scan_config():
                        try:
                            _restart_library_watchers()
                            if runtime.app_config.get('auto_scan_on_startup', True):
                                _initial_library_scan()
                        except Exception as _e:
                            log.debug('ERROR', f'应用扫描配置失败: {_e}')

                    _tw.Thread(target=_apply_scan_config, daemon=True,
                               name='apply-scan-config').start()
                except Exception as _e:
                    log.debug('ERROR', f'应用扫描配置失败: {_e}')
            return jsonify({'success': True, 'config': runtime.app_config})
        return jsonify({'success': False, 'message': '保存失败'}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/status')
def status():
    try:
        # 获取用户权限过滤后的视频数量
        allowed_library_ids = get_allowed_library_ids()
        
        if allowed_library_ids:
            # 过滤：library_id 为 NULL（主数据库的视频）或在允许的资源库中
            filtered_query = Video.query.filter(
                (Video.library_id == None) |
                (Video.library_id.in_(allowed_library_ids))
            ).filter(Video.in_trash == False)
            video_count = filtered_query.count()
        else:
            # 未登录或无权限用户只能看到主数据库的视频
            video_count = Video.query.filter(Video.library_id == None, Video.in_trash == False).count()
        
        return jsonify({
            'success': True,
            'status': 'running',
            'database': {
                'videos': video_count,
                'tags': Tag.query.count()
            },
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/services', methods=['GET'])
@admin_required
def get_services():
    """
    获取所有 dbox 服务的状态。

    架构说明：
    - 优先通过总线向 servicemgrd 查询缓存的服务状态
    - servicemgrd 后台每 5 秒扫描一次，API 请求不应重复扫描
    - 如果总线不可用，返回静态服务列表（不调用 Windows API）
    - 注意：每个请求创建独立的 BusClient，避免多线程共享 zmq socket 的问题
    """
    import time
    bus_start = time.time()

    # 1. 优先通过总线查询 servicemgrd 缓存的状态
    # 注意：由于 zmq socket 不是线程安全的，每个请求创建独立的 BusClient
    try:
        from servicebus import BusClient
        _svc_bus = BusClient(
            f'web-svc-req-{id(time.time())}',
            host='127.0.0.1',
            rpc_port=15555,
            pub_port=15556
        )
        result = _svc_bus.call_method(
            'com.dbox.servicemgr',
            'com.dbox.ServiceMgr',
            'ListServices',
            {},
            timeout=3000  # 3秒超时，给 servicemgrd 足够的响应时间
        )
        bus_elapsed = (time.time() - bus_start) * 1000

        if result and 'services' in result:
            # 转换总线返回的字段名以匹配前端期望
            services = []
            for svc in result['services']:
                services.append({
                    'service_name': svc.get('name', ''),
                    'display_name': svc.get('display_name', svc.get('name', '')),
                    'description': svc.get('description', ''),
                    'port': svc.get('port'),
                    'system_status': svc.get('status', 'unknown'),
                    'pid': svc.get('pid'),
                    'memory_mb': svc.get('memory_mb'),
                    'cpu_percent': svc.get('cpu_percent'),
                    'health_status': svc.get('health_status', 'unknown'),
                    'health_latency_ms': svc.get('latency_ms'),
                    'health_detail': svc.get('description', ''),
                })
            return jsonify({
                'success': True,
                'services': services,
                'source': 'bus',
                'bus_time_ms': round(bus_elapsed, 1),
            })
    except Exception as e:
        bus_elapsed = (time.time() - bus_start) * 1000
        log.debug('WARN', f'总线查询失败 ({bus_elapsed:.0f}ms): {e}')

    # 2. Fallback：总线 / servicemgrd 不可用时，直接扫描 Windows 服务真实状态。
    #    servicemgrd 仍是权威来源（source='bus' 优先），但路由器重启等情况下它会
    #    暂时不可达——若只返回全 unknown，前端所有服务的操作按钮都会消失，页面像
    #    "卡死"。这里回退为真实系统扫描，保证页面始终可见真实 RUNNING/STOPPED。
    log.debug('WARN', 'servicemgrd 不可用，回退为直接扫描 Windows 服务状态')
    try:
        from backend.system_helpers import _scan_services, _get_service_status
        scanned = _scan_services()
    except Exception as e:
        log.debug('WARN', f'服务扫描失败: {e}')
        scanned = []

    if scanned:
        services = []
        for svc_name in scanned:
            meta = _SERVICE_META.get(svc_name, {})
            st = _get_service_status(svc_name)
            services.append({
                'service_name': svc_name,
                'display_name': meta.get('display_name', svc_name),
                'description': meta.get('description', ''),
                'port': meta.get('port'),
                'system_status': st.get('status', 'unknown'),
                'pid': st.get('pid'),
                'memory_mb': st.get('memory_mb'),
                'cpu_percent': st.get('cpu_percent'),
                'health_status': 'unknown',
                'health_latency_ms': None,
                'health_detail': '服务管理器不可用，已直接扫描系统状态',
            })
        return jsonify({
            'success': True,
            'services': services,
            'source': 'scan',  # 直接扫描得到的真实状态（可能不含健康检查）
            'warning': 'servicemgrd 不可用，状态由直接扫描系统服务获得',
        })

    # 3. 扫描也失败，退回静态列表（仅展示元信息，状态 unknown）
    log.debug('WARN', '服务扫描也失败，返回静态服务列表')
    services = []
    for svc_name, meta in _SERVICE_META.items():
        services.append({
            'service_name': svc_name,
            'display_name': meta.get('display_name', svc_name),
            'description': meta.get('description', ''),
            'port': meta.get('port'),
            'system_status': 'unknown',  # 静态列表不知道运行时状态
            'pid': None,
            'memory_mb': None,
            'cpu_percent': None,
            'health_status': 'unknown',
            'health_latency_ms': None,
            'health_detail': '服务管理器不可用',
        })

    return jsonify({
        'success': True,
        'services': services,
        'source': 'static',  # 明确标识这是静态列表，不是实时扫描
        'warning': 'servicemgrd 不可用，状态可能不是最新的',
    })


@bp.route('/api/admin/health', methods=['GET'])
@admin_required
def get_health():
    """
    获取看门狗（com.dbox.watchdog）汇总的整体健康状态与逐服务详情。

    优先读取看门狗的实时巡检结果（含总线 ping、自动重启次数、告警）。
    若看门狗不可用，则直接聚合 servicemgrd 的 Windows 服务状态作为兜底。
    """
    import time

    # 1. 优先读看门狗的汇总结果
    try:
        from servicebus import BusClient
        _wdbus = BusClient(
            f'web-health-req-{id(time.time())}',
            host='127.0.0.1', rpc_port=15555, pub_port=15556
        )
        try:
            result = _wdbus.call_method(
                'com.dbox.watchdog', 'com.dbox.Watchdog', 'GetHealth',
                {}, timeout=3000
            )
        finally:
            _wdbus.stop()
        if result and 'overall_status' in result:
            return jsonify({
                'success': True,
                'overall_status': result.get('overall_status'),
                'services': result.get('services', []),
                'alerts': result.get('alerts', []),
                'last_check': result.get('last_check'),
                'uptime': result.get('uptime'),
                'config': result.get('config'),
                'source': 'watchdog',
            })
    except Exception as e:
        log.debug('WARN', f'看门狗查询失败，回退 servicemgrd: {e}')

    # 2. 兜底：直接聚合 servicemgrd 的 Windows 服务状态
    try:
        from servicebus import BusClient as _BC
        _smb = _BC(f'web-health-fb-{id(time.time())}',
                   host='127.0.0.1', rpc_port=15555, pub_port=15556)
        try:
            svc_result = _smb.call_method(
                'com.dbox.servicemgr', 'com.dbox.ServiceMgr', 'ListServices',
                {}, timeout=3000
            )
        finally:
            _smb.stop()
        if svc_result and 'services' in svc_result:
            services = []
            overall = 'healthy'
            for svc in svc_result['services']:
                win = svc.get('status', 'unknown')
                health = svc.get('health_status', 'unknown')
                if win not in ('RUNNING', 'PAUSED'):
                    svc_status = 'down'
                elif health in ('unhealthy', 'timeout', 'offline'):
                    svc_status = 'down'
                else:
                    svc_status = 'healthy'
                if svc_status != 'healthy':
                    overall = 'degraded'
                services.append({
                    'name': svc.get('name'),
                    'display': svc.get('display_name', svc.get('name')),
                    'bus_name': None,
                    'status': svc_status,
                    'windows_status': win,
                    'bus_reachable': None,
                    'consecutive_failures': 0,
                    'restart_count': 0,
                    'last_success': None,
                    'last_failure': None,
                    'last_restart': None,
                    'alerted': False,
                    'last_error': None,
                })
            return jsonify({
                'success': True,
                'overall_status': overall,
                'services': services,
                'alerts': [],
                'last_check': time.time(),
                'uptime': None,
                'config': None,
                'source': 'servicemgr-fallback',
                'warning': '看门狗不可用，状态由服务管理器聚合',
            })
    except Exception as e:
        log.debug('WARN', f'servicemgrd 兜底查询也失败: {e}')

    return jsonify({
        'success': False,
        'overall_status': 'unknown',
        'services': [],
        'alerts': [],
        'message': '看门狗与服务管理器均不可用',
    }), 503

@bp.route('/api/admin/services/<service_name>/control', methods=['POST'])
@admin_required
def control_service(service_name):
    """控制服务：start / stop / restart（通过 servicemgrd 总线）"""
    try:
        data = request.get_json()
        action = data.get('action', '').lower()

        if action not in ('start', 'stop', 'restart'):
            return jsonify({'success': False, 'message': f'无效操作: {action}'}), 400

        # 安全检查：只允许操作 dbox- 前缀的服务
        if not service_name.startswith('dbox-'):
            return jsonify({'success': False, 'message': '只允许操作 dbox- 前缀的服务'}), 403

        # 防并发锁
        if service_name not in _svc_control_locks:
            _svc_control_locks[service_name] = threading.Lock()

        if not _svc_control_locks[service_name].acquire(blocking=False):
            return jsonify({'success': False, 'message': '该服务正在操作中，请稍后再试'}), 409

        try:
            display_name = _SERVICE_META.get(service_name, {}).get('display_name', service_name)
            action_text = {'start': '启动', 'stop': '停止', 'restart': '重启'}

            # 优先通过总线调用 servicemgrd
            if runtime.svc_mgr_bus:
                try:
                    method_name = f'{action.capitalize()}Service'
                    result = runtime.svc_mgr_bus.call_method(
                        'com.dbox.servicemgr',
                        'com.dbox.ServiceMgr',
                        method_name,
                        {'name': service_name}
                    )
                    if result:
                        log.maintenance('INFO', f'服务 {service_name} {action} via bus: {result}')
                        return jsonify({
                            'success': result.get('success', False),
                            'message': result.get('message', ''),
                            'action': action,
                        })
                except Exception as bus_err:
                    log.debug('WARN', f'总线控制服务失败，降级到直接调用: {bus_err}')

            # 降级：直接调用 win32service
            import win32service

            scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
            svc = win32service.OpenService(scm, service_name, win32service.SERVICE_ALL_ACCESS)

            try:
                if action == 'start':
                    win32service.StartService(svc, None)
                elif action == 'stop':
                    win32service.ControlService(svc, win32service.SERVICE_CONTROL_STOP)
                elif action == 'restart':
                    status = win32service.QueryServiceStatus(svc)
                    if status[1] == win32service.SERVICE_RUNNING:
                        win32service.ControlService(svc, win32service.SERVICE_CONTROL_STOP)
                        for _ in range(30):
                            time.sleep(1)
                            status = win32service.QueryServiceStatus(svc)
                            if status[1] == win32service.SERVICE_STOPPED:
                                break
                            elif status[1] == win32service.SERVICE_STOP_PENDING:
                                continue
                            else:
                                break
                        else:
                            raise RuntimeError('停止服务超时（30秒）')
                    win32service.StartService(svc, None)
            finally:
                win32service.CloseServiceHandle(svc)
                win32service.CloseServiceHandle(scm)

            log.maintenance('INFO', f'服务 {service_name} {action} 成功（直接调用）')
            return jsonify({
                'success': True,
                'message': f'{display_name} {action_text[action]}成功',
                'action': action,
            })
        except Exception as e:
            error_msg = str(e)
            log.debug('ERROR', f'服务 {service_name} {action} 失败: {error_msg}')
            return jsonify({'success': False, 'message': error_msg}), 500
        finally:
            _svc_control_locks[service_name].release()

    except Exception as e:
        log.debug('ERROR', f'控制服务失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/logs', methods=['GET'])
@admin_required
def get_system_logs():
    """
    获取系统日志（从 liblog 日志文件读取），支持多维筛选。

    参数:
    - type:    日志类型 (maintenance/runtime/debug/operation)，默认 maintenance
    - service: 模块/服务名筛选（可选），如 'dbox-web'
    - level:   日志等级筛选（可选，仅对非 operation 类型有效），如 INFO/WARN/ERROR
    - user:    操作人筛选（可选，仅对 operation 类型有效），模糊匹配
    - keyword: 关键字筛选（可选），匹配 content（大小写不敏感）
    - date:    日期筛选 YYYY-MM-DD（可选），匹配该日产生的日志
    - page:    页码，默认 1
    - limit:   每页条数，默认 20
    """
    log_type = request.args.get('type', 'maintenance').strip().lower()
    service = request.args.get('service', '').strip() or None
    level = request.args.get('level', '').strip().upper() or None
    user = request.args.get('user', '').strip() or None
    keyword = request.args.get('keyword', '').strip() or None
    date = request.args.get('date', '').strip() or None
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 20, type=int)

    # 验证日志类型
    valid_types = ['maintenance', 'runtime', 'debug', 'operation']
    if log_type not in valid_types:
        return jsonify({'success': False, 'message': f'无效的日志类型，可选: {", ".join(valid_types)}'}), 400

    # 限制每页条数范围
    limit = max(1, min(limit, 200))
    page = max(1, page)

    # 日期筛选仅保留前缀（YYYY-MM-DD）
    if date:
        date = date[:10]

    # 日志文件路径
    log_dir = os.path.join(DATA_DIR, 'logs')
    log_file = os.path.join(log_dir, f'{log_type}.log')

    if not os.path.exists(log_file):
        return jsonify({
            'success': True,
            'logs': [],
            'total': 0,
            'page': page,
            'limit': limit,
            'total_pages': 0,
            'type': log_type,
            'service': service,
            'level': level,
            'user': user,
            'keyword': keyword,
            'date': date,
            'services': [],
            'modules': [],
            'levels': [],
            'users': []
        })

    # 读取并解析日志文件
    try:
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            with open(log_file, 'r', encoding='gbk', errors='replace') as f:
                lines = f.readlines()

        parsed_logs = []
        services_set = set()
        levels_set = set()
        users_set = set()
        for line in lines:
            line = line.strip()
            if not line:
                continue

            parsed = parse_log_line(line, log_type)
            if not parsed:
                continue

            # ---- 多维筛选 ----
            # 模块/服务
            if service and parsed.get('service') != service:
                continue
            # 等级（非 operation 类型）
            if log_type != 'operation' and level and parsed.get('level') != level:
                continue
            # 操作人（operation 类型）
            if user:
                entry_user = parsed.get('user') or ''
                if user.lower() not in entry_user.lower():
                    continue
            # 关键字（content，大小写不敏感）
            if keyword and keyword.lower() not in parsed.get('content', '').lower():
                continue
            # 日期（时间戳前缀匹配 YYYY-MM-DD）
            if date and not parsed.get('timestamp', '').startswith(date):
                continue

            parsed_logs.append(parsed)
            if parsed.get('service'):
                services_set.add(parsed['service'])
            if log_type != 'operation' and parsed.get('level'):
                levels_set.add(parsed['level'])
            if parsed.get('user'):
                users_set.add(parsed['user'])

        # 倒序排列（最新在前）
        parsed_logs.reverse()
        # 倒序后，facet 集合保持原始去重即可
        services_set.update(services_set)
        levels_set.update(levels_set)
        users_set.update(users_set)

        # 计算分页
        total = len(parsed_logs)
        total_pages = (total + limit - 1) // limit if total > 0 else 0
        start = (page - 1) * limit
        end = start + limit
        page_logs = parsed_logs[start:end]

        return jsonify({
            'success': True,
            'logs': page_logs,
            'total': total,
            'page': page,
            'limit': limit,
            'total_pages': total_pages,
            'type': log_type,
            'service': service,
            'level': level,
            'user': user,
            'keyword': keyword,
            'date': date,
            'services': sorted(services_set),
            'modules': sorted(services_set),
            'levels': sorted(levels_set),
            'users': sorted(users_set)
        })

    except Exception as e:
        log.debug('ERROR', f'读取日志文件失败: {e}')
        return jsonify({'success': False, 'message': f'读取日志失败: {str(e)}'}), 500

@bp.route('/api/admin/users', methods=['GET'])
@admin_required
def get_admin_users():
    """获取用户列表（管理员）"""
    try:
        users = User.query.all()
        return jsonify({
            'success': True,
            'users': [{
                'id': u.id,
                'username': u.username,
                'role': u.role,
                'role_name': u.role_name,
                'created_at': u.created_at.isoformat() if u.created_at else None
            } for u in users]
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/users', methods=['POST'])
@admin_required
def create_admin_user():
    """创建新用户（管理员）"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        role_str = data.get('role', 'user')
        
        # 将字符串角色转换为数字
        role_map = {
            'guest': UserRole.GUEST,
            'user': UserRole.USER,
            'admin': UserRole.ADMIN,
            'root': UserRole.ROOT
        }
        role = role_map.get(role_str, UserRole.USER)

        # ROOT 账号仅允许 ROOT 创建，防止普通管理员越权提权
        if role == UserRole.ROOT and g.role < UserRole.ROOT:
            return jsonify({'success': False, 'message': '只有超级管理员可以创建超级管理员账号'}), 403

        if not username or not password:
            return jsonify({'success': False, 'message': '用户名和密码不能为空'}), 400
        
        if User.query.filter_by(username=username).first():
            return jsonify({'success': False, 'message': '用户名已存在'}), 400
        
        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        log.maintenance('INFO', f"创建用户: {username} (角色: {user.role_name})")
        log_operation('create user', target=username, detail=f'角色={user.role_name}', success=True)
        
        return jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'role': user.role,
                'role_name': user.role_name
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/users/<int:user_id>', methods=['PUT'])
@admin_required
def update_admin_user(user_id):
    """更新用户信息（管理员）"""
    try:
        user = User.query.get_or_404(user_id)
        data = request.get_json()

        # 更新用户名
        if 'username' in data:
            new_username = data['username'].strip()
            if not new_username:
                return jsonify({'success': False, 'message': '用户名不能为空'}), 400
            # 检查用户名是否已被其他用户占用
            existing_user = User.query.filter_by(username=new_username).first()
            if existing_user and existing_user.id != user_id:
                return jsonify({'success': False, 'message': '用户名已存在'}), 400
            user.username = new_username

        # 更新角色
        if 'role' in data:
            role_map = {
                'guest': UserRole.GUEST,
                'user': UserRole.USER,
                'admin': UserRole.ADMIN,
                'root': UserRole.ROOT
            }
            new_role = role_map.get(data['role'], UserRole.USER)
            # ROOT 账号仅允许 ROOT 修改
            if user.role == UserRole.ROOT and g.role < UserRole.ROOT:
                return jsonify({'success': False, 'message': '只有超级管理员可以修改超级管理员账号'}), 403
            # 禁止普通管理员把任意账号提权为 ROOT
            if new_role == UserRole.ROOT and g.role < UserRole.ROOT:
                return jsonify({'success': False, 'message': '只有超级管理员可以设置超级管理员角色'}), 403
            user.role = new_role

        # 更新密码（如果提供了）
        if data.get('password'):
            user.set_password(data['password'])

        db.session.commit()
        log.maintenance('INFO', f"更新用户信息: {user.username} (ID: {user_id})")
        log_operation('update user', target=user.username, detail=f'角色={user.role_name}', success=True)

        return jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'role': user.role,
                'role_name': user.role_name
            }
        })
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"更新用户信息失败: {user_id}, {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_admin_user(user_id):
    """删除用户（管理员）"""
    try:
        user = User.query.get_or_404(user_id)
        # ROOT 账号仅允许 ROOT 删除
        if user.role == UserRole.ROOT and g.role < UserRole.ROOT:
            return jsonify({'success': False, 'message': '只有超级管理员可以删除超级管理员账号'}), 403
        if user.id == g.user_id:
            return jsonify({'success': False, 'message': '不能删除当前登录用户'}), 400
        db.session.delete(user)
        db.session.commit()
        log.maintenance('INFO', f"删除用户: {user.username} (ID: {user_id})")
        log_operation('delete user', target=user.username, success=True)
        return jsonify({'success': True, 'message': '用户已删除'})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"删除用户失败: {user_id}, {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


def _effective_library_perm(user, library_id):
    """返回用户对某库的实际生效权限级别：'none'/'read'/'write'/'admin'/'full'。

    管理员(role>=ADMIN)对激活库恒为 'full'；普通用户取直接授权/用户组授权/通用授权中
    最高的一档（admin > write > read；custom 按 permissions 推断，这里简化为 read/write）。
    """
    if user.role >= UserRole.ADMIN:
        lib = ResourceLibrary.query.get(library_id)
        if lib and lib.is_active:
            return 'full'
    best = None
    perms = list(LibraryPermission.query.filter_by(user_id=user.id).all())
    for m in LibraryUserGroupMember.query.filter_by(user_id=user.id).all():
        perms.extend(LibraryPermission.query.filter_by(group_id=m.group_id).all())
    perms.extend(LibraryPermission.query.filter_by(user_id=None).all())
    rank = {'read': 1, 'write': 2, 'admin': 3}
    for p in perms:
        if p.library_id != library_id:
            continue
        lvl = p.access_level or 'read'
        if lvl == 'custom':
            lvl = 'write' if _perm_allows_write(p) else 'read'
        r = rank.get(lvl, 1)
        if best is None or r > rank.get(best, 1):
            best = lvl
    if best == 'admin':
        return 'admin'
    if best == 'write':
        return 'write'
    if best == 'read':
        return 'read'
    return 'none'


@bp.route('/api/admin/users/<int:user_id>/library-permissions', methods=['GET'])
@admin_required
def get_user_library_permissions(user_id):
    """获取指定用户对全部资源库的读写权限（仅直接授权 + 用户组授权，不含管理员默认全权）。"""
    try:
        user = User.query.get_or_404(user_id)
        libraries = ResourceLibrary.query.filter_by(is_active=True).order_by(ResourceLibrary.id).all()
        # 该用户已有的直接授权记录（用于区分"无"与"有记录但仅通用授权"）
        direct = {p.library_id: p for p in LibraryPermission.query.filter_by(user_id=user.id).all()}
        data = [{
            'library_id': lib.id,
            'library_name': lib.name,
            'effective': _effective_library_perm(user, lib.id),
            'direct_level': direct.get(lib.id).access_level if lib.id in direct else None,
        } for lib in libraries]
        return jsonify({
            'success': True,
            'is_admin': user.role >= UserRole.ADMIN,
            'libraries': data,
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/admin/users/<int:user_id>/library-permissions', methods=['POST'])
@admin_required
def set_user_library_permissions(user_id):
    """批量设置指定用户对各资源库的读写权限。

    body: { permissions: [ { library_id, level } ] }  level ∈ 'none'|'read'|'write'
    仅修改该用户的「直接授权」记录；'none' 表示删除该用户针对该库的直接授权。
    管理员(role>=ADMIN)对所有激活库默认可读写，不允许通过此接口改降。
    """
    try:
        user = User.query.get_or_404(user_id)
        if user.role >= UserRole.ADMIN:
            return jsonify({'success': False, 'message': '管理员默认拥有全部资源库权限，无需单独设置'}), 400
        data = request.get_json(silent=True) or {}
        items = data.get('permissions', [])
        if not isinstance(items, list):
            return jsonify({'success': False, 'message': 'permissions 必须是数组'}), 400

        allowed = {'none', 'read', 'write'}
        for item in items:
            lid = item.get('library_id')
            level = item.get('level')
            if lid is None or level not in allowed:
                return jsonify({'success': False, 'message': '无效的 library_id 或 level'}), 400
            lib = ResourceLibrary.query.get(lid)
            if not lib or not lib.is_active:
                return jsonify({'success': False, 'message': f'资源库不存在或未激活: {lid}'}), 400

        # 一次性覆盖：先删除该用户现有直接授权，再按请求重建
        LibraryPermission.query.filter_by(user_id=user.id).delete()
        for item in items:
            lid = item['library_id']
            level = item['level']
            if level == 'none':
                continue
            db.session.add(LibraryPermission(
                user_id=user.id,
                library_id=lid,
                access_level=level,
                granted_by=g.user_id,
            ))
        db.session.commit()
        log.maintenance('INFO', f"更新用户资源库权限: {user.username} (ID: {user_id})")
        log_operation('update user library permissions', target=user.username, success=True)
        return jsonify({'success': True, 'message': '资源库权限已更新'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
