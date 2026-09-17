# -*- coding: utf-8 -*-
"""资源索引一致性巡检单元测试（离线，临时 sqlite）。

覆盖：各类漂移能被检出；修复只补不删（孤儿索引不会被清理）。

运行：python tests/test_consistency.py
"""
import os
import shutil
import sys
import tempfile
import unittest

_SRC_WEB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'web'))
_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
for _p in (_SRC_WEB, _SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backend import consistency as cons  # noqa: E402

DDL = [
    "CREATE TABLE videos (id INTEGER PRIMARY KEY, resource_index_id INTEGER, local_path TEXT)",
    "CREATE TABLE galleries (id INTEGER PRIMARY KEY, resource_index_id INTEGER, folder_path TEXT)",
    "CREATE TABLE resource_index (id INTEGER PRIMARY KEY, kind TEXT, location TEXT,"
    " created_at TIMESTAMP, updated_at TIMESTAMP)",
    "CREATE TABLE resource_memberships (id INTEGER PRIMARY KEY, resource_index_id INTEGER,"
    " mode TEXT, position INTEGER, note TEXT, collection_id INTEGER, created_by INTEGER,"
    " created_at TIMESTAMP)",
    "CREATE TABLE post_refs (id INTEGER PRIMARY KEY, post_id INTEGER, resource_index_id INTEGER)",
    "CREATE TABLE galleries_dummy (x INTEGER)",
]


def _make_db():
    from flask import Flask
    from flask_sqlalchemy import SQLAlchemy
    tmp = tempfile.mkdtemp(prefix='dboxcons')
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(tmp, 't.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db = SQLAlchemy(app)
    return app, db, tmp


class TestConsistency(unittest.TestCase):
    def setUp(self):
        self.app, self.db, self.tmp = _make_db()
        cons.init(self.db)
        self.ctx = self.app.app_context()
        self.ctx.push()
        for ddl in DDL:
            self.db.session.execute(self.db.text(ddl))
        self.db.session.commit()

    def tearDown(self):
        try:
            self.ctx.pop()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _exec(self, sql, params=None):
        self.db.session.execute(self.db.text(sql), params or {})
        self.db.session.commit()

    def _seed(self):
        # 有索引、无归属的视频
        self._exec("INSERT INTO resource_index (id, kind, location) VALUES (1,'video_file','/a.mp4')")
        self._exec('INSERT INTO videos (id, resource_index_id) VALUES (1, 1)')
        # 无索引、但历史路径列仍在的视频
        self._exec("INSERT INTO videos (id, local_path) VALUES (2, '/b.mp4')")
        # 孤儿索引（没有实体指向它）
        self._exec("INSERT INTO resource_index (id, kind, location) VALUES (9,'video_file','/gone.mp4')")

    def test_check_detects_drift(self):
        self._seed()
        rep = cons.check()
        self.assertEqual(rep['video_without_membership'], 1)
        self.assertEqual(rep['video_without_index'], 1)
        self.assertEqual(rep['orphan_video_index'], 1)

    def test_repair_only_adds(self):
        self._seed()
        before = cons.check()
        fixed = cons.repair()
        after = cons.check()

        self.assertEqual(after['video_without_membership'], 0, '缺失的归属行应被补上')
        self.assertEqual(after['video_without_index'], 0, '能按历史路径重建索引的应补上')
        # 1 条本来就有索引 + 1 条重建索引后才补上 → 共 2 条
        self.assertEqual(fixed['video_membership_added'], 2,
                         '重建索引后仍要补上归属（顺序不能颠倒）')

        # 关键契约：孤儿索引只报告、绝不自动删除
        self.assertEqual(before['orphan_video_index'], after['orphan_video_index'],
                         '巡检修复不得删除任何数据（孤儿索引保持原样）')

    def test_healthy_when_clean(self):
        rep = cons.check()
        self.assertEqual(sum(1 for v in rep.values() if v and v > 0), 0)

    def test_summary_text(self):
        text = cons.summary_text({'a': 1, 'b': 0})
        self.assertIn('a=1', text)


class TestPurgeOrphans(unittest.TestCase):
    def setUp(self):
        self.app, self.db, self.tmp = _make_db()
        cons.init(self.db)
        self.ctx = self.app.app_context()
        self.ctx.push()
        for ddl in DDL:
            self.db.session.execute(self.db.text(ddl))
        self.db.session.commit()

    def tearDown(self):
        try:
            self.ctx.pop()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _exec(self, sql, params=None):
        self.db.session.execute(self.db.text(sql), params or {})
        self.db.session.commit()

    def _seed(self):
        # 10：无人引用的孤儿；11：仍被帖子引用，不能删
        self._exec("INSERT INTO resource_index (id,kind,location) VALUES (10,'video_file','/x.mp4')")
        self._exec("INSERT INTO resource_index (id,kind,location) VALUES (11,'video_file','/y.mp4')")
        self._exec('INSERT INTO post_refs (id, post_id, resource_index_id) VALUES (1, 1, 11)')

    def test_dry_run_by_default(self):
        self._seed()
        res = cons.purge_orphans(snapshot=False)
        self.assertTrue(res['dry_run'])
        self.assertEqual(res['plan']['video_file'], 1)
        # 试运行不得改动数据
        self.assertEqual(cons.check()['orphan_video_index'], 2)

    def test_confirm_deletes_only_unreferenced(self):
        self._seed()
        res = cons.purge_orphans(confirm=True, snapshot=False)
        self.assertFalse(res['dry_run'])
        self.assertEqual(res['plan']['video_file'], 1)
        left = self.db.session.execute(self.db.text(
            'SELECT id FROM resource_index ORDER BY id')).fetchall()
        self.assertEqual([r[0] for r in left], [11], '被帖子引用的索引必须保留')


if __name__ == '__main__':
    unittest.main(verbosity=2)
