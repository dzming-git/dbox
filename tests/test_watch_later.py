# -*- coding: utf-8 -*-
"""「稍后再看」软删除（防复活）集成测试。

验证根因修复：移除条目改为软删除（打墓碑 deleted_at），服务端权威记住「已删除」，
即使底层视频被恢复/重新入库、或客户端回推本地残留，已删条目也不再「复活」。

运行：python tests/test_watch_later.py
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

_SRC_WEB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'web'))
_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
for _p in (_SRC_WEB, _SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from flask import Flask  # noqa: E402
from core.models import db, WatchLater  # noqa: E402
import backend.api.watch_later_api as wl_api  # noqa: E402
from backend.trash import _tombstone_watch_later, _purge_watch_later  # noqa: E402


class WatchLaterSoftDeleteTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{self.db_path}'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(self.app)
        self.app_ctx = self.app.app_context()
        self.app_ctx.push()
        db.create_all()
        # 让交互键稳定为登录态 u1（跨设备一致），避免游客随机会话干扰断言
        wl_api.current_interaction_key = lambda: 'u1'
        self.app.register_blueprint(wl_api.bp)
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_ctx.pop()
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def _add(self, item_type='post', item_id='999', title='T'):
        return self.client.post(
            '/api/watch-later',
            json={'type': item_type, 'id': item_id, 'title': title})

    def _list(self):
        return self.client.get('/api/watch-later').get_json()

    def _remove(self, item_type='post', item_id='999'):
        return self.client.delete(f'/api/watch-later/{item_type}/{item_id}')

    def test_add_then_list_visible(self):
        self._add()
        data = self._list()
        self.assertTrue(data['success'])
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['items'][0]['id'], '999')

    def test_remove_tombstones_and_disappears_from_list(self):
        self._add()
        self._remove()
        # 列表已不含该条目
        self.assertEqual(self._list()['total'], 0)
        # 但行并未物理删除，只是打了墓碑
        row = WatchLater.query.filter_by(
            user_key='u1', item_type='post', item_id='999').first()
        self.assertIsNotNone(row)
        self.assertIsNotNone(row.deleted_at)

    def test_re_add_does_not_resurrect_tombstoned(self):
        self._add()
        self._remove()
        # 客户端把本地残留再次回推（重复 add），不应让已删条目复活
        self._add()
        self.assertEqual(self._list()['total'], 0)
        # 且不能产生重复行
        self.assertEqual(
            WatchLater.query.filter_by(
                user_key='u1', item_type='post', item_id='999').count(), 1)

    def test_clear_tombstones_all(self):
        self._add(item_id='1')
        self._add(item_id='2')
        self.client.delete('/api/watch-later')
        self.assertEqual(self._list()['total'], 0)
        # 两行均被打墓碑
        self.assertEqual(
            WatchLater.query.filter_by(user_key='u1').count(), 2)
        self.assertEqual(
            WatchLater.query.filter(WatchLater.deleted_at.is_(None)).count(), 0)

    def test_purge_removes_old_tombstones(self):
        self._add(item_id='1')
        self._remove(item_id='1')
        # 模拟一条早已过保留期的墓碑
        old = WatchLater.query.filter_by(
            user_key='u1', item_type='post', item_id='1').first()
        old.deleted_at = datetime.utcnow() - timedelta(days=31)
        db.session.commit()
        wl_api._purge_old_tombstones()
        self.assertEqual(
            WatchLater.query.filter_by(
                user_key='u1', item_type='post', item_id='1').count(), 0)

    def test_trash_tombstones_watch_later_video(self):
        # 模拟一个视频型条目，资源移入回收站时应一并打墓碑
        wl = WatchLater(user_key='u1', item_type='video',
                        item_id='abcdef' * 8, title='V')
        db.session.add(wl)
        db.session.commit()

        class _FakeVideo:
            hash = 'abcdef' * 8

        _tombstone_watch_later(_FakeVideo(), 'video')
        row = WatchLater.query.filter_by(
            user_key='u1', item_type='video', item_id='abcdef' * 8).first()
        self.assertIsNotNone(row.deleted_at)

    def test_purge_trash_removes_watch_later_video(self):
        wl = WatchLater(user_key='u1', item_type='video',
                        item_id='deadbeef' * 4, title='V')
        db.session.add(wl)
        db.session.commit()

        class _FakeVideo:
            hash = 'deadbeef' * 4

        _purge_watch_later(_FakeVideo(), 'video')
        self.assertEqual(
            WatchLater.query.filter_by(
                user_key='u1', item_type='video', item_id='deadbeef' * 4).count(), 0)


if __name__ == '__main__':
    unittest.main()
