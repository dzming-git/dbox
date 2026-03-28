# -*- coding: utf-8 -*-
"""
System Monitor Module - 系统监控模块

提供 CPU、内存、磁盘等系统资源的实时监控数据。
支持通过 ServiceBus 提供服务接口。
"""
from .monitor import SystemMonitor, get_system_monitor

__all__ = ['SystemMonitor', 'get_system_monitor']