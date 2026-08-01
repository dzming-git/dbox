# -*- coding: utf-8 -*-
"""backend.runtime 运行时注册中心单元测试。

验证单例注入 / 覆盖 / 默认值语义，无需应用上下文。
运行：python tests/test_runtime.py
"""
import os
import sys
import unittest

_SRC_WEB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'web'))
if _SRC_WEB not in sys.path:
    sys.path.insert(0, _SRC_WEB)

from backend.runtime import runtime, _Runtime, init  # noqa: E402


class TestRuntimeRegistry(unittest.TestCase):
    def tearDown(self):
        # 还原为干净的注册表，避免影响其它测试
        runtime.db = None
        runtime.app = None
        runtime.app_config = None
        runtime.thumbnail_bus = None
        runtime.resource_bus = None

    def test_defaults_none(self):
        r = _Runtime()
        self.assertIsNone(r.db)
        self.assertIsNone(r.app)
        self.assertIsNone(r.app_config)
        self.assertIsNone(r.thumbnail_bus)
        self.assertIsNone(r.resource_bus)

    def test_init_injects_only_provided(self):
        fake_db = object()
        init(db=fake_db)
        self.assertIs(runtime.db, fake_db)
        # 未提供的字段保持 None
        self.assertIsNone(runtime.app)
        self.assertIsNone(runtime.resource_bus)

    def test_init_overwrites_previous(self):
        init(db=object(), app_config={'a': 1})
        init(db=object(), app_config={'b': 2})
        self.assertEqual(runtime.app_config, {'b': 2})
        self.assertIsNotNone(runtime.db)
        # 未再次提供的 app 保持上一次注入值
        self.assertIsNone(runtime.app)

    def test_init_all_fields(self):
        vals = {k: object() for k in (
            'db', 'app', 'app_config', 'thumbnail_bus', 'resource_bus',
            'svc_mgr_bus', 'history_bus', 'collection_bus', 'search_bus')}
        init(**vals)
        for k, v in vals.items():
            self.assertIs(getattr(runtime, k), v)


if __name__ == '__main__':
    unittest.main(verbosity=2)
