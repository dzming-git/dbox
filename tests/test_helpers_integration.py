# -*- coding: utf-8 -*-
"""backend.helpers 依赖数据库的集成测试。

使用真实的 core.models + 临时 SQLite + 应用上下文，验证
get_or_create_tag_by_path 等需要 db.session 的辅助函数行为正确，
并通过 backend.runtime 注入单例，与运行时调用路径保持一致。

运行：python tests/test_helpers_integration.py
"""
import os
import sys
import tempfile
import unittest

_SRC_WEB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'web'))
_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
for _p in (_SRC_WEB, _SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from flask import Flask  # noqa: E402
from core.models import db, Tag, ResourceIndex, Video, Gallery  # noqa: E402
from backend.helpers import get_or_create_tag_by_path  # noqa: E402
from backend.runtime import runtime  # noqa: E402


class HelpersIntegrationTestCase(unittest.TestCase):
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
        # 注入运行时单例（与 main 启动时的 runtime.init 一致）
        runtime.init(db=db)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_ctx.pop()
        runtime.db = None
        try:
            os.remove(self.db_path)
        except OSError:
            pass

    def test_get_or_create_tag_by_path_creates_hierarchy(self):
        tag = get_or_create_tag_by_path('/动物/狗/哈士奇', library_id=1)
        self.assertIsNotNone(tag)
        self.assertEqual(tag.name, '哈士奇')
        self.assertEqual(tag.path, '/动物/狗/哈士奇')
        # 父标签应被自动创建
        dog = Tag.query.filter(Tag.path == '/动物/狗').first()
        self.assertIsNotNone(dog)
        self.assertEqual(dog.parent_id, Tag.query.filter(Tag.path == '/动物').first().id)
        self.assertEqual(tag.parent_id, dog.id)
        self.assertEqual(Tag.query.count(), 3)

    def test_get_or_create_tag_by_path_idempotent(self):
        t1 = get_or_create_tag_by_path('/类型/电影')
        t2 = get_or_create_tag_by_path('/类型/电影')
        self.assertEqual(t1.id, t2.id)
        self.assertEqual(Tag.query.count(), 2)

    def test_get_or_create_tag_by_path_accepts_without_leading_slash(self):
        tag = get_or_create_tag_by_path('动漫/热血')
        self.assertEqual(tag.path, '/动漫/热血')
        self.assertEqual(Tag.query.count(), 2)

    def test_get_or_create_tag_by_path_empty_returns_none(self):
        self.assertIsNone(get_or_create_tag_by_path('   '))
        self.assertEqual(Tag.query.count(), 0)

    def test_get_or_create_tag_sets_library_id(self):
        tag = get_or_create_tag_by_path('/分类/A', library_id=42)
        self.assertEqual(tag.library_id, 42)


if __name__ == '__main__':
    unittest.main(verbosity=2)
