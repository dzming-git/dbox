"""Auto-split blueprint: system_api (moved from main.py)."""
from backend.access import admin_required, auth_required
from flask import Blueprint, request, jsonify, send_file, send_from_directory, session, g, abort, Response, current_app

bp = Blueprint('system_api', __name__)

@bp.route('/api/system/shutdown', methods=['POST'])
@admin_required
def system_shutdown():
    import main
    data = main.request.get_json(silent=True) or {}
    action = data.get('action', 'immediate')
    try:
        if action == 'scheduled':
            minutes = int(data.get('minutes', 0))
            if minutes <= 0:
                return main.jsonify({'success': False, 'message': '定时关机分钟数必须大于 0'}), 400
            main._do_windows_shutdown(seconds=minutes * 60)
            return main.jsonify({'success': True, 'message': f'已安排 {minutes} 分钟后关机'})
        elif action == 'after_tasks':
            with main._SHUTDOWN_LOCK:
                main._SHUTDOWN_CANCEL['after_tasks'] = False

            def _wait():
                import time
                while True:
                    with main._SHUTDOWN_LOCK:
                        if main._SHUTDOWN_CANCEL['after_tasks']:
                            return
                    if main._count_active_tasks() == 0:
                        main._do_windows_shutdown(seconds=30)
                        return
                    main.time.sleep(15)

            _t = main._shutdown_threading.Thread(target=_wait, daemon=True)
            _t.start()
            return main.jsonify({'success': True, 'message': '将在所有任务结束后关机（空闲后约 30 秒执行）'})
        else:  # immediate
            main._do_windows_shutdown(seconds=0)
            return main.jsonify({'success': True, 'message': '正在关机…'})
    except Exception as e:
        return main.jsonify({'success': False, 'message': f'关机指令执行失败: {e}'}), 500

@bp.route('/api/system/shutdown/cancel', methods=['POST'])
@admin_required
def system_shutdown_cancel():
    import main
    try:
        import subprocess
        subprocess.run('shutdown /a /f', shell=True, capture_output=True)
        with main._SHUTDOWN_LOCK:
            main._SHUTDOWN_CANCEL['after_tasks'] = True
        return main.jsonify({'success': True, 'message': '已取消关机计划'})
    except Exception as e:
        return main.jsonify({'success': False, 'message': f'取消失败: {e}'}), 500

@bp.route('/api/settings', methods=['GET'])
def api_get_settings():
    import main
    """获取当前用户可见的分层设置（游客仅返回全局层与默认值）。

    返回 defaults / global / user 三层原始数据，浏览器层由前端自行合并。
    无需登录即可访问，以便游客也能继承管理员的全局默认。
    """
    user_id, role = main.resolve_identity()
    global_setting = main.AppSetting.query.filter_by(scope='global', owner='').first()
    global_data = global_setting.get_data() if global_setting else {}
    user_data = {}
    if user_id:
        user_setting = main.AppSetting.query.filter_by(scope='user', owner=str(user_id)).first()
        user_data = user_setting.get_data() if user_setting else {}
    return main.jsonify({
        'success': True,
        'defaults': main.SETTINGS_DEFAULTS,
        'global': global_data,
        'user': user_data,
        'is_admin': role >= main.UserRole.ADMIN,
    })

@bp.route('/api/settings', methods=['POST'])
@auth_required
def api_save_settings():
    import main
    """保存设置。

    body: { scope: 'user'|'global', settings: {...partial}, reset?: [keys] }
    - scope='global' 需要管理员权限，写入全站默认（owner=''）
    - scope='user'   写入当前登录用户（owner=用户ID），跨设备生效
    - reset 中的键会从该层删除（回落到下一层）
    """
    user_id, role = main.resolve_identity()
    body = main.request.get_json(silent=True) or {}
    scope = body.get('scope')
    settings = body.get('settings') or {}
    reset_keys = body.get('reset') or []

    if not isinstance(settings, dict):
        return main.jsonify({'success': False, 'message': 'settings 必须是对象', 'code': 400}), 400

    if scope == 'global':
        if role < main.UserRole.ADMIN:
            return main.jsonify({'success': False, 'message': '需要管理员权限', 'code': 403}), 403
        owner = ''
    elif scope == 'user':
        if not user_id:
            return main.jsonify({'success': False, 'message': '未登录', 'code': 401}), 401
        owner = str(user_id)
    else:
        return main.jsonify({'success': False, 'message': 'scope 必须是 user 或 global', 'code': 400}), 400

    record = main.AppSetting.query.filter_by(scope=scope, owner=owner).first()
    existing = record.get_data() if record else {}
    existing.update(settings)
    # 仅保留白名单内的键
    existing = {k: v for k, v in existing.items() if k in main.SETTINGS_DEFAULTS}
    for k in (reset_keys or []):
        existing.pop(k, None)

    if record is None:
        record = main.AppSetting(scope=scope, owner=owner)
        main.db.session.add(record)
    record.set_data(existing)
    main.db.session.commit()
    main.log_operation('save settings', target=f'层={scope}', detail=f'键={list(settings.keys())}', success=True)
    return main.jsonify({'success': True, 'scope': scope, 'data': record.get_data()})

@bp.route('/api/admin/config', methods=['GET'])
@admin_required
def get_system_config():
    import main
    """获取系统配置"""
    try:
        # 从数据库或配置文件读取
        config = {
            'max_upload_size': 1024,  # MB
            'thumbnail_quality': 85,
            'auto_sync': True,
            'allow_register': False
        }
        return main.jsonify({'success': True, 'config': config})
    except Exception as e:
        return main.jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/config', methods=['POST'])
@admin_required
def update_system_config():
    import main
    """更新系统配置"""
    try:
        data = main.request.get_json()
        # 这里可以保存到数据库或配置文件
        return main.jsonify({'success': True, 'message': '配置已保存'})
    except Exception as e:
        return main.jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/config', methods=['GET'])
def get_config():
    import main
    return main.jsonify({'success': True, 'config': main.app_config})

@bp.route('/api/config', methods=['PUT'])
def update_config():
    import main
    try:
        data = main.request.get_json()
        for k, v in data.items():
            main.app_config[k] = v
        if main.save_config(main.app_config):
            main.log.maintenance('INFO', f"更新配置文件: {list(data.keys())}")
            return main.jsonify({'success': True, 'config': main.app_config})
        return main.jsonify({'success': False, 'message': '保存失败'}), 500
    except Exception as e:
        return main.jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/status')
def status():
    import main
    try:
        # 获取用户权限过滤后的视频数量
        allowed_library_ids = main.get_allowed_library_ids()
        
        if allowed_library_ids:
            # 过滤：library_id 为 NULL（主数据库的视频）或在允许的资源库中
            filtered_query = main.Video.query.filter(
                (main.Video.library_id == None) |
                (main.Video.library_id.in_(allowed_library_ids))
            ).filter(main.Video.in_trash == False)
            video_count = filtered_query.count()
        else:
            # 未登录或无权限用户只能看到主数据库的视频
            video_count = main.Video.query.filter(main.Video.library_id == None, main.Video.in_trash == False).count()
        
        return main.jsonify({
            'success': True,
            'status': 'running',
            'database': {
                'videos': video_count,
                'tags': main.Tag.query.count()
            },
            'timestamp': main.datetime.now().isoformat()
        })
    except Exception as e:
        return main.jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/services', methods=['GET'])
@admin_required
def get_services():
    import main
    """
    获取所有 dplayer 服务的状态。

    架构说明：
    - 优先通过总线向 servicemgrd 查询缓存的服务状态
    - servicemgrd 后台每 5 秒扫描一次，API 请求不应重复扫描
    - 如果总线不可用，返回静态服务列表（不调用 Windows API）
    - 注意：每个请求创建独立的 BusClient，避免多线程共享 zmq socket 的问题
    """
    import time
    bus_start = main.time.main.time()

    # 1. 优先通过总线查询 servicemgrd 缓存的状态
    # 注意：由于 zmq socket 不是线程安全的，每个请求创建独立的 BusClient
    try:
        from servicebus import BusClient
        _svc_bus = BusClient(
            f'web-svc-req-{id(main.time.main.time())}',
            host='127.0.0.1',
            rpc_port=15555,
            pub_port=15556
        )
        result = _svc_bus.call_method(
            'com.dplayer.servicemgr',
            'com.dplayer.ServiceMgr',
            'ListServices',
            {},
            timeout=3000  # 3秒超时，给 servicemgrd 足够的响应时间
        )
        bus_elapsed = (main.time.main.time() - bus_start) * 1000

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
            return main.jsonify({
                'success': True,
                'services': services,
                'source': 'bus',
                'bus_time_ms': round(bus_elapsed, 1),
            })
    except Exception as e:
        bus_elapsed = (main.time.main.time() - bus_start) * 1000
        main.log.debug('WARN', f'总线查询失败 ({bus_elapsed:.0f}ms): {e}')

    # 2. Fallback：如果总线不可用，返回静态服务列表（不调用 Windows API 扫描）
    # 这是正确的架构：不应该在 API 请求时重新扫描服务，应该信任 servicemgrd 的缓存
    main.log.debug('WARN', 'servicemgrd 不可用，返回静态服务列表')
    services = []
    for svc_name, meta in main._SERVICE_META.items():
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

    return main.jsonify({
        'success': True,
        'services': services,
        'source': 'static',  # 明确标识这是静态列表，不是实时扫描
        'warning': 'servicemgrd 不可用，状态可能不是最新的',
    })

@bp.route('/api/admin/services/<service_name>/control', methods=['POST'])
@admin_required
def control_service(service_name):
    import main
    """控制服务：start / stop / restart（通过 servicemgrd 总线）"""
    try:
        data = main.request.get_json()
        action = data.get('action', '').lower()

        if action not in ('start', 'stop', 'restart'):
            return main.jsonify({'success': False, 'message': f'无效操作: {action}'}), 400

        # 安全检查：只允许操作 dplayer- 前缀的服务
        if not service_name.startswith('dplayer-'):
            return main.jsonify({'success': False, 'message': '只允许操作 dplayer- 前缀的服务'}), 403

        # 防并发锁
        if service_name not in main._svc_control_locks:
            main._svc_control_locks[service_name] = main.threading.Lock()

        if not main._svc_control_locks[service_name].acquire(blocking=False):
            return main.jsonify({'success': False, 'message': '该服务正在操作中，请稍后再试'}), 409

        try:
            display_name = main._SERVICE_META.get(service_name, {}).get('display_name', service_name)
            action_text = {'start': '启动', 'stop': '停止', 'restart': '重启'}

            # 优先通过总线调用 servicemgrd
            if svc_mgr_bus:
                try:
                    method_name = f'{action.capitalize()}Service'
                    result = svc_mgr_bus.call_method(
                        'com.dplayer.servicemgr',
                        'com.dplayer.ServiceMgr',
                        method_name,
                        {'name': service_name}
                    )
                    if result:
                        main.log.maintenance('INFO', f'服务 {service_name} {action} via bus: {result}')
                        return main.jsonify({
                            'success': result.get('success', False),
                            'message': result.get('message', ''),
                            'action': action,
                        })
                except Exception as bus_err:
                    main.log.debug('WARN', f'总线控制服务失败，降级到直接调用: {bus_err}')

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
                            main.time.sleep(1)
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

            main.log.maintenance('INFO', f'服务 {service_name} {action} 成功（直接调用）')
            return main.jsonify({
                'success': True,
                'message': f'{display_name} {action_text[action]}成功',
                'action': action,
            })
        except Exception as e:
            error_msg = str(e)
            main.log.debug('ERROR', f'服务 {service_name} {action} 失败: {error_msg}')
            return main.jsonify({'success': False, 'message': error_msg}), 500
        finally:
            main._svc_control_locks[service_name].release()

    except Exception as e:
        main.log.debug('ERROR', f'控制服务失败: {e}')
        return main.jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/logs', methods=['GET'])
@admin_required
def get_system_logs():
    import main
    """
    获取系统日志（从 liblog 日志文件读取），支持多维筛选。

    参数:
    - type:    日志类型 (maintenance/runtime/debug/operation)，默认 maintenance
    - service: 模块/服务名筛选（可选），如 'dplayer-web'
    - level:   日志等级筛选（可选，仅对非 operation 类型有效），如 INFO/WARN/ERROR
    - user:    操作人筛选（可选，仅对 operation 类型有效），模糊匹配
    - keyword: 关键字筛选（可选），匹配 content（大小写不敏感）
    - date:    日期筛选 YYYY-MM-DD（可选），匹配该日产生的日志
    - page:    页码，默认 1
    - limit:   每页条数，默认 20
    """
    log_type = main.request.args.get('type', 'maintenance').strip().lower()
    service = main.request.args.get('service', '').strip() or None
    level = main.request.args.get('level', '').strip().upper() or None
    user = main.request.args.get('user', '').strip() or None
    keyword = main.request.args.get('keyword', '').strip() or None
    date = main.request.args.get('date', '').strip() or None
    page = main.request.args.get('page', 1, type=int)
    limit = main.request.args.get('limit', 20, type=int)

    # 验证日志类型
    valid_types = ['maintenance', 'runtime', 'debug', 'operation']
    if log_type not in valid_types:
        return main.jsonify({'success': False, 'message': f'无效的日志类型，可选: {", ".join(valid_types)}'}), 400

    # 限制每页条数范围
    limit = max(1, min(limit, 200))
    page = max(1, page)

    # 日期筛选仅保留前缀（YYYY-MM-DD）
    if date:
        date = date[:10]

    # 日志文件路径
    log_dir = main.os.path.join(main._DATA_DIR, 'logs')
    log_file = main.os.path.join(log_dir, f'{log_type}.main.log')

    if not main.os.path.exists(log_file):
        return main.jsonify({
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

            parsed = main.parse_log_line(line, log_type)
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

        return main.jsonify({
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
        main.log.debug('ERROR', f'读取日志文件失败: {e}')
        return main.jsonify({'success': False, 'message': f'读取日志失败: {str(e)}'}), 500

@bp.route('/api/admin/users', methods=['GET'])
@admin_required
def get_admin_users():
    import main
    """获取用户列表（管理员）"""
    try:
        users = main.User.query.all()
        return main.jsonify({
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
        return main.jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/users', methods=['POST'])
@admin_required
def create_admin_user():
    import main
    """创建新用户（管理员）"""
    try:
        data = main.request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        role_str = data.get('role', 'user')
        
        # 将字符串角色转换为数字
        role_map = {
            'guest': main.UserRole.GUEST,
            'user': main.UserRole.USER,
            'admin': main.UserRole.ADMIN,
            'root': main.UserRole.ROOT
        }
        role = role_map.get(role_str, main.UserRole.USER)
        
        if not username or not password:
            return main.jsonify({'success': False, 'message': '用户名和密码不能为空'}), 400
        
        if main.User.query.filter_by(username=username).first():
            return main.jsonify({'success': False, 'message': '用户名已存在'}), 400
        
        user = main.User(username=username, role=role)
        user.set_password(password)
        main.db.session.add(user)
        main.db.session.commit()
        main.log.maintenance('INFO', f"创建用户: {username} (角色: {user.role_name})")
        main.log_operation('create user', target=username, detail=f'角色={user.role_name}', success=True)
        
        return main.jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'role': user.role,
                'role_name': user.role_name
            }
        })
    except Exception as e:
        main.db.session.rollback()
        return main.jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/users/<int:user_id>', methods=['PUT'])
@admin_required
def update_admin_user(user_id):
    import main
    """更新用户信息（管理员）"""
    try:
        user = main.User.query.get_or_404(user_id)
        data = main.request.get_json()

        # 更新用户名
        if 'username' in data:
            new_username = data['username'].strip()
            if not new_username:
                return main.jsonify({'success': False, 'message': '用户名不能为空'}), 400
            # 检查用户名是否已被其他用户占用
            existing_user = main.User.query.filter_by(username=new_username).first()
            if existing_user and existing_user.id != user_id:
                return main.jsonify({'success': False, 'message': '用户名已存在'}), 400
            user.username = new_username

        # 更新角色
        if 'role' in data:
            role_map = {
                'guest': main.UserRole.GUEST,
                'user': main.UserRole.USER,
                'admin': main.UserRole.ADMIN,
                'root': main.UserRole.ROOT
            }
            user.role = role_map.get(data['role'], main.UserRole.USER)

        # 更新密码（如果提供了）
        if data.get('password'):
            user.set_password(data['password'])

        main.db.session.commit()
        main.log.maintenance('INFO', f"更新用户信息: {user.username} (ID: {user_id})")
        main.log_operation('update user', target=user.username, detail=f'角色={user.role_name}', success=True)

        return main.jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'role': user.role,
                'role_name': user.role_name
            }
        })
    except Exception as e:
        main.db.session.rollback()
        main.log.debug('ERROR', f"更新用户信息失败: {user_id}, {e}")
        return main.jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_admin_user(user_id):
    import main
    """删除用户（管理员）"""
    try:
        user = main.User.query.get_or_404(user_id)
        if user.id == main.g.user_id:
            return main.jsonify({'success': False, 'message': '不能删除当前登录用户'}), 400
        main.db.session.delete(user)
        main.db.session.commit()
        main.log.maintenance('INFO', f"删除用户: {user.username} (ID: {user_id})")
        main.log_operation('delete user', target=user.username, success=True)
        return main.jsonify({'success': True, 'message': '用户已删除'})
    except Exception as e:
        main.db.session.rollback()
        main.log.debug('ERROR', f"删除用户失败: {user_id}, {e}")
        return main.jsonify({'success': False, 'message': str(e)}), 500
