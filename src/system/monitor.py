# -*- coding: utf-8 -*-
"""
System Monitor - 系统监控模块

提供 CPU、内存、磁盘、网络等系统资源的实时监控数据。
"""

import os
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional


# ============ 数据模型 ============

@dataclass
class CPUInfo:
    """CPU 信息"""
    count: int                    # CPU 核心数
    usage_percent: float          # 总使用率 (0-100)
    per_core_usage: List[float]   # 每核心使用率
    freq_current: Optional[float] # 当前频率 (MHz)
    freq_max: Optional[float]     # 最大频率

@dataclass
class MemoryInfo:
    """内存信息"""
    total: int                    # 总内存 (bytes)
    available: int                # 可用内存 (bytes)
    used: int                     # 已用内存 (bytes)
    usage_percent: float           # 使用率 (0-100)
    cached: int                   # 缓存内存

@dataclass
class DiskInfo:
    """磁盘信息"""
    device: str                   # 设备名 (如 'C:')
    mount_point: str              # 挂载点 (如 'C:\\')
    total: int                    # 总容量 (bytes)
    used: int                     # 已用 (bytes)
    free: int                     # 空闲 (bytes)
    usage_percent: float           # 使用率 (0-100)
    fs_type: str                  # 文件系统类型

@dataclass
class NetworkInfo:
    """网络信息"""
    interface: str                 # 网卡名
    bytes_sent: int               # 发送字节数
    bytes_recv: int               # 接收字节数
    packets_sent: int             # 发送包数
    packets_recv: int             # 接收包数
    errin: int                    # 输入错误
    errout: int                   # 输出错误

@dataclass
class SystemMetrics:
    """系统指标汇总"""
    timestamp: str                # ISO 格式时间戳
    cpu: CPUInfo
    memory: MemoryInfo
    disks: List[DiskInfo]
    uptime: float                 # 运行时间 (秒)
    load_avg: Optional[List[float]]  # 负载均值 (Linux)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': self.timestamp,
            'cpu': {
                'count': self.cpu.count,
                'usage_percent': round(self.cpu.usage_percent, 1),
                'per_core_usage': [round(u, 1) for u in self.cpu.per_core_usage],
                'freq_current': self.cpu.freq_current,
                'freq_max': self.cpu.freq_max,
            },
            'memory': {
                'total': self.memory.total,
                'available': self.memory.available,
                'used': self.memory.used,
                'usage_percent': round(self.memory.usage_percent, 1),
                'cached': self.memory.cached,
            },
            'disks': [
                {
                    'device': d.device,
                    'mount_point': d.mount_point,
                    'total': d.total,
                    'used': d.used,
                    'free': d.free,
                    'usage_percent': round(d.usage_percent, 1),
                    'fs_type': d.fs_type,
                }
                for d in self.disks
            ],
            'uptime': self.uptime,
            'load_avg': self.load_avg,
        }


# ============ 系统监控器 ============

class SystemMonitor:
    """
    系统资源监控器

    轮询获取 CPU、内存、磁盘、网络等系统资源使用情况。
    支持 Windows 和 Linux。
    """

    def __init__(self, interval: float = 2.0):
        """
        Args:
            interval: 轮询间隔（秒）
        """
        self.interval = interval
        self._stop = False
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._last_metrics: Optional[SystemMetrics] = None
        self._history: List[SystemMetrics] = []
        self._max_history = 60  # 保留最近 60 条历史记录

        # 初始化平台特定模块
        self._init_platform()

    def _init_platform(self):
        """初始化平台特定的监控模块"""
        import platform
        self._platform = platform.system().lower()

        if self._platform == 'windows':
            self._init_windows()
        elif self._platform == 'linux':
            self._init_linux()
        else:
            raise NotImplementedError(f"Unsupported platform: {self._platform}")

    def _init_windows(self):
        """初始化 Windows 监控"""
        try:
            import psutil
            self._psutil = psutil
        except ImportError:
            raise ImportError("psutil is required for Windows monitoring. Install: pip install psutil")

    def _init_linux(self):
        """初始化 Linux 监控"""
        try:
            import psutil
            self._psutil = psutil
        except ImportError:
            raise ImportError("psutil is required for Linux monitoring. Install: pip install psutil")

    # ============ 公开接口 ============

    def start(self):
        """启动后台轮询"""
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止后台轮询"""
        self._stop = True
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def get_current_metrics(self) -> SystemMetrics:
        """获取当前系统指标（同步调用）"""
        return self._collect_metrics()

    def get_metrics(self) -> Optional[SystemMetrics]:
        """获取最近一次轮询结果（需要先调用 start）"""
        with self._lock:
            return self._last_metrics

    def get_history(self, limit: int = 60) -> List[SystemMetrics]:
        """获取历史记录"""
        with self._lock:
            return self._history[-limit:]

    # ============ 轮询循环 ============

    def _poll_loop(self):
        """后台轮询循环"""
        while not self._stop:
            try:
                metrics = self._collect_metrics()
                with self._lock:
                    self._last_metrics = metrics
                    self._history.append(metrics)
                    if len(self._history) > self._max_history:
                        self._history.pop(0)
            except Exception as e:
                print(f"[SystemMonitor] Error collecting metrics: {e}")
            time.sleep(self.interval)

    # ============ 数据采集 ============

    def _collect_metrics(self) -> SystemMetrics:
        """采集所有系统指标"""
        return SystemMetrics(
            timestamp=datetime.now().isoformat(),
            cpu=self._collect_cpu(),
            memory=self._collect_memory(),
            disks=self._collect_disks(),
            uptime=self._get_uptime(),
            load_avg=self._get_load_avg(),
        )

    def _collect_cpu(self) -> CPUInfo:
        """采集 CPU 信息"""
        per_core = self._psutil.cpu_percent(interval=0.1, percpu=True)
        total_usage = sum(per_core) / len(per_core)

        freq = None
        freq_max = None
        try:
            cpu_freq = self._psutil.cpu_freq()
            if cpu_freq:
                freq = cpu_freq.current
                freq_max = cpu_freq.max
        except Exception:
            pass

        return CPUInfo(
            count=len(per_core),
            usage_percent=total_usage,
            per_core_usage=per_core,
            freq_current=freq,
            freq_max=freq_max,
        )

    def _collect_memory(self) -> MemoryInfo:
        """采集内存信息"""
        mem = self._psutil.virtual_memory()
        return MemoryInfo(
            total=mem.total,
            available=mem.available,
            used=mem.used,
            usage_percent=mem.percent,
            cached=getattr(mem, 'cached', 0),
        )

    def _collect_disks(self) -> List[DiskInfo]:
        """采集磁盘信息"""
        disks = []
        for partition in self._psutil.disk_partitions(all=False):
            try:
                usage = self._psutil.disk_usage(partition.mountpoint)
                disks.append(DiskInfo(
                    device=partition.device or partition.mountpoint,
                    mount_point=partition.mountpoint,
                    total=usage.total,
                    used=usage.used,
                    free=usage.free,
                    usage_percent=usage.percent,
                    fs_type=partition.fstype or 'unknown',
                ))
            except PermissionError:
                # 某些磁盘可能没有权限
                continue
            except Exception:
                continue
        return disks

    def _get_uptime(self) -> float:
        """获取系统运行时间（秒）"""
        try:
            boot_time = self._psutil.boot_time()
            return time.time() - boot_time
        except Exception:
            return 0.0

    def _get_load_avg(self) -> Optional[List[float]]:
        """获取系统负载（Linux）"""
        if self._platform != 'linux':
            return None
        try:
            import os
            return os.getloadavg()
        except Exception:
            return None


# ============ 全局单例 ============

_monitor: Optional[SystemMonitor] = None


def get_system_monitor() -> SystemMonitor:
    """获取系统监控器单例"""
    global _monitor
    if _monitor is None:
        _monitor = SystemMonitor(interval=2.0)
        _monitor.start()
    return _monitor