# -*- coding: utf-8 -*-
"""回归测试：测试上下文下 paths 必须把数据区指到临时目录。

⚠️ 背景（2026-09-18 事故）：某测试 `import main` 后 `db.drop_all()` 把生产库整表删空。
包级 `tests/__init__.py` 只对 `python -m unittest tests.xxx` 生效；直接
`python tests/xxx.py` 会绕过它。 `backend/paths._ensure_test_isolation` 依据通用信号
（`sys.modules` 含单元测试 / 环境变量 `DBOX_TEST_MODE` / `sys.argv[0]` 落在 `tests/` 下）
强制隔离，覆盖两种跑法。

本测试锁定这个不变量：只要本文件以测试上下文加载，数据目录绝不解析到真实
（ProgramData）数据区。若有人移除 `_ensure_test_isolation`，这里会解析到生产数据区
并断言失败。
"""
import os
import sys
import unittest

# 本文件自身即满足测试上下文（顶部 import unittest + sys.argv 含 tests/），
# 确保 paths 模块在导入时已经触发隔离。若隔离被移除，这里会解析到真实数据区。
SRC_WEB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'web'))
if SRC_WEB not in sys.path:
    sys.path.insert(0, SRC_WEB)

import backend.paths as paths  # noqa: E402


class TestPathIsolation(unittest.TestCase):
    def test_test_context_uses_temp_data_dir(self):
        d = paths.get_user_data_dir()
        self.assertNotIn('ProgramData', d, '测试上下文下仍指向生产数据区，隔离失效')
        self.assertIn('dbox_tests_', d, '未落到测试临时目录')
        cfg = paths.get_user_config_dir()
        self.assertNotIn('ProgramData', cfg, '配置目录也应在临时区')
        self.assertIn('dbox_tests_', cfg)

    def test_normal_context_uses_real_dir(self):
        # 单独子进程模拟「正常启动」（无测试信号），必须解析到 ProgramData。
        import subprocess
        code = (
            'import sys; sys.path.insert(0,%r); sys.argv=["x","main.py"];'
            'import backend.paths as p; print(p.get_user_data_dir())'
        ) % SRC_WEB
        out = subprocess.run([sys.executable, '-c', code],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        self.assertTrue(out, '正常上下文解析失败：空输出')
        self.assertIn('ProgramData', out, '正常上下文未指向真实数据区')
