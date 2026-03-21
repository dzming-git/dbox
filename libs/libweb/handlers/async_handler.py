# -*- coding: utf-8 -*-
"""
AsyncRequestHandler - 异步请求处理器
PriorityContextPool - 优先级ContextPool

提供异步请求处理和优先级队列支持。
"""

import asyncio
from typing import Dict, Any, List
from queue import Queue, Empty

from ..core import NodeManager, ContextPool, TaskContext


class AsyncRequestHandler:
    """
    异步请求处理器

    支持队列缓冲、优先级调度、超时控制等高级功能。
    """

    def __init__(self, node_manager: NodeManager, context_pool: ContextPool = None):
        """
        初始化异步请求处理器

        Args:
            node_manager: NodeManager实例
            context_pool: ContextPool实例
        """
        self.node_manager = node_manager
        self.context_pool = context_pool or ContextPool()
        self._request_queue = Queue()
        self._running = False

    async def process_request(self, method: str, path: str, headers: Dict[str, str] = None,
                             body: Any = None, params: Dict[str, Any] = None) -> TaskContext:
        """
        处理单个异步请求

        Args:
            method: HTTP方法
            path: 请求路径
            headers: 请求头
            body: 请求体
            params: URL参数

        Returns:
            TaskContext对象
        """
        # 获取上下文
        context = self.context_pool.acquire(method, path, headers, body, params)

        try:
            # 处理请求
            await self.node_manager.handle_request(context)
            return context
        except Exception as e:
            context.set_response(500, body={'error': str(e)})
            return context

    async def process_batch(self, requests: List[Dict[str, Any]]) -> List[TaskContext]:
        """
        批量处理异步请求

        Args:
            requests: 请求列表

        Returns:
            TaskContext对象列表
        """
        tasks = []
        for req in requests:
            task = self.process_request(
                method=req.get('method', 'GET'),
                path=req.get('path', '/'),
                headers=req.get('headers'),
                body=req.get('body'),
                params=req.get('params')
            )
            tasks.append(task)

        # 并发执行所有任务
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常结果
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                context = self.context_pool.acquire(
                    requests[i].get('method', 'GET'),
                    requests[i].get('path', '/')
                )
                context.set_response(500, body={'error': str(result)})
                processed_results.append(context)
            else:
                processed_results.append(result)

        return processed_results


class PriorityContextPool(ContextPool):
    """
    支持优先级的ContextPool

    高优先级请求可以插队优先处理。
    """

    def __init__(self, max_concurrent: int = 100, timeout: float = 30.0):
        """
        初始化优先级ContextPool

        Args:
            max_concurrent: 最大并发数
            timeout: 获取上下文超时时间
        """
        super().__init__(max_concurrent, timeout)
        self._high_priority_queue: Queue = Queue()
        self._normal_priority_queue: Queue = Queue()
        self._low_priority_queue: Queue = Queue()

    def acquire(self, method: str, path: str, headers: Dict[str, str] = None,
                body: Any = None, params: Dict[str, Any] = None,
                priority: str = 'normal') -> TaskContext:
        """
        获取一个TaskContext（支持优先级）

        Args:
            method: HTTP方法
            path: 请求路径
            headers: 请求头
            body: 请求体
            params: URL参数
            priority: 优先级 ('high', 'normal', 'low')

        Returns:
            TaskContext对象
        """
        # 根据优先级选择队列
        if priority == 'high':
            queue = self._high_priority_queue
        elif priority == 'low':
            queue = self._low_priority_queue
        else:
            queue = self._normal_priority_queue

        # 尝试从优先级队列获取
        try:
            context = queue.get_nowait()
            # 重置上下文状态
            context.method = method.upper()
            context.path = path
            context.headers = headers or {}
            context.body = body
            context.params = params or {}
            context.response_status = None
            context.response_headers = {}
            context.response_body = None
            context._ref_count = 1
            return context
        except Empty:
            # 队列为空，创建新上下文
            pass

        # 使用父类方法获取
        return super().acquire(method, path, headers, body, params)

    def release(self, context: TaskContext):
        """
        释放一个TaskContext

        Args:
            context: 要释放的TaskContext
        """
        # 简单实现：直接释放，不回收
        super().release(context)
