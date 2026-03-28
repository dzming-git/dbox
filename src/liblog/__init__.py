# -*- coding: utf-8 -*-
"""
LibLog - 统一日志接口库

提供线程安全的日志记录功能，支持四种日志分类：
- 维护日志 (maintenance): 关键操作、状态变更
- 运行日志 (runtime): 流水账
- 调试日志 (debug): 开发调试
- 操作日志 (operation): 用户操作

特性：
- 服务标识：每个服务用自己的名字注册 logger
- 自动记录：服务名自动附加到每条日志
- 服务筛选：日志可按服务名筛选（类似 journalctl -u）

用法:
    # 方式一：ServiceLogger（推荐，服务级别日志）
    from liblog import get_service_logger, register_service

    # 在服务入口注册服务名
    register_service('dplayer-web')
    log = get_service_logger()
    log.maintenance('INFO', '服务启动成功')

    # 或直接指定服务名
    log = get_service_logger('dplayer-thumbnail')

    # 方式二：便捷函数
    from liblog import log_maintenance, log_runtime, log_debug, log_operation
    log_maintenance('INFO', '服务启动成功')
    log_runtime('INFO', '任务创建')
"""
from .logger import (
    get_logger,
    get_service_logger,
    register_service,
    ServiceLogger,
    log,
    log_maintenance,
    log_runtime,
    log_debug,
    log_operation,
    LOG_CATEGORIES,
    LOG_LEVELS,
)

__all__ = [
    'get_logger',
    'get_service_logger',
    'register_service',
    'ServiceLogger',
    'log',
    'log_maintenance',
    'log_runtime',
    'log_debug',
    'log_operation',
    'LOG_CATEGORIES',
    'LOG_LEVELS',
]