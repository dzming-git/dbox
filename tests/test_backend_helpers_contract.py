"""backend.helpers 统一响应封装与 backend.service_buses 契约测试。

锁定 {success, data, code, message} 响应格式，避免各蓝图响应结构漂移；
验证 init_service_buses 在总线不可用时也能安全返回（不抛异常）。
"""
import json
import os
import sys
import types
import unittest

SRC_WEB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'web'))
if SRC_WEB not in sys.path:
    sys.path.insert(0, SRC_WEB)

# liblog 由运行时注入，测试环境用桩模块模拟（提供 maintenance 等方法）
if 'liblog' not in sys.modules:
    _liblog = types.ModuleType('liblog')
    _logger = __import__('logging').getLogger('test')

    class _FakeServiceLogger:
        def __init__(self, name=''):
            self._name = name

        def maintenance(self, level, msg, *a):
            _logger.log(__import__('logging').INFO, f'[{level}] {msg}')

        def info(self, msg, *a, **k):
            _logger.info(msg)

        def warn(self, msg, *a, **k):
            _logger.warning(msg)

        def error(self, msg, *a, **k):
            _logger.error(msg)

        def debug(self, msg, *a, **k):
            _logger.debug(msg)

    _liblog.get_service_logger = lambda name='': _FakeServiceLogger(name)
    sys.modules['liblog'] = _liblog

from backend.helpers import success_response, error_response


class TestHelpersResponseContract(unittest.TestCase):
    def test_success_response_shape(self):
        resp = success_response({'k': 1}, message='ok')
        body = json.loads(resp.get_data(as_text=True))
        self.assertEqual(body['success'], True)
        self.assertEqual(body['code'], 0)
        self.assertEqual(body['message'], 'ok')
        self.assertEqual(body['data'], {'k': 1})

    def test_success_response_defaults(self):
        resp = success_response()
        body = json.loads(resp.get_data(as_text=True))
        self.assertTrue(body['success'])
        self.assertEqual(body['data'], None)
        self.assertEqual(body['code'], 0)

    def test_error_response_shape(self):
        resp = error_response('boom', code=7)
        body = json.loads(resp.get_data(as_text=True))
        self.assertEqual(body['success'], False)
        self.assertEqual(body['code'], 7)
        self.assertEqual(body['message'], 'boom')


class TestServiceBusesContract(unittest.TestCase):
    def test_init_service_buses_returns_dict_without_raising(self):
        # 在无 servicebus / 无总线服务的环境下，init_service_buses 必须安全返回且不为 None
        from backend.service_buses import init_service_buses
        src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
        buses = init_service_buses(src_dir)
        self.assertIsInstance(buses, dict)
        self.assertIn('thumbnail_bus', buses)
        self.assertIn('svc_mgr_bus', buses)
        self.assertIn('resource_bus', buses)


class TestHelpersResponseContract(unittest.TestCase):
    def test_success_response_shape(self):
        resp = success_response({'k': 1}, message='ok')
        body = json.loads(resp.get_data(as_text=True))
        self.assertEqual(body['success'], True)
        self.assertEqual(body['code'], 0)
        self.assertEqual(body['message'], 'ok')
        self.assertEqual(body['data'], {'k': 1})

    def test_success_response_defaults(self):
        resp = success_response()
        body = json.loads(resp.get_data(as_text=True))
        self.assertTrue(body['success'])
        self.assertEqual(body['data'], None)
        self.assertEqual(body['code'], 0)

    def test_error_response_shape(self):
        resp = error_response('boom', code=7)
        body = json.loads(resp.get_data(as_text=True))
        self.assertEqual(body['success'], False)
        self.assertEqual(body['code'], 7)
        self.assertEqual(body['message'], 'boom')


class TestServiceBusesContract(unittest.TestCase):
    def test_init_service_buses_returns_dict_without_raising(self):
        # 在无 zmq / 无总线服务的环境下，init_service_buses 必须安全返回且不为 None
        import os
        from backend.service_buses import init_service_buses
        src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))))
        buses = init_service_buses(src_dir)
        self.assertIsInstance(buses, dict)
        self.assertIn('thumbnail_bus', buses)
        self.assertIn('svc_mgr_bus', buses)
        self.assertIn('resource_bus', buses)


if __name__ == '__main__':
    unittest.main()
