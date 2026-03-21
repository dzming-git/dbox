# -*- coding: utf-8 -*-
"""
NodeManager 核心模块单元测试
"""

import unittest
import asyncio
import threading
import time
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from node_manager.core import TaskContext, ContextPool, Node, NodeManager


# ========== TaskContext 测试 ==========
class TestTaskContext(unittest.TestCase):

    def test_create_context(self):
        """测试创建TaskContext"""
        ctx = TaskContext('GET', '/api/test', {'Host': 'localhost'})
        self.assertIsNotNone(ctx.request_id)
        self.assertEqual(ctx.method, 'GET')
        self.assertEqual(ctx.path, '/api/test')
        self.assertEqual(ctx.headers['Host'], 'localhost')

    def test_retain_release(self):
        """测试引用计数"""
        ctx = TaskContext('GET', '/api/test')
        self.assertEqual(ctx._ref_count, 1)

        ctx.retain()
        self.assertEqual(ctx._ref_count, 2)

        ctx.release()
        self.assertEqual(ctx._ref_count, 1)

        ctx.release()  # 触发完成回调
        self.assertEqual(ctx._ref_count, 0)

    def test_completion_callback(self):
        """测试完成回调"""
        callback_called = []

        def callback(ctx):
            callback_called.append(ctx)

        ctx = TaskContext('GET', '/api/test')
        ctx.add_completion_callback(callback)
        ctx.release()

        self.assertEqual(len(callback_called), 1)

    def test_set_response(self):
        """测试设置响应"""
        ctx = TaskContext('GET', '/api/test')
        ctx.set_response(200, {'Content-Type': 'application/json'}, {'status': 'ok'})

        self.assertEqual(ctx.response_status, 200)
        self.assertEqual(ctx.response_headers['Content-Type'], 'application/json')
        self.assertEqual(ctx.response_body, {'status': 'ok'})


# ========== ContextPool 测试 ==========
class TestContextPool(unittest.TestCase):

    def test_acquire_release(self):
        """测试获取和释放"""
        pool = ContextPool(max_concurrent=5)

        ctx = pool.acquire('GET', '/api/test')
        self.assertIsNotNone(ctx)
        self.assertEqual(pool.active_count, 1)

        pool.release(ctx)
        self.assertEqual(pool.active_count, 0)

    def test_stats(self):
        """测试统计信息"""
        pool = ContextPool(max_concurrent=10)

        ctx1 = pool.acquire('GET', '/api/test1')
        ctx2 = pool.acquire('GET', '/api/test2')

        stats = pool.get_stats()
        self.assertEqual(stats['max_concurrent'], 10)
        self.assertEqual(stats['active_count'], 2)
        self.assertEqual(stats['available_count'], 8)
        self.assertEqual(stats['total_created'], 2)

        pool.release(ctx1)
        pool.release(ctx2)

        stats = pool.get_stats()
        self.assertEqual(stats['total_released'], 2)


# ========== Node 测试 ==========
class MockNode(Node):
    """用于测试的Mock Node"""

    def __init__(self, url_template: str = '/api/mock'):
        super().__init__(url_template)

    async def do_get(self, context: TaskContext):
        context.set_response(200, body={'mock': 'get'})

    async def do_post(self, context: TaskContext):
        context.set_response(201, body={'mock': 'post'})


# ========== NodeManager 测试 ==========
class TestNodeManager(unittest.TestCase):

    def setUp(self):
        """测试前准备"""
        self.manager = NodeManager()
        self.mock_node = MockNode()

    def test_register_exact_route(self):
        """测试精确路由注册"""
        self.manager.register_node('/api/users', self.mock_node, ['GET', 'POST'])

        routes = self.manager.get_registered_routes()
        self.assertEqual(len(routes), 2)

    def test_register_param_route(self):
        """测试参数化路由注册"""
        self.manager.register_node('/api/users/<int:user_id>', self.mock_node, ['GET'])

        routes = self.manager.get_registered_routes()
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0]['type'], 'param')

    def test_find_exact_route(self):
        """测试精确路由查找"""
        self.manager.register_node('/api/users', self.mock_node, ['GET'])

        node, params = self.manager.find_node('GET', '/api/users')
        self.assertIsNotNone(node)
        self.assertEqual(params, {})

    def test_find_param_route(self):
        """测试参数化路由查找"""
        self.manager.register_node('/api/users/<int:user_id>', self.mock_node, ['GET'])

        node, params = self.manager.find_node('GET', '/api/users/123')
        self.assertIsNotNone(node)
        self.assertEqual(params['user_id'], '123')

    def test_find_not_found(self):
        """测试未找到路由"""
        node, params = self.manager.find_node('GET', '/api/notexist')
        self.assertIsNone(node)

    def test_handle_request(self):
        """测试请求处理"""
        self.manager.register_node('/api/mock', self.mock_node, ['GET'])

        ctx = TaskContext('GET', '/api/mock')
        asyncio.run(self.manager.handle_request(ctx))

        self.assertEqual(ctx.response_status, 200)
        self.assertEqual(ctx.response_body, {'mock': 'get'})

    def test_method_not_allowed(self):
        """测试方法不允许"""
        self.manager.register_node('/api/mock', self.mock_node, ['GET'])

        ctx = TaskContext('POST', '/api/mock')
        asyncio.run(self.manager.handle_request(ctx))

        self.assertEqual(ctx.response_status, 405)


# ========== 路由匹配算法测试 ==========
class TestRouteMatching(unittest.TestCase):

    def test_exact_match_priority(self):
        """测试精确匹配优先于参数化匹配"""
        manager = NodeManager()

        exact_node = MockNode('/api/users')
        param_node = MockNode('/api/users/<id>')

        manager.register_node('/api/users', exact_node, ['GET'])
        manager.register_node('/api/users/<id>', param_node, ['GET'])

        # 应该匹配精确路由
        node, params = manager.find_node('GET', '/api/users')
        self.assertEqual(node.url_template, '/api/users')
        self.assertEqual(params, {})

    def test_int_param_matching(self):
        """测试整数参数匹配"""
        manager = NodeManager()
        node = MockNode('/api/items/<int:item_id>')
        manager.register_node('/api/items/<int:item_id>', node, ['GET'])

        # 整数应该匹配
        node, params = manager.find_node('GET', '/api/items/42')
        self.assertIsNotNone(node)
        self.assertEqual(params['item_id'], '42')

    def test_str_param_matching(self):
        """测试字符串参数匹配"""
        manager = NodeManager()
        node = MockNode('/api/users/<str:username>')
        manager.register_node('/api/users/<str:username>', node, ['GET'])

        node, params = manager.find_node('GET', '/api/users/john')
        self.assertIsNotNone(node)
        self.assertEqual(params['username'], 'john')


if __name__ == '__main__':
    unittest.main()
