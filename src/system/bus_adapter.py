# -*- coding: utf-8 -*-
"""
BusSystemAdapter - 系统监控服务的总线适配器

将系统监控能力暴露到服务总线上。

总线服务定义：

  Service:        com.dbox.systemd
  Interface:      com.dbox.Systemd
  Object Path:    /com/dbox/systemd

  Methods:
    GetMetrics()           → SystemMetrics
    GetCpuInfo()           → CPUInfo
    GetMemoryInfo()        → MemoryInfo
    GetDiskInfo()          → List[DiskInfo]
    GetHistory(limit)      → List[SystemMetrics]
    HealthCheck()          → {status: str}

使用方式：

    adapter = BusSystemAdapter(system_monitor, host='127.0.0.1', rpc_port=15555, pub_port=15556)
    adapter.start()
"""

import os
import sys
from typing import Dict, Any, Optional

# 添加 src 目录到 path
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from servicebus.service_base import BaseDBusService


class BusSystemAdapter(BaseDBusService):
    """
    系统监控服务总线适配器

    将 SystemMonitor 的监控能力暴露到服务总线上。
    """

    BUS_NAME = 'com.dbox.systemd'
    INTERFACES = ['com.dbox.Systemd']
    OBJECT_PATH = '/com/dbox/systemd'

    def __init__(self, system_monitor,
                 host: str = '127.0.0.1',
                 rpc_port: int = 15555,
                 pub_port: int = 15556):
        """
        Args:
            system_monitor: SystemMonitor 实例
            host: 总线地址
            rpc_port: 总线 RPC 端口
            pub_port: 总线 PUB 端口
        """
        super().__init__(host, rpc_port, pub_port)
        self._monitor = system_monitor

    # ============ 总线方法 ============

    def on_method_get_metrics(self, params: Dict[str, Any]) -> Dict:
        """
        获取当前系统指标

        Returns:
            完整的系统指标数据
        """
        metrics = self._monitor.get_current_metrics()
        return metrics.to_dict()

    def on_method_get_cpu_info(self, params: Dict[str, Any]) -> Dict:
        """
        获取 CPU 信息

        Returns:
            CPU 详细信息
        """
        metrics = self._monitor.get_current_metrics()
        cpu = metrics.cpu
        return {
            'count': cpu.count,
            'usage_percent': round(cpu.usage_percent, 1),
            'per_core_usage': [round(u, 1) for u in cpu.per_core_usage],
            'freq_current': cpu.freq_current,
            'freq_max': cpu.freq_max,
        }

    def on_method_get_memory_info(self, params: Dict[str, Any]) -> Dict:
        """
        获取内存信息

        Returns:
            内存详细信息
        """
        metrics = self._monitor.get_current_metrics()
        mem = metrics.memory
        return {
            'total': mem.total,
            'available': mem.available,
            'used': mem.used,
            'usage_percent': round(mem.usage_percent, 1),
            'cached': mem.cached,
        }

    def on_method_get_disk_info(self, params: Dict[str, Any]) -> Dict:
        """
        获取磁盘信息

        Returns:
            磁盘详细信息列表
        """
        metrics = self._monitor.get_current_metrics()
        return [
            {
                'device': d.device,
                'mount_point': d.mount_point,
                'total': d.total,
                'used': d.used,
                'free': d.free,
                'usage_percent': round(d.usage_percent, 1),
                'fs_type': d.fs_type,
            }
            for d in metrics.disks
        ]

    def on_method_get_history(self, params: Dict[str, Any]) -> Dict:
        """
        获取历史监控数据

        Args:
            limit: 最大返回条数，默认 60

        Returns:
            历史数据列表
        """
        limit = params.get('limit', 60)
        history = self._monitor.get_history(limit=limit)
        return {
            'history': [m.to_dict() for m in history],
            'count': len(history),
        }

    def on_method_health_check(self, params: Dict[str, Any]) -> Dict:
        """
        健康检查

        Returns:
            {status: str, metrics: dict}
        """
        try:
            metrics = self._monitor.get_current_metrics()
            return {
                'status': 'healthy',
                'cpu_percent': round(metrics.cpu.usage_percent, 1),
                'memory_percent': round(metrics.memory.usage_percent, 1),
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
            }