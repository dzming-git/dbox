# -*- coding: utf-8 -*-
"""用户状态合并策略（state_merge）纯函数单元测试。

重点锁住一类回归：union_by_id / max 的语义都依赖 `_sortable_ts` 把 order 解析成
可比较数值。若某种时间格式解析失败而统一退化成 -inf，整批条目的排序键就全部相等，
「倒序封顶」退化成「按插入序截断」——留下的永远是最旧的一批、新条目被截掉，
且每次合并都把这份只含旧内容的快照写回，覆盖客户端刚拿到的新数据
（前端表现为列表长期停在很久以前、最新内容永远补不进来）。

运行：python -m unittest tests.test_user_state_merge
"""
import os
import sys
import unittest

_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from web.core.state_merge import _sortable_ts, merge_union_by_id, merge_max  # noqa: E402


class TestSortableTs(unittest.TestCase):
    def test_iso_and_epoch_unchanged(self):
        self.assertEqual(_sortable_ts('2026-09-19T08:29:44Z'),
                         _sortable_ts('2026-09-19T08:29:44+00:00'))
        self.assertEqual(_sortable_ts(1789809251), 1789809251.0)
        self.assertEqual(_sortable_ts('1789809251'), 1789809251.0)

    def test_rfc822_style_date(self):
        # 「星期 月 日 时:分:秒 时区 年」：信息流类时间字段的常见格式，必须可排序
        self.assertEqual(_sortable_ts('Sat Sep 19 08:29:44 +0000 2026'),
                         _sortable_ts('2026-09-19T08:29:44Z'))
        self.assertGreater(_sortable_ts('Sat Sep 19 08:29:44 +0000 2026'),
                           _sortable_ts('Sat Sep 19 08:00:00 +0000 2026'))

    def test_unparsable_is_negative_inf(self):
        self.assertEqual(_sortable_ts('not-a-date'), float('-inf'))
        self.assertEqual(_sortable_ts(''), float('-inf'))
        self.assertEqual(_sortable_ts(None), float('-inf'))


class TestUnionByIdCap(unittest.TestCase):
    @staticmethod
    def _item(i, stamp):
        return {'id': str(i), 'order': stamp}

    def test_cap_keeps_newest_not_oldest(self):
        # 旧值塞满 cap、新值更新 —— 封顶后必须留下新值，而不是最旧的那批旧值
        old = [self._item(i, 'Tue Sep 01 10:00:00 +0000 2026') for i in range(10)]
        new = [self._item('newest', 'Sat Sep 19 03:07:00 +0000 2026')]
        merged, changed = merge_union_by_id(old, new, cap=10)
        self.assertTrue(changed)
        self.assertEqual(len(merged), 10)
        self.assertEqual(merged[0]['id'], 'newest')
        self.assertTrue(any(it['id'] == 'newest' for it in merged))

    def test_same_id_keeps_newer_order(self):
        old = [{'id': 'a', 'order': 'Sat Sep 19 01:00:00 +0000 2026', 'text': 'old'}]
        new = [{'id': 'a', 'order': 'Sat Sep 19 02:00:00 +0000 2026', 'text': 'new'}]
        merged, _ = merge_union_by_id(old, new, cap=10)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['text'], 'new')

    def test_tombstone_deletes(self):
        old = [{'id': 'a', 'order': 'Sat Sep 19 01:00:00 +0000 2026'}]
        new = [{'id': 'a', '_deleted': True}]
        merged, _ = merge_union_by_id(old, new, cap=10)
        self.assertEqual(merged, [])


class TestMergeMax(unittest.TestCase):
    def test_monotonic_with_rfc822_order(self):
        # max 策略同样依赖 _sortable_ts：解析失败会让「只前进」退化成「永不前进」
        older = 'Sat Sep 19 01:00:00 +0000 2026'
        newer = 'Sat Sep 19 02:00:00 +0000 2026'
        val, changed = merge_max(older, newer)
        self.assertTrue(changed)
        self.assertEqual(val, newer)
        val2, changed2 = merge_max(newer, older)
        self.assertFalse(changed2)
        self.assertEqual(val2, newer)


if __name__ == '__main__':
    unittest.main()
