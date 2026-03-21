# -*- coding: utf-8 -*-
"""
MetricsCollector - 指标收集器

收集请求计数、响应时间、错误率等指标。
"""

import time
import threading
from typing import Dict, Any, List
from collections import defaultdict

from ..core import TaskContext


class MetricsCollector:
    """
    指标收集器

    收集请求计数、响应时间、错误率等指标。
    """

    def __init__(self):
        """初始化指标收集器"""
        self._lock = threading.Lock()
        self._request_count = 0
        self._error_count = 0
        self._total_duration = 0.0
        self._status_codes = defaultdict(int)
        self._method_counts = defaultdict(int)
        self._path_counts = defaultdict(int)
        self._recent_requests: List[Dict[str, Any]] = []
        self._max_recent = 100  # 保留最近100个请求

    def record_request(self, context: TaskContext, duration: float):
        """
        记录请求指标

        Args:
            context: TaskContext
            duration: 处理时长（秒）
        """
        with self._lock:
            self._request_count += 1
            self._total_duration += duration

            # 状态码统计
            status = context.response_status or 500
            self._status_codes[status] += 1

            # 方法统计
            self._method_counts[context.method] += 1

            # 路径统计
            path = context.path
            if len(path) > 50:
                path = path[:50] + '...'
            self._path_counts[path] += 1

            # 错误统计
            if status >= 400:
                self._error_count += 1

            # 最近请求
            self._recent_requests.append({
                'method': context.method,
                'path': context.path,
                'status': status,
                'duration': duration,
                'timestamp': time.time()
            })
            if len(self._recent_requests) > self._max_recent:
                self._recent_requests.pop(0)

    def get_metrics(self) -> Dict[str, Any]:
        """
        获取指标数据

        Returns:
            指标字典
        """
        with self._lock:
            avg_duration = (
                self._total_duration / self._request_count
                if self._request_count > 0 else 0
            )
            error_rate = (
                self._error_count / self._request_count
                if self._request_count > 0 else 0
            )

            return {
                'request_count': self._request_count,
                'error_count': self._error_count,
                'error_rate': round(error_rate * 100, 2),
                'avg_duration_ms': round(avg_duration * 1000, 2),
                'status_codes': dict(self._status_codes),
                'method_counts': dict(self._method_counts),
                'top_paths': dict(sorted(
                    self._path_counts.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:10]),
                'recent_requests': self._recent_requests[-10:]
            }

    def reset(self):
        """重置所有指标"""
        with self._lock:
            self._request_count = 0
            self._error_count = 0
            self._total_duration = 0.0
            self._status_codes.clear()
            self._method_counts.clear()
            self._path_counts.clear()
            self._recent_requests.clear()
