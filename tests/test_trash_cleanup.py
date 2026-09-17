# -*- coding: utf-8 -*-
"""回收站超期自动清理单元测试（离线，monkeypatch 模型层）。

覆盖：pending_cleanup 只收超过保留期的项、按时间升序、owner 解析；
purge_expired_trash 真正清理（调用 purge_trash）且 dry_run 不删；
默认保留期（TRASH_RETENTION_DAYS）生效。

运行：python tests/test_trash_cleanup.py
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

_SRC_WEB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'web'))
if _SRC_WEB not in sys.path:
    sys.path.insert(0, _SRC_WEB)

import backend.trash as trash  # noqa: E402


class _User:
    def __init__(self, username):
        self.username = username


class _Row:
    def __init__(self, type_, hash_, title, owner_id, trashed_at):
        self.type = type_
        self.hash = hash_
        self.title = title
        self.owner_id = owner_id
        self.trashed_at = trashed_at


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def filter_by(self, **kw):
        return self

    def all(self):
        return self._rows


class TestTrashCleanup(unittest.TestCase):
    def setUp(self):
        now = datetime.utcnow()
        self.videos = [
            _Row('video', 'v_old', '老视频', 1, now - timedelta(days=40)),
            _Row('video', 'v_new', '新视频', 2, now - timedelta(days=5)),
            _Row('video', 'v_active', '仍在回收站但未超期', 3, now - timedelta(days=10)),
        ]
        self.galleries = [
            _Row('gallery', 'g_old', '老图集', 4, now - timedelta(days=60)),
        ]
        # monkeypatch 模型层，避免拉起完整 ORM / 数据库
        self._orig_video = trash.Video
        self._orig_gallery = trash.Gallery
        self._orig_db = trash.db
        self._orig_get = trash.get_trash_obj
        self._orig_purge = trash.purge_trash
        trash.Video = type('V', (), {'query': _Query(self.videos)})
        trash.Gallery = type('G', (), {'query': _Query(self.galleries)})
        trash.db = type('DB', (), {'session': type('S', (), {
            'get': staticmethod(lambda model, pk: _User('u%d' % pk))})})()
        self.purged = []
        trash.get_trash_obj = lambda kind, h: _Row(kind, h, 'x', 0, now)
        trash.purge_trash = lambda obj, kind: self.purged.append((kind, obj.hash))

    def tearDown(self):
        trash.Video = self._orig_video
        trash.Gallery = self._orig_gallery
        trash.db = self._orig_db
        trash.get_trash_obj = self._orig_get
        trash.purge_trash = self._orig_purge

    def test_pending_only_expired(self):
        items = trash.pending_cleanup(retention_days=30)
        hashes = {i['hash'] for i in items}
        self.assertEqual(hashes, {'v_old', 'g_old'},
                         '只应收录超过 30 天的项，未超期的不该进清单')
        # 按时间升序：最老的排第一
        self.assertEqual(items[0]['hash'], 'g_old')
        self.assertEqual(items[1]['hash'], 'v_old')

    def test_pending_owner_resolved(self):
        items = trash.pending_cleanup(retention_days=30)
        by = {i['hash']: i for i in items}
        self.assertEqual(by['v_old']['owner'], 'u1')
        self.assertEqual(by['g_old']['owner'], 'u4')

    def test_purge_expired_dry_run(self):
        res = trash.purge_expired_trash(retention_days=30, dry_run=True)
        self.assertEqual(res['purged'], 0)
        self.assertEqual(res['count'], 2)
        self.assertEqual(len(self.purged), 0, 'dry_run 不应真正删除')

    def test_purge_expired_real(self):
        res = trash.purge_expired_trash(retention_days=30, dry_run=False)
        self.assertEqual(res['purged'], 2)
        self.assertEqual(set(self.purged), {('video', 'v_old'), ('gallery', 'g_old')})

    def test_default_retention_respected(self):
        items = trash.pending_cleanup()
        hashes = {i['hash'] for i in items}
        self.assertNotIn('v_active', hashes)
        self.assertIn('v_old', hashes)


if __name__ == '__main__':
    unittest.main(verbosity=2)
