# -*- coding: utf-8 -*-
"""扫描预演的判定逻辑单元测试（纯计算，离线）。

重点是「删除量是否异常」的双重门槛：只看占比会误伤小库，只看绝对数会
漏掉大库。语义与 library_watcher._plan_orphan_deletions 保持一致。

运行：python tests/test_scan_preview.py
"""
import os
import sys
import unittest

_SRC_WEB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'web'))
_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
for _p in (_SRC_WEB, _SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backend.scan_preview import plan_for_roots  # noqa: E402


class TestPlanForRoots(unittest.TestCase):
    def test_normal_small_change(self):
        plan = plan_for_roots(['M:/a'], {'M:/a': 3}, {'M:/a': 2}, {'M:/a': 500})
        self.assertFalse(plan['need_confirm'])
        self.assertEqual(plan['to_add'], 3)
        self.assertEqual(plan['to_remove'], 2)

    def test_mass_removal_needs_confirm(self):
        """200/1000：绝对数与占比都过线 → 需要确认（盘不可见的典型表现）。"""
        plan = plan_for_roots(['M:/a'], {'M:/a': 0}, {'M:/a': 200}, {'M:/a': 1000})
        self.assertTrue(plan['need_confirm'])
        self.assertTrue(plan['roots'][0]['need_confirm'])

    def test_high_ratio_but_tiny_abs(self):
        """3/5 是 60%，但绝对数太小 —— 不该拦（否则小库每次都要确认）。"""
        plan = plan_for_roots(['M:/a'], {'M:/a': 0}, {'M:/a': 3}, {'M:/a': 5})
        self.assertFalse(plan['need_confirm'])

    def test_big_abs_but_low_ratio(self):
        """1000 条里删 25 条（2.5%）—— 正常整理，不该拦。"""
        plan = plan_for_roots(['M:/a'], {'M:/a': 0}, {'M:/a': 25}, {'M:/a': 1000})
        self.assertFalse(plan['need_confirm'])

    def test_any_root_suspicious_flags_overall(self):
        plan = plan_for_roots(['M:/a', 'M:/b'],
                              {'M:/a': 1, 'M:/b': 0},
                              {'M:/a': 2, 'M:/b': 300},
                              {'M:/a': 500, 'M:/b': 600})
        self.assertTrue(plan['need_confirm'], '任一根异常就应整体提示')
        self.assertFalse(plan['roots'][0]['need_confirm'])
        self.assertTrue(plan['roots'][1]['need_confirm'])
        self.assertEqual(plan['to_remove'], 302)

    def test_empty(self):
        plan = plan_for_roots([], {}, {}, {})
        self.assertEqual(plan['to_add'], 0)
        self.assertEqual(plan['to_remove'], 0)
        self.assertFalse(plan['need_confirm'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
