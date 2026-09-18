# -*- coding: utf-8 -*-
"""资源入库唯一入口的单元测试（离线，临时 sqlite + 真实模型）。

锁住的不变量：**一次入库必须同时产出「实体 + 索引 + 归属行」**。

历史事故：入库散在 4 处各自 `Video(...)` 建实体 —— 索引是 `Video.local_path`
的 setter **顺带**建的（且只在 library_id 已赋值时才带上，而构造参数赋值顺序
不确定），**归属行更是压根没人写**。归属行才是可见性的唯一真相源，于是出现
「有实体无归属」（历史上 1097 条视频）。

运行：python tests/test_resource_ingest.py
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


class TestResourceIngest(unittest.TestCase):
    def setUp(self):
        from flask import Flask
        from core.models import db
        self.tmp = tempfile.mkdtemp(prefix='dboxingest')
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(self.tmp, 't.db')
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(self.app)
        self.db = db
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        # 内容指纹只依赖「大小 + 头尾采样」，无需真实视频文件
        self.path = os.path.join(self.tmp, 'clip.mp4')
        with open(self.path, 'wb') as f:
            f.write(b'\x00' * 4096)

    def tearDown(self):
        try:
            self.ctx.pop()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ingest(self, **kw):
        from backend.resource_ingest import ingest_video_file
        return ingest_video_file(self.path, 1, **kw)

    def test_creates_index_and_membership(self):
        from core.models import ResourceModeMembership
        res = self._ingest()
        ri = res['resource_index']
        self.assertIsNotNone(ri.id)
        self.assertEqual(ri.kind, 'video_file')
        self.assertEqual(ri.library_id, 1,
                         '索引必须显式带 library_id（不能依赖 local_path setter 的赋值顺序）')
        self.assertEqual(res['video'].resource_index_id, ri.id,
                         '实体必须关联索引（消除「有实体无索引」）')
        modes = [m.mode for m in
                 ResourceModeMembership.query.filter_by(resource_index_id=ri.id).all()]
        self.assertEqual(modes, ['video'],
                         '必须有归属行——它是可见性的唯一真相源')

    def test_idempotent(self):
        from core.models import Video, ResourceIndex, ResourceModeMembership
        self._ingest()
        self._ingest()
        self.assertEqual(Video.query.count(), 1, '重复入库不应产生重复实体')
        self.assertEqual(ResourceIndex.query.count(), 1, '索引应复用')
        self.assertEqual(ResourceModeMembership.query.count(), 1, '归属行应幂等')

    def test_hidden_flag(self):
        res = self._ingest(hidden=True)
        self.assertTrue(res['resource_index'].hidden)

    def test_tags_applied_once(self):
        from core.models import VideoTag
        self._ingest(tags=['测试标签'])
        self._ingest(tags=['测试标签'])
        self.assertEqual(VideoTag.query.count(), 1, '标签不应重复关联')

    def test_explicit_title_wins(self):
        res = self._ingest(title='自定义标题')
        self.assertEqual(res['video'].title, '自定义标题')


if __name__ == '__main__':
    unittest.main(verbosity=2)
