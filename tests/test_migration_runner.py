# -*- coding: utf-8 -*-
"""迁移执行器单元测试（离线，临时 sqlite）。

核心断言：**一步失败不得连累后续步骤**，且结果可查询、成功过的步骤会跳过。
这正是此前「整段 try + 末尾 commit」踩的坑（前一步异常导致后面全部未执行）。

运行：python tests/test_migration_runner.py
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

from backend import migration_runner as mr  # noqa: E402


def _make_db():
    from flask import Flask
    from flask_sqlalchemy import SQLAlchemy
    tmp = tempfile.mkdtemp(prefix='dboxmig')
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(tmp, 't.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db = SQLAlchemy(app)
    return app, db, tmp


class TestMigrationRunner(unittest.TestCase):
    def setUp(self):
        self.app, self.db, self.tmp = _make_db()
        mr.init(self.db)
        self.ctx = self.app.app_context()
        self.ctx.push()
        mr.ensure_table()

    def tearDown(self):
        try:
            self.ctx.pop()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_applied_then_skipped(self):
        calls = []

        def step():
            calls.append(1)

        self.assertEqual(mr.run('s1', step), 'applied')
        self.assertEqual(mr.run('s1', step), 'skipped')
        self.assertEqual(len(calls), 1, '已成功的步骤不应重复执行')

    def test_failure_is_isolated(self):
        """一步失败不应影响后续步骤（旧实现里会整段回滚）。"""
        ok = []

        def boom():
            raise RuntimeError('模拟迁移失败')

        def after():
            ok.append(1)

        summary = mr.run_all([('bad', boom), ('good', after)])
        self.assertEqual(summary['applied'], ['good'])
        self.assertIn('bad', summary['failed'])
        self.assertEqual(len(ok), 1)
        self.assertIn('RuntimeError', summary['failed']['bad'])

    def test_failed_step_can_succeed_later(self):
        state = {'n': 0}

        def flaky():
            state['n'] += 1
            if state['n'] == 1:
                raise RuntimeError('第一次失败')

        self.assertEqual(mr.run('flaky', flaky), 'failed')
        self.assertEqual(mr.run('flaky', flaky), 'applied', '修复后应能补跑')
        statuses = {i['step']: i['ok'] for i in mr.status()}
        self.assertTrue(statuses.get('flaky'))

    def test_status_records(self):
        mr.run('a', lambda: None)
        mr.run('b', lambda: (_ for _ in ()).throw(ValueError('x')))
        st = {i['step']: i for i in mr.status()}
        self.assertTrue(st['a']['ok'])
        self.assertFalse(st['b']['ok'])
        self.assertIn('ValueError', st['b']['note'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
