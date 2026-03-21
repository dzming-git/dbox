# -*- coding: utf-8 -*-
"""
NodeManager与Flask应用集成

将现有的Flask路由包装为Node，实现完全迁移。
"""

import asyncio
from flask import request, g
from .core import Node, TaskContext, NodeManager, ContextPool
from .adapters import FlaskAdapter


# ========== 包装现有Flask函数为Node ==========

class FlaskWrapperNode(Node):
    """包装Flask视图函数为Node"""

    def __init__(self, path: str, flask_handler, methods: list):
        super().__init__(path)
        self.flask_handler = flask_handler
        self.methods = methods

    async def do_get(self, context: TaskContext):
        await self._handle_flask(context)

    async def do_post(self, context: TaskContext):
        await self._handle_flask(context)

    async def do_put(self, context: TaskContext):
        await self._handle_flask(context)

    async def do_delete(self, context: TaskContext):
        await self._handle_flask(context)

    async def do_patch(self, context: TaskContext):
        await self._handle_flask(context)

    async def _handle_flask(self, context: TaskContext):
        """同步调用Flask处理函数"""
        try:
            # 调用Flask视图函数
            result = self.flask_handler()

            # 设置响应
            if hasattr(result, 'status_code'):
                context.set_response(
                    result.status_code,
                    headers=dict(result.headers) if result.headers else {},
                    body=result.get_json() if result.is_json else result.data
                )
            elif isinstance(result, dict):
                context.set_response(200, body=result)
            else:
                context.set_response(200, body={'result': str(result)})
        except Exception as e:
            context.set_response(500, body={'error': str(e)})


# ========== Flask应用适配器 ==========

class FlaskAppAdapter:
    """
    Flask应用适配器 - 完全迁移版本

    将Flask应用的所有路由转换为NodeManager路由。
    """

    def __init__(self, flask_app, node_manager: NodeManager = None):
        """
        初始化适配器

        Args:
            flask_app: Flask应用实例
            node_manager: NodeManager实例
        """
        self.flask_app = flask_app
        self.node_manager = node_manager or NodeManager()
        self.context_pool = ContextPool()

    def migrate_all_routes(self):
        """迁移所有Flask路由到NodeManager"""
        print("[*] 开始迁移Flask路由到NodeManager...")

        for rule in self.flask_app.url_map.iter_rules():
            # 跳过静态文件等特殊路由
            if rule.endpoint == 'static':
                continue

            # 获取视图函数
            view_func = self.flask_app.view_functions.get(rule.endpoint)
            if not view_func:
                continue

            # 转换路径模板
            path = self._convert_rule_to_path(rule)

            # 转换方法
            methods = [m for m in rule.methods if m not in ['HEAD', 'OPTIONS']]

            # 创建Node并注册
            node = FlaskWrapperNode(path, view_func, methods)
            self.node_manager.register_node(path, node, methods)

            print(f"    - {', '.join(methods)} {path} -> {rule.endpoint}")

        print(f"[*] 迁移完成，共 {len(self.node_manager.get_registered_routes())} 个路由")

    def _convert_rule_to_path(self, rule) -> str:
        """将Flask路由规则转换为NodeManager路径"""
        path = rule.rule

        # 转换Flask路由语法为NodeManager语法
        # <converter:name> -> <name>
        import re
        path = re.sub(r'<([^:]+):([^>]+)>', r'<\2>', path)
        # <name> -> <str:name>
        path = re.sub(r'<([^>]+)>', r'<str:\1>', path)

        return path

    def create_unified_handler(self):
        """创建统一请求处理函数"""
        adapter = self

        async def handle_request():
            """处理所有NodeManager路由请求"""
            # 从Flask获取请求信息
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
                # 查找并处理请求
                node, params = adapter.node_manager.find_node(method, path)

                if node:
                    # 合并参数
                    if params:
                        context.params.update(params)

                    # 处理请求
                    await node.handle(context)
                else:
                    context.set_response(404, body={'error': 'Not Found'})

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
                adapter.context_pool.release(context)

        return handle_request


# ========== 迁移函数 ==========

def migrate_flask_to_node_manager(flask_app, node_manager: NodeManager = None) -> NodeManager:
    """
    将Flask应用完全迁移到NodeManager

    Args:
        flask_app: Flask应用实例
        node_manager: 可选的NodeManager实例

    Returns:
        迁移后的NodeManager实例
    """
    adapter = FlaskAppAdapter(flask_app, node_manager)
    adapter.migrate_all_routes()

    return adapter.node_manager


def create_migrated_app():
    """
    创建完全迁移到NodeManager的Flask应用

    Returns:
        Flask应用实例（已集成NodeManager）
    """
    from flask import Flask, jsonify
    from app import app as flask_app

    # 迁移
    adapter = FlaskAppAdapter(flask_app)
    adapter.migrate_all_routes()

    # 创建统一处理器
    handler = adapter.create_unified_handler()

    # 为每个路由注册处理器
    routes = adapter.node_manager.get_registered_routes()
    for route in routes:
        path = route['path']
        methods = [route['method']]
        flask_app.add_url_rule(path, view_func=handler, methods=methods, provide_automatic_options=False)

    return flask_app
