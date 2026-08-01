# -*- coding: utf-8 -*-
"""应用导入完整性测试。

作为 CI 的防回归底线：验证 main 模块可被成功导入（捕获导入期崩溃，如循环导入、
语法错误、缺失依赖），且蓝图注册完整（路由数量维持在合理下限之上）。

注意：导入 main 会触发 db.create_all() 写入默认数据库路径，该路径已被 .gitignore
忽略，不会进入版本库；CI runner 为临时文件系统，无副作用。
"""
import os
import sys
import unittest

SRC_WEB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'web'))
if SRC_WEB not in sys.path:
    sys.path.insert(0, SRC_WEB)


class TestAppImport(unittest.TestCase):
    def test_main_imports_and_registers_blueprints(self):
        import main
        rules = list(main.app.url_map.iter_rules())
        # 历史基线约 242 条路由；这里仅设合理下限，允许未来合理增减
        self.assertGreaterEqual(len(rules), 200,
                                '路由数量异常偏低，可能蓝图注册遗漏或导入崩溃')
        # 确认核心蓝图已注册（端点名前缀）
        endpoints = {getattr(r, 'endpoint', None) for r in rules}
        self.assertTrue(any(str(e).startswith('video_api') for e in endpoints),
                        'video_api 蓝图未注册')
        self.assertTrue(any(str(e).startswith('tag_api') for e in endpoints),
                        'tag_api 蓝图未注册')


if __name__ == '__main__':
    unittest.main()
