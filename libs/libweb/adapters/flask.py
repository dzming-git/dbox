# -*- coding: utf-8 -*-
"""
FlaskAdapter - Flask应用适配器
DualRouter - 双轨路由系统

提供Flask应用适配和双轨路由支持。
"""

import threading
from typing import Dict, Any, List, Optional

from ..core import NodeManager, ContextPool, Node


class FlaskAdapter:
    """
    Flask应用适配器

    将Flask请求转换为TaskContext，
    并将处理结果转换回Flask响应。
    """

    def __init__(self, node_manager: NodeManager, context_pool: ContextPool = None):
        """
        初始化Flask适配器

        Args:
            node_manager: NodeManager实例
            context_pool: 可选的ContextPool实例
        """
        self.node_manager = node_manager
        self.context_pool = context_pool or ContextPool()

    def create_request_handler(self):
        """
        创建Flask请求处理函数

        Returns:
            Flask视图函数
        """
        adapter = self

        async def handle_request_async():
            """异步请求处理"""
            # 从Flask获取请求信息
            from flask import request, g

            # 获取请求数据
            method = request.method
            path = request.path
            headers = dict(request.headers)
            body = request.get_json(silent=True) if request.is_json else None
            params = request.args.to_dict()

            # 从对象池获取上下文
            context = adapter.context_pool.acquire(method, path, headers, body, params)

            # 设置Flask g对象
            g.task_context = context

            try:
                # 处理请求
                await adapter.node_manager.handle_request(context)

                # 转换为Flask响应
                from flask import jsonify, Response
                status = context.response_status or 200
                response_headers = context.response_headers or {}

                if context.response_body is not None:
                    if isinstance(context.response_body, dict):
                        response = jsonify(context.response_body)
                    else:
                        response = Response(str(context.response_body))
                else:
                    response = Response('')

                response.status_code = status
                for key, value in response_headers.items():
                    response.headers[key] = value

                return response

            finally:
                # 释放上下文
                adapter.context_pool.release(context)

        return handle_request_async

    def register_to_flask(self, app, url_prefix: str = ''):
        """
        将NodeManager路由注册到Flask应用

        Args:
            app: Flask应用实例
            url_prefix: URL前缀
        """
        routes = self.node_manager.get_registered_routes()

        for route in routes:
            path = url_prefix + route['path']
            methods = [route['method']]
            handler = self.create_request_handler()
            app.add_url_rule(path, view_func=handler, methods=methods)


class DualRouter:
    """
    双轨路由系统

    支持传统Flask路由和NodeManager路由并存，
    允许渐进式迁移。
    """

    def __init__(self, node_manager: NodeManager = None):
        """
        初始化双轨路由器

        Args:
            node_manager: 可选的NodeManager实例
        """
        self.node_manager = node_manager or NodeManager()
        self.flask_routes = {}  # Flask原生路由
        self.node_routes = {}   # NodeManager路由
        self._route_overrides = {}  # 路由优先级配置

    def add_flask_route(self, path: str, handler, methods: List[str] = None):
        """
        添加Flask原生路由

        Args:
            path: URL路径
            handler: Flask处理函数
            methods: HTTP方法列表
        """
        if methods is None:
            methods = ['GET']
        self.flask_routes[path] = {'handler': handler, 'methods': methods}

    def add_node_route(self, path: str, node: Node, methods: List[str] = None):
        """
        添加NodeManager路由

        Args:
            path: URL路径
            node: Node实例
            methods: HTTP方法列表
        """
        self.node_manager.register_node(path, node, methods)
        self.node_routes[path] = {'node': node, 'methods': methods}

    def set_route_priority(self, path: str, priority: str):
        """
        设置路由优先级

        Args:
            path: URL路径
            priority: 'flask' 或 'node'
        """
        self._route_overrides[path] = priority

    def find_handler(self, path: str, method: str):
        """
        查找请求的处理方式

        Args:
            path: URL路径
            method: HTTP方法

        Returns:
            ('flask', handler) 或 ('node', node)
        """
        # 检查是否有优先级设置
        if path in self._route_overrides:
            priority = self._route_overrides[path]
            if priority == 'flask' and path in self.flask_routes:
                return 'flask', self.flask_routes[path]
            elif priority == 'node':
                node, _ = self.node_manager.find_node(method, path)
                if node:
                    return 'node', node

        # 查找Flask路由
        if path in self.flask_routes:
            return 'flask', self.flask_routes[path]

        # 查找Node路由
        node, _ = self.node_manager.find_node(method, path)
        if node:
            return 'node', node

        return None, None

    def get_all_routes(self) -> Dict[str, Any]:
        """
        获取所有路由信息

        Returns:
            路由信息字典
        """
        return {
            'flask': self.flask_routes,
            'node': self.node_routes,
            'overrides': self._route_overrides
        }
