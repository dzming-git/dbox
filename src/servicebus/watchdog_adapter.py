# -*- coding: utf-8 -*-
"""
WatchdogService - 服务看门狗（健康巡检 + 自愈 + 告警）

按固定间隔：
  1. 通过服务总线 ``Ping`` 各个已注册服务（满足「定时 ping 各个服务的 bus」）；
  2. 结合 Windows 服务状态（com.dbox.servicemgr 提供）判断每个 dbox 服务是否存活；
  3. 若某服务「长时间 ping 不通 / 非 RUNNING」则自动重启它；
  4. 若连续重启多次仍失败，则升级为告警（critical）并广播信号；
  5. 对外暴露总体健康灯数据，供管理后台聚合展示。

总线服务定义：

  Service:        com.dbox.watchdog
  Interface:      com.dbox.Watchdog
  Object Path:    /com/dbox/watchdog

  Methods:
    GetHealth()      → {overall_status, services, alerts, last_check, uptime, config}
    GetStatus()      → 与 GetHealth 同（兼容命名）
    RestartService(name)  → 手动重启某个服务（{success, message}）
    AcknowledgeAlert(name)→ 确认/消除某个服务的告警（重置重启计数）

  Signals:
    HealthChanged(overall_status, critical)  → 总体健康状态变化时广播
    ServiceRestarted(name, restart_count)    → 看门狗自动重启了某服务
    ServiceAlert(name, message, restart_count) → 重启耗尽，升级为告警

安全边界：
  dbox-bus / dbox-servicemgr / dbox-watchdog 属于看门狗自身依赖的基础设施，
  不在「自动重启」范围内（避免看门狗自杀式重启总线导致自身失联）；
  它们若异常只会产生告警，交由管理员手动处理。
"""

import os
import sys
import time
import threading
import logging
from typing import Dict, Any, List, Optional

from .service_base import BaseDBusService

# 日志：写到 data/logs/watchdog.log（与 NSSM 的 stdout/stderr 日志互补）
try:
    _LOG_DIR = os.path.join(
        os.environ.get('DBOX_DATA_DIR')
        or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'data', 'logs'
    )
except Exception:
    _LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'data', 'logs')

os.makedirs(_LOG_DIR, exist_ok=True)
_log = logging.getLogger('dbox.watchdog')
if not _log.handlers:
    _log.setLevel(logging.INFO)
    _fh = logging.FileHandler(os.path.join(_LOG_DIR, 'watchdog.log'), encoding='utf-8')
    _fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    _log.addHandler(_fh)
    _log.addHandler(logging.StreamHandler())


# ============ 监控的服务清单 ============
# win  : Windows 服务名（重启目标）
# bus  : 该服务在总线上的 Bus Name（用于 Ping；为 None 时仅按 Windows 状态判断）
# display: 展示名
DEFAULT_MONITORED = [
    {'win': 'dbox-bus',        'bus': None,               'display': '服务总线'},
    {'win': 'dbox-servicemgr', 'bus': 'com.dbox.servicemgr', 'display': '服务管理'},
    {'win': 'dbox-thumbnail',  'bus': 'com.dbox.thumbnaild', 'display': '缩略图'},
    {'win': 'dbox-systemd',    'bus': 'com.dbox.systemd',   'display': '系统监控'},
    {'win': 'dbox-resource',   'bus': 'com.dbox.resourced', 'display': '资源管理'},
    {'win': 'dbox-userd',      'bus': 'com.dbox.userd',     'display': '用户'},
    {'win': 'dbox-searchd',    'bus': 'com.dbox.searchd',   'display': '搜索'},
    {'win': 'dbox-collectiond','bus': 'com.dbox.collectiond', 'display': '合集'},
    {'win': 'dbox-historyd',   'bus': 'com.dbox.historyd',  'display': '历史'},
    {'win': 'dbox-web',        'bus': None,               'display': 'Web API'},
    {'win': 'dbox-webui',      'bus': None,               'display': 'WebUI'},
    {'win': 'dbox-downloader', 'bus': None,               'display': '下载器'},
    {'win': 'dbox-scheduler',   'bus': None,               'display': '脚本调度器'},
]

# 看门狗自身依赖的基础设施，禁止自动重启（只告警）
AUTO_RESTART_EXCLUDED = {'dbox-bus', 'dbox-servicemgr', 'dbox-watchdog'}

# 健康 url（用于 Windows 服务层 HTTP 探活，可选）
_KNOWN_HEALTH_URLS = {
    'dbox-webui': 'http://localhost:5173',
    'dbox-downloader': 'http://127.0.0.1:8092/api/health',
}


class WatchdogService(BaseDBusService):
    """看门狗服务 — 周期性健康检查 + 自愈重启 + 告警。"""

    BUS_NAME = 'com.dbox.watchdog'
    INTERFACES = ['com.dbox.Watchdog']
    OBJECT_PATH = '/com/dbox/watchdog'

    def __init__(self,
                 host: str = '127.0.0.1',
                 rpc_port: int = 15555,
                 pub_port: int = 15556,
                 check_interval: int = 15,
                 ping_timeout: int = 2000,
                 fail_threshold: int = 3,
                 restart_grace: int = 45,
                 max_restarts: int = 3):
        """
        Args:
            check_interval:  巡检间隔（秒）
            ping_timeout:    单次总线 Ping 超时（毫秒）
            fail_threshold:   连续多少次判定不健康后才重启
            restart_grace:   重启后多少秒内不计入失败（给服务启动时间）
            max_restarts:    连续重启达到此次数仍失败则升级为告警
        """
        super().__init__(host, rpc_port, pub_port)
        self._check_interval = check_interval
        self._ping_timeout = ping_timeout
        self._fail_threshold = fail_threshold
        self._restart_grace = restart_grace
        self._max_restarts = max_restarts

        self._lock = threading.Lock()
        # 监控状态表：win_name -> state dict
        self._states: Dict[str, Dict[str, Any]] = {}
        for item in DEFAULT_MONITORED:
            self._states[item['win']] = {
                'win': item['win'],
                'bus': item.get('bus'),
                'display': item.get('display', item['win']),
                'status': 'unknown',        # healthy / down / restarting / critical / unknown
                'windows_status': 'unknown',
                'health_status': 'unknown', # servicemgr 探活结果：healthy/unhealthy/timeout/offline/unknown
                'bus_reachable': None,      # True/False/None(无 bus)
                'consecutive_failures': 0,
                'restart_count': 0,
                'last_success': None,
                'last_failure': None,
                'last_restart': None,
                'last_error': None,
                'alerted': False,
            }

        self._alerts: List[Dict[str, Any]] = []
        self._last_check = None
        self._last_overall = 'unknown'
        self._start_time = time.time()
        self._running = False
        self._watch_thread: Optional[threading.Thread] = None
        # 单一持久化探测客户端（在巡检线程内复用，避免每次 Ping 都新建 ZMQ Context 导致超时）
        self._probe: Optional[Any] = None

    # ============ 生命周期 ============

    def start(self, block: bool = False):
        super().start(block=block)
        self._running = True
        self._watch_thread = threading.Thread(
            target=self._watch_loop, daemon=True, name='watchdog-loop')
        self._watch_thread.start()
        _log.info('看门狗已启动：巡检间隔=%ds, 失败阈值=%d, 最大重启=%d',
                  self._check_interval, self._fail_threshold, self._max_restarts)

    def stop(self):
        self._running = False
        super().stop()

    # ============ 总线客户端 ============
    # 每次巡检用「一次性」BusClient（创建 -> 完成本轮所有调用 -> 关闭）。
    # 早期版本复用常驻探针客户端(self._probe)，但在常驻进程里该客户端会出现
    # 静默失效（收到 unknown method / 收不到回复），而新建客户端则稳定可用；
    # 故改为每轮新建，避免常驻客户端状态污染。

    def _new_bus_client(self):
        try:
            from .client import BusClient
            return BusClient('com.dbox.watchdog.cycle', host=self._host,
                             rpc_port=self._rpc_port, pub_port=self._pub_port)
        except Exception as e:
            _log.error('探测客户端创建失败: %s', e)
            return None

    # ============ 巡检主循环 ============

    def _watch_loop(self):
        # 启动后先等一会，让总线/各服务就绪
        time.sleep(min(self._check_interval, 10))
        while self._running:
            try:
                self._do_check()
            except Exception as e:
                _log.exception('巡检异常: %s', e)
            # 用分段 sleep 以便尽快响应 stop()
            for _ in range(max(1, self._check_interval)):
                if not self._running:
                    break
                time.sleep(1)

    def _do_check(self):
        states_snapshot = self._query_service_states()
        now = time.time()
        overall_changed = False

        with self._lock:
            for win_name, st in self._states.items():
                snap = states_snapshot.get(win_name, {})
                win_status = snap.get('windows_status', 'unknown')
                bus_reachable = snap.get('bus_reachable')   # True/False/None
                health_status = snap.get('health_status', 'unknown')
                st['windows_status'] = win_status
                st['bus_reachable'] = bus_reachable
                st['health_status'] = health_status

                # 是否处于重启宽限期
                in_grace = (st['last_restart'] is not None
                            and (now - st['last_restart']) < self._restart_grace)

                reachable = self._is_reachable(win_status, bus_reachable, health_status)
                if reachable:
                    st['last_success'] = now
                    st['last_error'] = None
                    if st['consecutive_failures'] > 0:
                        st['consecutive_failures'] = 0
                    # 恢复健康
                    if st['status'] in ('down', 'restarting', 'critical'):
                        _log.info('服务恢复健康: %s (was %s)', win_name, st['status'])
                    if st['status'] != 'healthy':
                        st['status'] = 'healthy'
                else:
                    # 不可达
                    if in_grace:
                        st['status'] = 'restarting'
                        st['last_failure'] = now
                        continue
                    st['last_failure'] = now
                    st['consecutive_failures'] += 1
                    # 优先用服务管理器探活给出的明确失败原因（如下载器 HTTP 探活失败）
                    if health_status in ('unhealthy', 'timeout', 'offline'):
                        reason = 'health check failed: %s' % health_status
                    else:
                        reason = snap.get('last_error') or ('windows_status=%s' % win_status)
                    st['last_error'] = reason

                    if st['consecutive_failures'] >= self._fail_threshold:
                        if st['restart_count'] < self._max_restarts and \
                                win_name not in AUTO_RESTART_EXCLUDED:
                            # 触发自动重启
                            ok, msg = self._restart_windows_service(win_name)
                            st['restart_count'] += 1
                            st['last_restart'] = now
                            st['consecutive_failures'] = 0
                            st['status'] = 'restarting'
                            if ok:
                                _log.warning('看门狗已自动重启 %s (第%d次): %s',
                                             win_name, st['restart_count'], msg)
                                self.emit_signal('com.dbox.Watchdog', 'ServiceRestarted',
                                                 {'name': win_name,
                                                  'restart_count': st['restart_count'],
                                                  'message': msg})
                            else:
                                _log.error('看门狗重启 %s 失败: %s', win_name, msg)
                        else:
                            # 重启耗尽 / 基础设施禁止自动重启 → 升级告警
                            if st['status'] != 'critical':
                                st['status'] = 'critical'
                                overall_changed = True
                            if not st['alerted']:
                                st['alerted'] = True
                                alert = {
                                    'name': win_name,
                                    'display': st['display'],
                                    'message': '服务持续不可用，已尝试重启 %d 次仍失败'
                                               % st['restart_count'],
                                    'restart_count': st['restart_count'],
                                    'time': time.time(),
                                }
                                self._alerts.append(alert)
                                _log.error('服务告警(CRITICAL): %s — %s', win_name, alert['message'])
                                self.emit_signal('com.dbox.Watchdog', 'ServiceAlert',
                                                 alert)
                    else:
                        if st['status'] != 'down':
                            st['status'] = 'down'
                        _log.warning('服务不健康(待重启): %s — %s (连续%d次)',
                                     win_name, reason, st['consecutive_failures'])

            # 计算总体状态
            overall = self._compute_overall()
            self._last_check = now
            if overall != self._last_overall:
                overall_changed = True
            if overall_changed:
                self._last_overall = overall
                self.emit_signal('com.dbox.Watchdog', 'HealthChanged', {
                    'overall_status': overall,
                    'critical': [s['win'] for s in self._states.values()
                                 if s['status'] == 'critical'],
                })
                _log.info('总体健康状态变更 → %s', overall)

    @staticmethod
    def _is_reachable(win_status: str, bus_reachable, health_status=None) -> bool:
        if win_status not in ('RUNNING', 'PAUSED'):
            return False
        # 有 bus 的服务以 bus ping 为准
        if bus_reachable is True:
            return True
        if bus_reachable is False:
            return False
        # None：无 bus 服务 / 服务在线但不支持 Ping（旧版本未加载新代码）
        # → 若服务管理器已通过 HTTP 探活明确判定该服务不可达（如下载器
        #   进程虽 RUNNING 但 /api/health 不通），同样视为不可达，避免汇总
        #   状态误报「全部正常」。
        if health_status in ('unhealthy', 'timeout', 'offline'):
            return False
        return True

    def _compute_overall(self) -> str:
        statuses = [s['status'] for s in self._states.values()]
        if any(s == 'critical' for s in statuses):
            return 'critical'
        if any(s in ('down', 'restarting') for s in statuses):
            return 'degraded'
        if all(s == 'healthy' for s in statuses):
            return 'healthy'
        return 'degraded'

    # ============ 状态采集 ============

    def _query_service_states(self) -> Dict[str, Dict[str, Any]]:
        """采集每个被监控服务的可达状态。优先走 servicemgr 总线，失败则直查。
        除了 Windows 状态 / 总线可达性，还会带上服务管理器的 HTTP 探活结果
        （health_status），使汇总状态能反映「进程在跑但服务实际不可用」的情况。
        """
        result: Dict[str, Dict[str, Any]] = {}
        client = self._new_bus_client()
        try:
            # 先尝试通过 servicemgr 拿 Windows 状态 + 探活结果
            svc_states = self._query_via_servicemgr(client) if client else {}
            if not svc_states:
                svc_states = self._query_win32_direct()
            for win_name, st in self._states.items():
                snap = svc_states.get(win_name, {})
                entry = {
                    'windows_status': snap.get('windows_status', 'unknown'),
                    'health_status': snap.get('health_status', 'unknown'),
                }
                bus_name = st.get('bus')
                if bus_name and client:
                    reachable, err = self._ping_bus(client, bus_name)
                    entry['bus_reachable'] = reachable
                    if reachable is False:
                        entry['last_error'] = 'bus ping 失败: %s' % (err or 'timeout')
                else:
                    entry['bus_reachable'] = None
                result[win_name] = entry
        finally:
            if client:
                try:
                    client.stop()
                except Exception:
                    pass
        return result

    def _query_via_servicemgr(self, client) -> Dict[str, Dict[str, str]]:
        """经服务管理器总线取 {name: {windows_status, health_status}}。"""
        if not client:
            return {}
        try:
            resp = client.call_method(
                'com.dbox.servicemgr', 'com.dbox.ServiceMgr', 'ListServices',
                {}, timeout=3000)
            if not resp or 'services' not in resp:
                return {}
            out = {}
            for svc in resp['services']:
                out[svc.get('name')] = {
                    'windows_status': svc.get('status', 'unknown'),
                    'health_status': svc.get('health_status', 'unknown'),
                }
            return out
        except Exception as e:
            _log.debug('通过 servicemgr 查询失败，回退直查: %s', e)
            return {}

    def _query_win32_direct(self) -> Dict[str, Dict[str, str]]:
        """直查 Windows 服务状态；对已知 health_url 的服务额外做 HTTP 探活。"""
        status_map = {
            1: 'STOPPED', 2: 'START_PENDING', 3: 'STOP_PENDING',
            4: 'RUNNING', 5: 'CONTINUE_PENDING', 6: 'PAUSE_PENDING',
            7: 'PAUSED',
        }
        out = {}
        try:
            import win32service
            scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
            try:
                for win_name in self._states:
                    health = 'unknown'
                    try:
                        svc = win32service.OpenService(
                            scm, win_name, win32service.SERVICE_QUERY_STATUS)
                        st = win32service.QueryServiceStatus(svc)[1]
                        win = status_map.get(st, 'UNKNOWN(%d)' % st)
                        win32service.CloseServiceHandle(svc)
                    except Exception:
                        win = 'not_found'
                    # 进程在跑的服务，额外验证其 HTTP 探活端点是否真可用
                    if win == 'RUNNING' and win_name in _KNOWN_HEALTH_URLS:
                        health = self._http_health(_KNOWN_HEALTH_URLS[win_name])
                    out[win_name] = {'windows_status': win, 'health_status': health}
            finally:
                win32service.CloseServiceHandle(scm)
        except Exception as e:
            _log.debug('直查 win32 失败: %s', e)
        return out

    @staticmethod
    def _http_health(url: str) -> str:
        """对已知 health url 发起 HTTP 探活，返回 health_status 字符串。"""
        import requests
        try:
            resp = requests.get(url, timeout=1.5)
            return 'healthy' if resp.status_code == 200 else 'unhealthy'
        except requests.exceptions.Timeout:
            return 'timeout'
        except Exception:
            return 'offline'

    def _ping_bus(self, client, bus_name: str):
        """
        对某个总线服务发起 Ping。

        返回 (status, err)：
          True   : 收到 pong，服务总线存活
          False  : 超时/连接异常，服务可能挂起（视为不可达）
          None   : 服务在线但不支持 Ping（如旧版本代码未加载新基类），
                   交由 Windows 状态判定，不计入总线失败
        """
        if not client:
            _log.warning('探测客户端未就绪，跳过 %s 的 Ping', bus_name)
            return None, '探测客户端未就绪'
        try:
            resp = client.call_method(
                bus_name, bus_name.split('.')[-1] if '.' in bus_name else bus_name,
                'Ping', {}, timeout=self._ping_timeout)
            _log.debug('ping %s -> %s', bus_name, str(resp)[:200])
            if resp and resp.get('success'):
                return True, None
            if resp and '_error' in resp:
                err = str(resp.get('_error'))
                # 旧版本服务未实现 Ping：不算总线失败，回落到 Windows 状态
                if '未知方法' in err or 'unknown method' in err.lower():
                    return None, err
                return False, err
            # resp 为 None：超时（服务可能挂起）
            return False, 'ping 超时'
        except Exception as e:
            _log.debug('ping %s 异常: %s', bus_name, e)
            return False, str(e)

    # ============ 重启 ============

    def _restart_windows_service(self, win_name: str):
        """重启 Windows 服务。优先用 win32service，失败则用 servicemgr 总线。"""
        ok, msg = self._restart_via_win32(win_name)
        if ok:
            return ok, msg
        return self._restart_via_bus(win_name)

    def _restart_via_win32(self, win_name: str):
        try:
            import win32service
            import win32con
            scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
            try:
                svc = win32service.OpenService(
                    scm, win_name,
                    win32service.SERVICE_START | win32service.SERVICE_STOP
                    | win32service.SERVICE_QUERY_STATUS)
                try:
                    status = win32service.QueryServiceStatus(svc)
                    if status[1] != win32service.SERVICE_STOPPED:
                        win32service.ControlService(svc, win32service.SERVICE_CONTROL_STOP)
                        # 等待停止
                        for _ in range(10):
                            if win32service.QueryServiceStatus(svc)[1] == \
                                    win32service.SERVICE_STOPPED:
                                break
                            time.sleep(0.5)
                    win32service.StartService(svc, None)
                    return True, '已发送重启命令(win32)'
                finally:
                    win32service.CloseServiceHandle(svc)
            finally:
                win32service.CloseServiceHandle(scm)
        except Exception as e:
            return False, 'win32 重启失败: %s' % e

    def _restart_via_bus(self, win_name: str):
        try:
            if self._probe:
                resp = self._probe.call_method(
                    'com.dbox.servicemgr', 'com.dbox.ServiceMgr', 'RestartService',
                    {'name': win_name}, timeout=8000)
            else:
                from .client import BusClient
                client = BusClient('com.dbox.watchdog.restart', host=self._host,
                                   rpc_port=self._rpc_port, pub_port=self._pub_port)
                try:
                    resp = client.call_method(
                        'com.dbox.servicemgr', 'com.dbox.ServiceMgr', 'RestartService',
                        {'name': win_name}, timeout=8000)
                finally:
                    client.stop()
            if resp and resp.get('success'):
                return True, '已发送重启命令(bus)'
            return False, str(resp)
        except Exception as e:
            return False, 'bus 重启失败: %s' % e

    # ============ 总线方法 ============

    def on_method_get_health(self, params: Dict[str, Any] = None) -> Dict:
        """返回总体健康 + 各服务详情 + 告警。"""
        with self._lock:
            services = []
            for st in self._states.values():
                services.append({
                    'name': st['win'],
                    'display': st['display'],
                    'bus_name': st['bus'],
                    'status': st['status'],
                    'windows_status': st['windows_status'],
                    'health_status': st['health_status'],
                    'bus_reachable': st['bus_reachable'],
                    'consecutive_failures': st['consecutive_failures'],
                    'restart_count': st['restart_count'],
                    'last_success': st['last_success'],
                    'last_failure': st['last_failure'],
                    'last_restart': st['last_restart'],
                    'alerted': st['alerted'],
                    'last_error': st['last_error'],
                })
            alerts = list(self._alerts)
            overall = self._compute_overall()
        return {
            'overall_status': overall,
            'services': services,
            'alerts': alerts,
            'last_check': self._last_check,
            'uptime': round(time.time() - self._start_time, 1),
            'config': {
                'check_interval': self._check_interval,
                'ping_timeout': self._ping_timeout,
                'fail_threshold': self._fail_threshold,
                'restart_grace': self._restart_grace,
                'max_restarts': self._max_restarts,
                'auto_restart_excluded': list(AUTO_RESTART_EXCLUDED),
            },
        }

    def on_method_get_status(self, params: Dict[str, Any] = None) -> Dict:
        return self.on_method_get_health(params)

    def on_method_restart_service(self, params: Dict[str, Any]) -> Dict:
        """手动重启指定服务（同时清空其告警与重启计数）。"""
        name = params.get('name', '')
        if not name:
            return {'success': False, 'message': '缺少 name 参数'}
        with self._lock:
            st = self._states.get(name)
            if st is None:
                return {'success': False, 'message': '未知服务: %s' % name}
            st['alerted'] = False
            st['restart_count'] = 0
            st['consecutive_failures'] = 0
        ok, msg = self._restart_windows_service(name)
        return {'success': ok, 'message': msg}

    def on_method_acknowledge_alert(self, params: Dict[str, Any]) -> Dict:
        """确认告警：清除该服务的告警标记与重启计数，允许看门狗重新尝试。"""
        name = params.get('name', '')
        with self._lock:
            st = self._states.get(name)
            if st is None:
                return {'success': False, 'message': '未知服务: %s' % name}
            st['alerted'] = False
            st['restart_count'] = 0
            st['consecutive_failures'] = 0
            if st['status'] == 'critical':
                st['status'] = 'down'
            # 从告警列表移除
            self._alerts = [a for a in self._alerts if a.get('name') != name]
        return {'success': True, 'message': '告警已确认: %s' % name}
