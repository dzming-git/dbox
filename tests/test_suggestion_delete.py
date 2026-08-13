# -*- coding: utf-8 -*-
"""反馈单删除功能测试。

验证两点：
1. 路由层：DELETE /api/suggestion/<id> 仅管理员可调用（非管理员 403、单号不存在 404、
   删除成功 200）；
2. 数据层：db_delete_issue 删除主单时级联清理其全部评论（cascade）。

数据层测试使用独立临时 SQLite，不触碰项目真实反馈库。
"""
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

SRC_WEB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'web'))
if SRC_WEB not in sys.path:
    sys.path.insert(0, SRC_WEB)

# liblog 由运行时注入，测试环境用桩模块模拟
if 'liblog' not in sys.modules:
    _liblog = types.ModuleType('liblog')
    _logging = __import__('logging')

    class _FakeServiceLogger:
        def __init__(self, name=''):
            self._name = name

        def maintenance(self, level, msg, *a):
            _logging.getLogger('test').info(msg)

        def info(self, msg, *a, **k):
            _logging.getLogger('test').info(msg)

        def warn(self, msg, *a, **k):
            _logging.getLogger('test').warning(msg)

        def error(self, msg, *a, **k):
            _logging.getLogger('test').error(msg)

        def debug(self, msg, *a, **k):
            _logging.getLogger('test').debug(msg)

    _liblog.get_service_logger = lambda name='': _FakeServiceLogger(name)
    sys.modules['liblog'] = _liblog


class TestDeleteIssueRoute(unittest.TestCase):
    def _make_app(self):
        import main
        return main.app

    def test_admin_can_delete(self):
        from backend.api import suggestion_api
        app = self._make_app()
        with mock.patch.object(suggestion_api, '_is_admin', return_value=True), \
                mock.patch.object(suggestion_api, 'db_delete_issue', return_value=True):
            client = app.test_client()
            resp = client.delete('/api/suggestion/202608130099')
            self.assertEqual(resp.status_code, 200)
            body = resp.get_json()
            self.assertTrue(body['success'])

    def test_non_admin_forbidden(self):
        from backend.api import suggestion_api
        app = self._make_app()
        with mock.patch.object(suggestion_api, '_is_admin', return_value=False):
            client = app.test_client()
            resp = client.delete('/api/suggestion/202608130099')
            self.assertEqual(resp.status_code, 403)

    def test_delete_missing_issue_404(self):
        from backend.api import suggestion_api
        app = self._make_app()
        with mock.patch.object(suggestion_api, '_is_admin', return_value=True), \
                mock.patch.object(suggestion_api, 'db_delete_issue', return_value=False):
            client = app.test_client()
            resp = client.delete('/api/suggestion/202608130000')
            self.assertEqual(resp.status_code, 404)


class TestDbDeleteIssue(unittest.TestCase):
    def setUp(self):
        from backend import feedback_db
        from sqlalchemy import create_engine
        self._mod = feedback_db
        self._tmp = tempfile.mkdtemp()
        uri = 'sqlite:///' + os.path.join(self._tmp, 'feedback.db')
        self._orig = (
            feedback_db._engine, feedback_db._SessionFactory, feedback_db._Session,
            feedback_db.FEEDBACK_DB_URI,
        )
        engine = create_engine(uri)
        feedback_db._engine = engine
        factory = feedback_db.sessionmaker(bind=engine)
        feedback_db._SessionFactory = factory
        feedback_db._Session = feedback_db.scoped_session(factory)
        feedback_db.FEEDBACK_DB_URI = uri
        feedback_db._Base.metadata.create_all(engine)

    def tearDown(self):
        (engine, factory, session, uri) = self._orig
        self._mod._engine = engine
        self._mod._SessionFactory = factory
        self._mod._Session = session
        self._mod.FEEDBACK_DB_URI = uri

    def test_delete_cascades_comments(self):
        from sqlalchemy import create_engine
        from backend.feedback_db import FeedbackIssue, FeedbackComment, db_delete_issue
        with self._mod._Session() as s:
            issue = FeedbackIssue(
                id='202608130001', title='测试', content='内容',
                status='open', submitter='游客')
            issue.comments.append(FeedbackComment(
                author='自动助手', author_role=2, content='分析'))
            s.add(issue)
            s.commit()
        # 删除前存在
        with self._mod._Session() as s:
            self.assertEqual(s.query(FeedbackComment).count(), 1)
        # 执行删除
        self.assertTrue(db_delete_issue('202608130001'))
        # 删除后主单与评论一并消失
        with self._mod._Session() as s:
            self.assertIsNone(s.get(FeedbackIssue, '202608130001'))
            self.assertEqual(s.query(FeedbackComment).count(), 0)
        # 重复删除不存在的单返回 False
        self.assertFalse(db_delete_issue('202608130001'))


if __name__ == '__main__':
    unittest.main()
