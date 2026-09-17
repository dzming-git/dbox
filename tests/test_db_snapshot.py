# -*- coding: utf-8 -*-
"""数据库快照模块单元测试（离线，不依赖运行中的服务）。

覆盖：创建、列表、同日去重、保留策略、恢复与回滚点。

运行：python tests/test_db_snapshot.py
"""
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime

# 与 tests/test_backend_helpers.py 一致：backend.* 在 src/web，liblog 在 src
_SRC_WEB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'web'))
_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
for _p in (_SRC_WEB, _SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backend import db_snapshot  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='dboxsnap')
        self.back = os.path.join(self.tmp, 'backups')
        self.dbfile = os.path.join(self.tmp, 'dbox.db')
        os.makedirs(self.back, exist_ok=True)
        with open(self.dbfile, 'wb') as f:
            f.write(b'sqlite-fake')
        # 隔离真实数据目录：只允许操作临时目录
        self._orig_backups = db_snapshot.backups_dir
        self._orig_db = db_snapshot.db_path
        db_snapshot.backups_dir = lambda: self.back
        db_snapshot.db_path = lambda: self.dbfile

    def tearDown(self):
        db_snapshot.backups_dir = self._orig_backups
        db_snapshot.db_path = self._orig_db
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, name, when):
        p = os.path.join(self.back, name)
        with open(p, 'wb') as f:
            f.write(b'x' * 16)
        ts = when.timestamp()
        os.utime(p, (ts, ts))
        return p

    def _names(self):
        return [s['name'] for s in db_snapshot.list_snapshots()]


class TestSnapshot(_Base):
    def test_create_and_list(self):
        info = db_snapshot.snapshot('manual')
        self.assertIsNotNone(info)
        self.assertTrue(info['name'].startswith('dbox_'))
        self.assertTrue(info['name'].endswith('_manual.db'))
        self.assertTrue(os.path.isfile(info['path']))
        names = self._names()
        self.assertEqual(len(names), 1)
        self.assertEqual(db_snapshot.list_snapshots()[0]['reason'], 'manual')

    def test_new_day_dedup(self):
        first = db_snapshot.snapshot_if_new_day('auto')
        self.assertIsNotNone(first)
        second = db_snapshot.snapshot_if_new_day('auto')   # 同一天 → 不重复
        self.assertIsNone(second)
        self.assertEqual(len(self._names()), 1)

    def test_snapshot_when_db_missing(self):
        os.remove(self.dbfile)
        self.assertIsNone(db_snapshot.snapshot('manual'))


class TestPrune(_Base):
    def test_keeps_daily_and_weekly(self):
        # 1 月 1~30 日每天一份
        for d in range(1, 31):
            self._touch('dbox_202601%02d_120000_auto.db' % d,
                        datetime(2026, 1, d, 12, 0, 0))
        # 最近一天再多几份，验证「每天只留最新一份」
        self._touch('dbox_20260130_130000_auto.db', datetime(2026, 1, 30, 13, 0, 0))
        self._touch('dbox_20260130_140000_auto.db', datetime(2026, 1, 30, 14, 0, 0))
        before = len(self._names())
        self.assertEqual(before, 32)

        removed = db_snapshot.prune(keep_daily=7, keep_weekly=2)
        names = self._names()
        # 7 天每天一份 + 更早 2 周各一份 = 9
        self.assertEqual(len(names), 9, '保留数量应为 9，实际 %d' % len(names))
        self.assertEqual(removed, before - 9)
        # 最新那天必须留下，且只留最新的一份
        self.assertIn('dbox_20260130_140000_auto.db', names)
        self.assertNotIn('dbox_20260130_130000_auto.db', names)
        self.assertNotIn('dbox_20260130_120000_auto.db', names)
        # 最老的那天应被清理
        self.assertNotIn('dbox_20260101_120000_auto.db', names)

    def test_prune_empty(self):
        self.assertEqual(db_snapshot.prune(), 0)


class TestRestore(_Base):
    def test_restore_swaps_and_makes_rollback(self):
        # 造一个"旧快照"
        old = self._touch('dbox_20260101_120000_auto.db', datetime(2026, 1, 1, 12, 0, 0))
        with open(old, 'wb') as f:
            f.write(b'OLD-SNAPSHOT')
        # 当前库
        with open(self.dbfile, 'wb') as f:
            f.write(b'CURRENT-DB')

        ok, msg = db_snapshot.restore('dbox_20260101_120000_auto.db')
        self.assertTrue(ok, msg)
        with open(self.dbfile, 'rb') as f:
            self.assertEqual(f.read(), b'OLD-SNAPSHOT')
        # 回滚点必须存在
        rollback = [n for n in self._names() if 'prerestore' in n]
        self.assertEqual(len(rollback), 1, '恢复前应先存回滚点')

    def test_restore_missing_snapshot(self):
        ok, msg = db_snapshot.restore('nope.db')
        self.assertFalse(ok)
        self.assertIn('快照不存在', msg)


if __name__ == '__main__':
    unittest.main(verbosity=2)
