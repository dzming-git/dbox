# -*- coding: utf-8 -*-
"""
BusServiceMgrAdapter - 服务管理总线适配器

将 Windows 服务管理能力（win32service/psutil）暴露到服务总线上，
供其他服务（尤其是 web）通过总线查询，无需直接调用 Windows API。

总线服务定义：

  Service:        com.dbox.servicemgr
  Interface:      com.dbox.ServiceMgr
  Object Path:    /com/dbox/servicemgr

  Methods:
    ListServices()
      → {services: [{name, display_name, status, pid, memory_mb, cpu_percent, port, health_status}, ...]}

    GetService(name)
      → {name, display_name, status, pid, memory_mb, cpu_percent, port, health_status}

    ReloadServices()
      → {count: int}

    StartService(name)
      → {success: bool, message: str}

    StopService(name)
      → {success: bool, message: str}

    RestartService(name)
      → {success: bool, message: str}

使用方式：

    adapter = BusServiceMgrAdapter(host='127.0.0.1', rpc_port=15555, pub_port=15556)
    adapter.start()
"""

import os
import sys
import time
import threading
from typing import Dict, Any, List, Optional

from .service_base import BaseDBusService

# Windows 服务状态码映射
_WIN32_SVC_STATUS = {
    1: 'STOPPED',
    2: 'START_PENDING',
    3: 'STOP_PENDING',
    4: 'RUNNING',
    5: 'CONTINUE_PENDING',
    6: 'PAUSE_PENDING',
    7: 'PAUSED',
}

# 服务元信息（静态配置，非 NSSM 扫描得到）
_SERVICE_META = {
    'dbox-web': {
        'display_name': 'Dbox Web服务',
        'description': 'Web API 服务 - 视频管理、用户认证等',
        'health_url': None,
        'port': 8080,
    },
    'dbox-bus': {
        'display_name': 'Dbox 服务总线',
        'description': '服务总线代理，所有内部服务通信中枢',
        'health_url': None,
        'port': None,
    },
    'dbox-servicemgr': {
        'display_name': 'Dbox 服务管理',
        'description': '服务管理守护进程，定期扫描 dbox-* 服务状态',
        'health_url': None,
        'port': None,
    },
    'dbox-thumbnail': {
        'display_name': 'Dbox 缩略图服务',
        'description': '视频缩略图生成微服务（通过服务总线）',
        'health_url': None,
        'port': None,
    },
    'dbox-webui': {
        'display_name': 'Dbox WebUI服务',
        'description': 'Vue3 前端界面',
        'health_url': 'http://localhost:5173',
        'port': 5173,
    },
    'dbox-downloader': {
        'display_name': 'Dbox 资源下载器',
        'description': '独立进程：外部脚本 / 下载器服务（与主服务解耦，崩溃不影响主服务）',
        'health_url': 'http://127.0.0.1:8092/api/health',
        'port': 8092,
    },
    'dbox-watchdog': {
        'display_name': 'Dbox 服务看门狗',
        'description': '服务看门狗 - 定时 ping 各服务总线，不可达则自动重启，多次失败告警',
        'health_url': None,
        'port': None,
    },
    'dbox-resource': {
        'display_name': 'Dbox 资源管理服务',
        'description': '资源管理微服务 - 资源库扫描、文件监控、索引管理',
        'health_url': None,
        'port': None,
    },
    'dbox-userd': {
        'display_name': 'Dbox 用户管理服务',
        'description': '用户管理微服务 - 用户增删改查与认证',
        'health_url': None,
        'port': None,
    },
    'dbox-systemd': {
        'display_name': 'Dbox 系统监控服务',
        'description': '系统监控微服务 - 监控 CPU、内存、磁盘等系统资源',
        'health_url': None,
        'port': None,
    },
    'dbox-historyd': {
        'display_name': 'Dbox 播放历史服务',
        'description': '播放历史微服务 - 记录播放进度、支持断点续播',
        'health_url': None,
        'port': None,
    },
    'dbox-collectiond': {
        'display_name': 'Dbox 收藏夹服务',
        'description': '收藏夹微服务 - 收藏视频、组织播放列表',
        'health_url': None,
        'port': None,
    },
    'dbox-searchd': {
        'display_name': 'Dbox 搜索服务',
        'description': '搜索微服务 - 全文搜索、视频标签和描述检索',
        'health_url': None,
        'port': None,
    },
    'dbox-scheduler': {
        'display_name': 'Dbox 定时任务服务',
        'description': '通用脚本轮询调度器 - 按各脚本 manifest 声明的 interval 周期执行',
        'health_url': None,
        'port': None,
    },
}

# 即使未注册为 Windows 服务也要出现在服务列表中的服务
# （如以独立进程方式运行的下载器）；其余服务仍以实际扫描结果为准。
_ALWAYS_LIST_SERVICES = ('dbox-downloader',)


class BusServiceMgrAdapter(BaseDBusService):
    """
    服务管理总线适配器

    定期扫描 Windows NSSM 服务，缓存状态，
    通过总线暴露查询接口。
    """

    BUS_NAME = 'com.dbox.servicemgr'
    INTERFACES = ['com.dbox.ServiceMgr']
    OBJECT_PATH = '/com/dbox/servicemgr'

    def __init__(self,
                 host: str = '127.0.0.1',
                 rpc_port: int = 15555,
                 pub_port: int = 15556,
                 scan_interval: int = 5):
        """
        Args:
            host: 总线地址
            rpc_port: 总线 RPC 端口
            pub_port: 总线 PUB 端口
            scan_interval: 服务状态扫描间隔（秒）
        """
        super().__init__(host, rpc_port, pub_port)
        self._scan_interval = scan_interval
        self._lock = threading.Lock()
        self._cached_services: Dict[str, Dict] = {}
        self._scan_thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        """启动适配器和后台扫描"""
        super().start()
        self._running = True
        self._scan_thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._scan_thread.start()

    def stop(self):
        """停止适配器和后台扫描"""
        self._running = False
        super().stop()

    def _scan_loop(self):
        """后台扫描循环"""
        # 启动时立即扫描一次
        self._do_scan()

        while self._running:
            time.sleep(self._scan_interval)
            if self._running:
                self._do_scan()

    def _do_scan(self):
        """执行一次服务扫描"""
        try:
            service_names = self._scan_nssm_services()
            # 合并静态元信息中定义的服务（如以独立进程方式运行的下载器），
            # 保证它们始终出现在服务列表中，即使未注册为 Windows 服务。
            merged = list(service_names)
            for name in _ALWAYS_LIST_SERVICES:
                if name not in merged:
                    merged.append(name)
            for name in merged:
                try:
                    info = self._get_service_info(name)
                    with self._lock:
                        self._cached_services[name] = info
                except Exception:
                    pass
        except Exception:
            pass

    def _scan_nssm_services(self) -> List[str]:
        """
        扫描所有 dbox- 前缀的 Windows 服务
        优先使用 win32service API，失败时 fallback 到 sc query 命令
        """
        # 方法1: win32service API（需要足够的权限）
        try:
            import win32service
            scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
            try:
                services = win32service.EnumServicesStatus(
                    scm, win32service.SERVICE_WIN32, win32service.SERVICE_STATE_ALL
                )
                result = [s[0] for s in services if s[0].startswith('dbox-')]
                if result:
                    return result
            finally:
                win32service.CloseServiceHandle(scm)
        except Exception:
            pass

        # 方法2: sc query 命令（权限要求较低）
        try:
            import subprocess
            # Windows 上 sc 是 cmd 内置命令，需要 shell=True 才能正确执行
            result = subprocess.run(
                'sc query type= service state= all',
                capture_output=True, text=True, timeout=30, shell=True
            )
            if result.returncode == 0:
                dbox_svcs = []
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line.startswith('SERVICE_NAME:'):
                        svc_name = line.split(':', 1)[1].strip()
                        if svc_name.startswith('dbox-'):
                            dbox_svcs.append(svc_name)
                if dbox_svcs:
                    return dbox_svcs
        except Exception:
            pass

        # 方法3: 直接探测已知服务名
        known_services = [
            'dbox-web', 'dbox-bus', 'dbox-servicemgr', 'dbox-thumbnail',
            'dbox-webui', 'dbox-resource', 'dbox-userd', 'dbox-systemd',
            'dbox-historyd', 'dbox-collectiond', 'dbox-searchd',
            'dbox-downloader', 'dbox-watchdog', 'dbox-scheduler',
        ]
        verified = []
        try:
            import win32service
            scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
            for svc_name in known_services:
                try:
                    hs = win32service.OpenService(scm, svc_name, win32service.SERVICE_QUERY_STATUS)
                    win32service.CloseServiceHandle(hs)
                    verified.append(svc_name)
                except Exception:
                    pass
            win32service.CloseServiceHandle(scm)
        except Exception:
            pass

        if verified:
            return verified

        # 最终 fallback: 返回静态元信息中定义的所有服务名
        # （包括未注册为 Windows 服务、以独立进程方式运行的下载器等）
        return list(_SERVICE_META.keys())

    def _get_service_info(self, service_name: str) -> Dict[str, Any]:
        """获取单个服务的详细信息"""
        meta = _SERVICE_META.get(service_name, {})
        info = {
            'name': service_name,
            'display_name': meta.get('display_name', service_name),
            'description': meta.get('description', ''),
            'status': 'unknown',
            'pid': None,
            'memory_mb': None,
            'cpu_percent': None,
            'port': meta.get('port'),
            'health_status': 'unknown',
            'latency_ms': None,
        }

        # 1. Windows 服务状态
        try:
            import win32service
            scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
            try:
                svc = win32service.OpenService(
                    scm, service_name, win32service.SERVICE_QUERY_STATUS
                )
                status_info = win32service.QueryServiceStatus(svc)
                win32service.CloseServiceHandle(svc)
                state_code = status_info[1]
                info['status'] = _WIN32_SVC_STATUS.get(state_code, f'UNKNOWN({state_code})')
            finally:
                win32service.CloseServiceHandle(scm)
        except Exception:
            info['status'] = 'not_found'

        # 2. PID / CPU / 内存（仅针对 RUNNING/PAUSED 状态）
        if info['status'] not in ('RUNNING', 'PAUSED'):
            return info

        port = info['port']
        if port:
            try:
                import psutil
                for conn in psutil.net_connections(kind='inet'):
                    if (conn.laddr and conn.laddr.port == port
                            and conn.status == psutil.CONN_LISTEN):
                        info['pid'] = conn.pid
                        break
            except Exception:
                pass

        if not info['pid']:
            try:
                import psutil
                for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                    try:
                        if proc.info['name'] and proc.info['name'].lower() == 'python.exe':
                            cmdline = proc.info.get('cmdline') or []
                            cmdline_str = ' '.join(cmdline).lower()
                            if 'dbox' in cmdline_str:
                                svc_key = service_name.replace('dbox-', '')
                                if svc_key in cmdline_str:
                                    info['pid'] = proc.info['pid']
                                    break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except Exception:
                pass

        if info['pid']:
            try:
                import psutil
                proc = psutil.Process(info['pid'])
                mem_info = proc.memory_info()
                info['memory_mb'] = round(mem_info.rss / (1024 * 1024), 1)
                # 使用 interval=None 非阻塞模式，避免每个服务阻塞 0.3 秒
                # CPU 使用率会在下一次调用时计算（基于时间差）
                try:
                    info['cpu_percent'] = proc.cpu_percent(interval=None)
                except Exception:
                    info['cpu_percent'] = None
            except Exception:
                info['pid'] = None

        # 3. 健康检查
        health_url = meta.get('health_url')
        if health_url:
            info['health_status'], info['latency_ms'] = self._check_http_health(health_url)
        elif info['status'] == 'RUNNING':
            info['health_status'] = 'healthy'

        return info

    def _check_http_health(self, url: str) -> tuple:
        """HTTP 健康检查"""
        import requests
        try:
            start = time.time()
            resp = requests.get(url, timeout=1.5)  # 1.5秒超时，加快降级
            latency = (time.time() - start) * 1000
            if resp.status_code == 200:
                return ('healthy', round(latency, 1))
            return ('unhealthy', round(latency, 1))
        except requests.exceptions.Timeout:
            return ('timeout', None)
        except Exception:
            return ('offline', None)

    # ============ 总线方法 ============

    def on_method_list_services(self, params: Dict[str, Any]) -> Dict:
        """
        列出所有 dbox 服务及其当前状态。

        Returns:
            {services: [{name, display_name, status, pid, memory_mb, cpu_percent, port, health_status, latency_ms}, ...]}
        """
        with self._lock:
            services = list(self._cached_services.values())
        return {'services': services}

    def on_method_get_service(self, params: Dict[str, Any]) -> Dict:
        """
        获取单个服务详情。

        Args (params):
            name: str - 服务名（如 'dbox-web'）

        Returns:
            服务信息 dict，不存在则返回 {error: str}
        """
        name = params.get('name', '')
        with self._lock:
            info = self._cached_services.get(name)
        if info:
            return info
        return {'error': f'服务不存在: {name}'}

    def on_method_reload_services(self, params: Dict[str, Any]) -> Dict:
        """
        强制立即重新扫描所有服务。

        Returns:
            {count: int}
        """
        self._do_scan()
        with self._lock:
            count = len(self._cached_services)
        return {'count': count}

    def _control_service(self, service_name: str, action: str) -> Dict:
        """
        控制 Windows 服务（启动/停止/重启）。

        Args:
            service_name: Windows 服务名
            action: 'start' | 'stop' | 'restart'

        Returns:
            {success: bool, message: str}
        """
        try:
            import win32service
            import win32con

            scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
            try:
                svc = win32service.OpenService(
                    scm, service_name,
                    win32service.SERVICE_START
                    | win32service.SERVICE_STOP
                    | win32service.SERVICE_QUERY_STATUS
                )
                try:
                    status = win32service.QueryServiceStatus(svc)
                    current_state = status[1]

                    if action == 'start':
                        if current_state == win32service.SERVICE_RUNNING:
                            return {'success': True, 'message': '服务已在运行'}
                        win32service.StartService(svc, None)
                        return {'success': True, 'message': '启动命令已发送'}

                    elif action == 'stop':
                        if current_state in (win32service.SERVICE_STOPPED, win32service.SERVICE_STOP_PENDING):
                            return {'success': True, 'message': '服务已停止'}
                        win32service.ControlService(svc, win32service.SERVICE_CONTROL_STOP)
                        return {'success': True, 'message': '停止命令已发送'}

                    elif action == 'restart':
                        if current_state != win32service.SERVICE_STOPPED:
                            win32service.ControlService(svc, win32service.SERVICE_CONTROL_STOP)
                            time.sleep(0.5)
                        win32service.StartService(svc, None)
                        return {'success': True, 'message': '重启命令已发送'}

                finally:
                    win32service.CloseServiceHandle(svc)
            finally:
                win32service.CloseServiceHandle(scm)
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def on_method_start_service(self, params: Dict[str, Any]) -> Dict:
        return self._control_service(params.get('name', ''), 'start')

    def on_method_stop_service(self, params: Dict[str, Any]) -> Dict:
        return self._control_service(params.get('name', ''), 'stop')

    def on_method_restart_service(self, params: Dict[str, Any]) -> Dict:
        return self._control_service(params.get('name', ''), 'restart')
