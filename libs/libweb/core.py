# -*- coding: utf-8 -*-
"""
NodeManager 核心模块

提供异步请求处理的基础类：
- TaskContext: 异步任务生命周期管理
- ContextPool: TaskContext对象池
- Node: 异步请求处理基类
- NodeManager: 路由注册与请求分发
"""
from __future__ import annotations

import threading
import time
import uuid
import logging
import re
from typing import Optional, Callable, Dict, Any, List
from collections import defaultdict
from queue import Queue, Empty


# ========== TaskContext 类 ==========
class TaskContext:
    """
    管理异步任务生命周期

    属性：
        request_id: 请求唯一标识
        method: HTTP方法
        path: 请求路径
        headers: 请求头
        body: 请求体
        params: URL参数
        response_status: 响应状态码
        response_headers: 响应头
        response_body: 响应体
    """

    def __init__(self, method: str, path: str, headers: Dict[str, str] = None,
                 body: Any = None, params: Dict[str, Any] = None):
        self.request_id = str(uuid.uuid4())[:8]
        self.method = method.upper()
        self.path = path
        self.headers = headers or {}
        self.body = body
        self.params = params or {}

        # 响应信息
        self.response_status: Optional[int] = None
        self.response_headers: Dict[str, str] = {}
        self.response_body: Any = None

        # 内部状态
        self._ref_count = 1
        self._lock = threading.RLock()
        self._completion_callbacks: List[Callable] = []
        self._created_at = time.time()
        self._completed_at: Optional[float] = None

    def retain(self):
        """增加引用计数"""
        with self._lock:
            self._ref_count += 1

    def release(self):
        """减少引用计数，归零时触发收尾工作"""
        with self._lock:
            self._ref_count -= 1
            if self._ref_count <= 0:
                self._trigger_completion()

    def _trigger_completion(self):
        """触发完成回调"""
        self._completed_at = time.time()
        for callback in self._completion_callbacks:
            try:
                callback(self)
            except Exception:
                pass

    def set_response(self, status: int, headers: Dict[str, str] = None, body: Any = None):
        """设置响应信息"""
        with self._lock:
            self.response_status = status
            self.response_headers = headers or {}
            self.response_body = body

    def add_completion_callback(self, callback: Callable):
        """添加完成回调"""
        with self._lock:
            self._completion_callbacks.append(callback)

    @property
    def duration(self) -> Optional[float]:
        """获取请求处理时长（秒）"""
        if self._completed_at:
            return self._completed_at - self._created_at
        return None

    def __repr__(self):
        return f"TaskContext({self.request_id}, {self.method} {self.path})"


# ========== ContextPool 类 ==========
class ContextPool:
    """
    管理TaskContext对象池

    支持最大并发数控制，获取和释放上下文对象，
    等待队列机制处理高并发场景。
    """

    def __init__(self, max_concurrent: int = 100, timeout: float = 30.0):
        self._max_concurrent = max_concurrent
        self._timeout = timeout
        self._semaphore = threading.Semaphore(max_concurrent)
        self._waiting_queue: Queue = Queue()
        self._active_count = 0
        self._lock = threading.Lock()
        self._total_created = 0
        self._total_released = 0

    def acquire(self, method: str, path: str, headers: Dict[str, str] = None,
                body: Any = None, params: Dict[str, Any] = None) -> TaskContext:
        """获取一个TaskContext"""
        acquired = self._semaphore.acquire(timeout=self._timeout)
        if not acquired:
            raise TimeoutError(f"Failed to acquire context within {self._timeout}s")

        with self._lock:
            self._active_count += 1
            self._total_created += 1

        context = TaskContext(method, path, headers, body, params)

        def auto_release(ctx):
            self.release(ctx)
        context.add_completion_callback(auto_release)

        return context

    def release(self, context: TaskContext):
        """释放一个TaskContext"""
        with self._lock:
            self._active_count -= 1
            self._total_released += 1

        self._semaphore.release()

    @property
    def active_count(self) -> int:
        """当前活跃的上下文数量"""
        with self._lock:
            return self._active_count

    @property
    def available_count(self) -> int:
        """可用的并发数量"""
        return self._max_concurrent - self.active_count

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                'max_concurrent': self._max_concurrent,
                'active_count': self._active_count,
                'available_count': self.available_count,
                'total_created': self._total_created,
                'total_released': self._total_released,
            }


# ========== Node 基类 ==========
class Node:
    """异步请求处理基类"""

    def __init__(self, url_template: str = None):
        self.url_template = url_template

    async def do_get(self, context: TaskContext) -> None:
        """处理GET请求"""
        raise NotImplementedError("Subclass must implement do_get")

    async def do_post(self, context: TaskContext) -> None:
        """处理POST请求"""
        raise NotImplementedError("Subclass must implement do_post")

    async def do_put(self, context: TaskContext) -> None:
        """处理PUT请求"""
        raise NotImplementedError("Subclass must implement do_put")

    async def do_patch(self, context: TaskContext) -> None:
        """处理PATCH请求"""
        raise NotImplementedError("Subclass must implement do_patch")

    async def do_delete(self, context: TaskContext) -> None:
        """处理DELETE请求"""
        raise NotImplementedError("Subclass must implement do_delete")

    async def handle(self, context: TaskContext) -> None:
        """根据HTTP方法分发请求"""
        method_map = {
            'GET': self.do_get,
            'POST': self.do_post,
            'PUT': self.do_put,
            'PATCH': self.do_patch,
            'DELETE': self.do_delete,
        }

        handler = method_map.get(context.method)
        if handler:
            await handler(context)
        else:
            context.set_response(405, body={'error': 'Method Not Allowed'})


# ========== NodeManager 类 ==========
class NodeManager:
    """
    路由注册与请求分发

    管理Node注册，提供路由匹配和请求处理功能。
    """

    def __init__(self):
        """初始化NodeManager"""
        # 路由注册表: {method: {path_template: Node}}
        self._routes: Dict[str, Dict[str, Node]] = defaultdict(dict)
        # 参数化路由: [(pattern, Node)]
        self._param_routes: List[tuple] = []
        # 路由锁
        self._lock = threading.RLock()

    def register_node(self, path: str, node: Node, methods: List[str] = None):
        """注册Node到路由"""
        if methods is None:
            methods = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']

        with self._lock:
            for method in methods:
                method = method.upper()
                if '<' in path and '>' in path:
                    # 参数化路由
                    self._param_routes.append((method, path, node))
                else:
                    # 精确匹配路由
                    self._routes[method][path] = node

    def find_node(self, method: str, path: str) -> tuple:
        """查找匹配的Node"""
        method = method.upper()

        with self._lock:
            # 1. 精确匹配优先
            if path in self._routes.get(method, {}):
                node = self._routes[method][path]
                return node, {}

            # 2. 参数化匹配
            for route_method, pattern, node in self._param_routes:
                if route_method != method:
                    continue

                params = self._match_pattern(pattern, path)
                if params is not None:
                    return node, params

        return None, None

    def _match_pattern(self, pattern: str, path: str) -> Optional[Dict[str, Any]]:
        """匹配参数化路由"""
        # 转换模式为正则表达式
        regex_pattern = pattern
        regex_pattern = re.sub(r'<int:(\w+)>', r'(?P<\1>\d+)', regex_pattern)
        regex_pattern = re.sub(r'<str:(\w+)>', r'(?P<\1>[^/]+)', regex_pattern)
        regex_pattern = re.sub(r'<(\w+)>', r'(?P<\1>[^/]+)', regex_pattern)
        regex_pattern = '^' + regex_pattern + '$'

        match = re.match(regex_pattern, path)
        if match:
            return match.groupdict()
        return None

    async def handle_request(self, context: TaskContext) -> Optional[TaskContext]:
        """处理请求"""
        # 路由查找
        node, params = self.find_node(context.method, context.path)

        if node is None:
            context.set_response(404, body={'error': 'Not Found'})
            return context

        # 合并参数
        if params:
            context.params.update(params)

        # 调用Node处理
        try:
            await node.handle(context)
        except Exception as e:
            context.set_response(500, body={'error': str(e)})

        return context

    def get_registered_routes(self) -> List[Dict[str, Any]]:
        """获取已注册的路由列表"""
        routes = []

        with self._lock:
            # 精确路由
            for method, paths in self._routes.items():
                for path, node in paths.items():
                    routes.append({
                        'method': method,
                        'path': path,
                        'type': 'exact',
                        'node': node.__class__.__name__
                    })

            # 参数化路由
            for method, pattern, node in self._param_routes:
                routes.append({
                    'method': method,
                    'path': pattern,
                    'type': 'param',
                    'node': node.__class__.__name__
                })

        return routes
