#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源监控和限制模块
用于监控和控制缩略图生成进程的资源使用
"""

import os
import psutil
import time
import threading
import logging
from typing import Callable, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ResourceType(Enum):
    """资源类型"""
    MEMORY = "memory"
    CPU = "cpu"
    DISK = "disk"


@dataclass
class ResourceLimit:
    """资源限制配置"""
    max_memory_mb: int = 512  # 最大内存（MB）
    max_cpu_percent: float = 80.0  # 最大CPU使用率（%）
    check_interval: int = 5  # 检查间隔（秒）
    enable_limit: bool = True  # 是否启用限制


class ResourceMonitor:
    """资源监控器"""

    def __init__(self, limits: ResourceLimit = None):
        """
        初始化资源监控器

        Args:
            limits: 资源限制配置
        """
        self.limits = limits or ResourceLimit()
        self.process = psutil.Process()
        self.monitoring = False
        self.monitor_thread = None
        self.violations = {
            'memory': 0,
            'cpu': 0
        }
        self.callbacks = []

    def start_monitoring(self):
        """开始监控"""
        if self.monitoring:
            logger.warning("资源监控已经在运行")
            return

        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("资源监控已启动")

    def stop_monitoring(self):
        """停止监控"""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        logger.info("资源监控已停止")

    def _monitor_loop(self):
        """监控循环"""
        while self.monitoring:
            try:
                self._check_resources()
            except Exception as e:
                logger.error(f"资源检查失败: {e}", exc_info=True)

            time.sleep(self.limits.check_interval)

    def _check_resources(self):
        """检查资源使用情况"""
        if not self.limits.enable_limit:
            return

        # 检查内存使用
        memory_info = self.process.memory_info()
        memory_mb = memory_info.rss / 1024 / 1024

        if memory_mb > self.limits.max_memory_mb:
            self.violations['memory'] += 1
            logger.warning(
                f"内存超限: {memory_mb:.1f}MB > {self.limits.max_memory_mb}MB, "
                f"违规次数: {self.violations['memory']}"
            )
            self._handle_violation(ResourceType.MEMORY, memory_mb, self.limits.max_memory_mb)

        # 检查CPU使用率
        cpu_percent = self.process.cpu_percent(interval=1.0)

        if cpu_percent > self.limits.max_cpu_percent:
            self.violations['cpu'] += 1
            logger.warning(
                f"CPU超限: {cpu_percent:.1f}% > {self.limits.max_cpu_percent}%, "
                f"违规次数: {self.violations['cpu']}"
            )
            self._handle_violation(ResourceType.CPU, cpu_percent, self.limits.max_cpu_percent)

    def _handle_violation(self, resource_type: ResourceType, current: float, limit: float):
        """处理资源违规"""
        for callback in self.callbacks:
            try:
                callback(resource_type, current, limit)
            except Exception as e:
                logger.error(f"回调函数执行失败: {e}", exc_info=True)

    def add_callback(self, callback: Callable[[ResourceType, float, float], None]):
        """
        添加资源违规回调函数

        Args:
            callback: 回调函数，接收(resource_type, current, limit)参数
        """
        self.callbacks.append(callback)

    def get_current_usage(self) -> dict:
        """
        获取当前资源使用情况

        Returns:
            资源使用字典
        """
        memory_info = self.process.memory_info()
        cpu_percent = self.process.cpu_percent(interval=0.1)

        return {
            'memory_mb': memory_info.rss / 1024 / 1024,
            'memory_limit_mb': self.limits.max_memory_mb,
            'memory_usage_percent': (memory_info.rss / 1024 / 1024) / self.limits.max_memory_mb * 100,
            'cpu_percent': cpu_percent,
            'cpu_limit_percent': self.limits.max_cpu_percent,
            'violations': self.violations.copy()
        }


class ResourceLimiter:
    """资源限制器"""

    def __init__(self, limits: ResourceLimit = None):
        """
        初始化资源限制器

        Args:
            limits: 资源限制配置
        """
        self.limits = limits or ResourceLimit()
        self.monitor = ResourceMonitor(limits)
        self.paused = False
        self.pause_event = threading.Event()
        self.pause_event.set()  # 初始状态：未暂停

        # 添加默认回调
        self.monitor.add_callback(self._on_violation)

    def _on_violation(self, resource_type: ResourceType, current: float, limit: float):
        """资源违规回调"""
        if resource_type == ResourceType.MEMORY:
            # 内存超限，暂停处理
            self._pause_processing("内存超限")

        elif resource_type == ResourceType.CPU:
            # CPU超限，降低处理速度
            if self.violations['cpu'] > 3:
                # 连续3次CPU超限，暂停处理
                self._pause_processing("CPU持续超限")

    def _pause_processing(self, reason: str):
        """暂停处理"""
        if not self.paused:
            self.paused = True
            self.pause_event.clear()
            logger.warning(f"因{reason}暂停处理")
            # 30秒后自动恢复
            threading.Timer(30.0, self._resume_processing).start()

    def _resume_processing(self):
        """恢复处理"""
        if self.paused:
            self.paused = False
            self.pause_event.set()
            logger.info("处理已恢复")

    def wait_if_paused(self):
        """如果暂停则等待"""
        while self.paused:
            logger.info("等待资源释放...")
            self.pause_event.wait()

    def start(self):
        """启动资源限制"""
        self.monitor.start_monitoring()

    def stop(self):
        """停止资源限制"""
        self.monitor.stop_monitoring()

    def get_status(self) -> dict:
        """
        获取状态

        Returns:
            状态字典
        """
        usage = self.monitor.get_current_usage()
        usage['paused'] = self.paused

        return usage


class ContextManagerResourceLimiter:
    """上下文管理器方式的资源限制器"""

    def __init__(self, limits: ResourceLimit = None):
        """
        初始化

        Args:
            limits: 资源限制配置
        """
        self.limiter = ResourceLimiter(limits)

    def __enter__(self):
        """进入上下文"""
        self.limiter.start()
        return self.limiter

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文"""
        self.limiter.stop()


# 全局资源限制器实例
_global_limiter: Optional[ResourceLimiter] = None


def get_resource_limiter(limits: ResourceLimit = None) -> ResourceLimiter:
    """
    获取全局资源限制器实例

    Args:
        limits: 资源限制配置（仅在首次调用时生效）

    Returns:
        资源限制器实例
    """
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = ResourceLimiter(limits)
    return _global_limiter


def with_resource_limit(limits: ResourceLimit = None):
    """
    装饰器：为函数添加资源限制

    Args:
        limits: 资源限制配置
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            limiter = ResourceLimiter(limits)
            try:
                limiter.start()
                limiter.wait_if_paused()
                result = func(*args, **kwargs)
                return result
            finally:
                limiter.stop()
        return wrapper
    return decorator


if __name__ == '__main__':
    # 测试代码
    logging.basicConfig(level=logging.INFO)

    limits = ResourceLimit(
        max_memory_mb=100,
        max_cpu_percent=50.0,
        check_interval=2
    )

    print("测试资源监控...")
    with ContextManagerResourceLimiter(limits) as limiter:
        print("监控已启动")
        time.sleep(10)
        status = limiter.get_status()
        print(f"当前状态: {status}")
