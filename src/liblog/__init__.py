# -*- coding: utf-8 -*-
"""
LibLog - 统一日志接口库

提供线程安全的日志记录功能，支持四种日志分类：
- 维护日志 (maintenance): 关键操作、状态变更
- 运行日志 (runtime): 流水账
- 调试日志 (debug): 开发调试
- 操作日志 (operation): 用户操作

用法:
    # 方式一：便捷函数（module 自动获取）
    from liblog import log_maintenance, log_runtime, log_debug, log_operation
    log_maintenance('INFO', '服务启动成功')
    log_runtime('INFO', '缩略图任务创建: hash=abc123')
    log_debug('DEBUG', '查询参数: %s', params)
    log_operation('用户登录', source_ip='203.0.113.7')
    
    # 方式二：ModuleLogger（推荐，避免重复获取 module）
    from liblog import get_module_logger
    log = get_module_logger()
    log.maintenance('INFO', '服务启动成功')
    log.runtime('INFO', '任务创建')
    log.debug('DEBUG', '调试信息')
    log.operation('用户操作', source_ip='203.0.113.7')
    
    # 方式三：底层接口
    from liblog import log
    log('maintenance', 'ERROR', 'my_module', '服务停止')
"""
from .logger import (
    get_logger,
    get_module_logger,
    ModuleLogger,
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
    'get_module_logger',
    'ModuleLogger',
    'log',
    'log_maintenance',
    'log_runtime',
    'log_debug',
    'log_operation',
    'LOG_CATEGORIES',
    'LOG_LEVELS',
]
