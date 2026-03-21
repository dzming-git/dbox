# -*- coding: utf-8 -*-
"""
LoggingMiddleware - 日志中间件

记录请求日志、响应日志、操作日志。
"""

import logging
from typing import Dict

from ..core import TaskContext


class LoggingMiddleware:
    """
    日志中间件

    记录请求日志、响应日志、操作日志。
    """

    def __init__(self, log_file: str = None, log_level: str = 'INFO'):
        """
        初始化日志中间件

        Args:
            log_file: 日志文件路径
            log_level: 日志级别
        """
        self._log_file = log_file
        self._log_level = log_level
        self._logger = logging.getLogger('node_manager')
        self._logger.setLevel(getattr(logging, log_level))

        if log_file:
            handler = logging.FileHandler(log_file, encoding='utf-8')
            formatter = logging.Formatter(
                '%(asctime)s | %(levelname)s | %(message)s'
            )
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)

    def log_request(self, context: TaskContext):
        """
        记录请求日志

        Args:
            context: TaskContext
        """
        message = f"REQUEST | {context.method} {context.path}"
        if context.params:
            message += f" | params={context.params}"
        self._logger.info(message)

    def log_response(self, context: TaskContext, duration: float):
        """
        记录响应日志

        Args:
            context: TaskContext
            duration: 处理时长（秒）
        """
        status = context.response_status or 500
        message = f"RESPONSE | {context.method} {context.path} | {status} | {duration:.3f}s"
        self._logger.info(message)

    def log_operation(self, user_id: str, operation: str, target: str, result: str = 'success'):
        """
        记录操作日志

        Args:
            user_id: 用户ID
            operation: 操作类型
            target: 操作目标
            result: 操作结果
        """
        message = f"OPERATION | {user_id} | {operation} | {target} | {result}"
        self._logger.info(message)

    def log_error(self, context: TaskContext, error: Exception):
        """
        记录错误日志

        Args:
            context: TaskContext
            error: 异常对象
        """
        message = f"ERROR | {context.method} {context.path} | {str(error)}"
        self._logger.error(message)
