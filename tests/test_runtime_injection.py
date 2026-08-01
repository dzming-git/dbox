# -*- coding: utf-8 -*-
"""运行时注入（backend.runtime）解耦测试。

验证 helper 模块不再依赖 main 模块，而是通过注入的 runtime 单例读取
app_config / db / bus 等运行时资源；并固化若干 helper 纯函数行为。

注意：backend.system_helpers / library_helpers / thumbnail_helpers 在导入时
依赖 ``liblog`` 模块（由主程序在启动时注入），测试前需先在 sys.modules 注册
一个替身，否则无法导入。这不影响被测逻辑（我们验证的是 runtime 注入路径）。
"""
import os
import sys
import types
import unittest
from unittest import mock

# 让 src/web 可被导入
SRC_WEB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'web'))
if SRC_WEB not in sys.path:
    sys.path.insert(0, SRC_WEB)

# 在任何 backend helper 导入之前注册 fake liblog（避免 ModuleNotFoundError）
_fake_liblog = types.ModuleType('liblog')


def _fake_get_service_logger(*args, **kwargs):
    import logging
    return logging.getLogger('fake')

_fake_liblog.get_service_logger = _fake_get_service_logger
sys.modules.setdefault('liblog', _fake_liblog)


class TestRuntimeInjection(unittest.TestCase):
    def setUp(self):
        # 每个用例前重置 runtime，避免用例间串扰
        from backend.runtime import runtime
        runtime.db = None
        runtime.app = None
        runtime.app_config = {}
        runtime.thumbnail_bus = None
        runtime.resource_bus = None
        runtime.svc_mgr_bus = None
        runtime.history_bus = None
        runtime.collection_bus = None
        runtime.search_bus = None

    def test_helpers_do_not_import_main(self):
        """helper 模块不应直接依赖 main 模块（解耦的核心不变量）。"""
        helper_modules = [
            'backend.system_helpers',
            'backend.library_helpers',
            'backend.thumbnail_helpers',
        ]
        for mod in helper_modules:
            with self.subTest(module=mod):
                __import__(mod)
        # 即便 main 被间接导入，helper 自身也不应 import main
        for mod in helper_modules:
            m = sys.modules[mod]
            self.assertNotIn('main', m.__dict__, f'{mod} 仍直接引用 main 模块')

    def test_library_watchers_respect_config_disabled(self):
        """library_watch_enabled=False 时应跳过 watcher 启动。"""
        from backend.runtime import init
        init(app_config={'library_watch_enabled': False})

        import backend.library_helpers as lh
        started = {'called': False}

        def fake_start(**kwargs):
            started['called'] = True

        with mock.patch.dict(sys.modules, {'library_watcher': types.ModuleType('library_watcher')}):
            sys.modules['library_watcher'].start_library_watchers = fake_start
            lh._restart_library_watchers()
            self.assertFalse(started['called'], '配置禁用时不应启动 watcher')

    def test_library_watchers_start_when_enabled(self):
        """library_watch_enabled=True 时应调用 start_library_watchers。"""
        from backend.runtime import init
        init(app_config={'library_watch_enabled': True}, app=object(),
             resource_bus=object(), thumbnail_bus=object())

        import backend.library_helpers as lh
        started = {'called': False}

        def fake_start(**kwargs):
            started['called'] = True
            self.assertIn('app', kwargs)
            self.assertIn('resource_bus', kwargs)

        with mock.patch.dict(sys.modules, {'library_watcher': types.ModuleType('library_watcher')}):
            sys.modules['library_watcher'].start_library_watchers = fake_start
            lh._restart_library_watchers()
            self.assertTrue(started['called'], '配置启用时应启动 watcher')

    def test_runtime_single_instance_shared(self):
        """所有 helper 模块访问的是同一个 runtime 单例。"""
        from backend import runtime as rt1
        from backend import system_helpers, library_helpers, thumbnail_helpers
        self.assertIs(system_helpers.runtime, rt1.runtime)
        self.assertIs(library_helpers.runtime, rt1.runtime)
        self.assertIs(thumbnail_helpers.runtime, rt1.runtime)


class TestHelperPureFunctions(unittest.TestCase):
    def test_parse_log_line(self):
        """system_helpers.parse_log_line 解析格式稳定。"""
        from backend import system_helpers as sh
        line = '[2026-08-01 12:00:00] | [INFO] | [dplayer-web] | [扫描完成]'
        parsed = sh.parse_log_line(line, 'maintenance')
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['level'], 'INFO')
        self.assertEqual(parsed['service'], 'dplayer-web')
        self.assertEqual(parsed['content'], '扫描完成')
        self.assertEqual(parsed['timestamp'], '2026-08-01 12:00:00')

    def test_invalid_library_name_rejection(self):
        """library_helpers._INVALID_NAME_RE 拒绝非法字符。"""
        from backend import library_helpers as lh
        self.assertIsNotNone(lh._INVALID_NAME_RE.search('a/b'))
        self.assertIsNotNone(lh._INVALID_NAME_RE.search('a:b'))
        self.assertIsNone(lh._INVALID_NAME_RE.search('合法名称'))


if __name__ == '__main__':
    unittest.main()
