# -*- coding: utf-8 -*-
"""数据库迁移执行器：每步独立事务、记录执行结果、失败不连累其它步骤。

背景
----
此前启动迁移是这样的形状：一大段 `try:` 里顺序跑若干步，末尾才 `commit()`。
后果是**前面任何一步抛异常，整段回滚，后面的步骤一次都没执行过**，而且只有
一行 WARN 日志——表现就是「某个功能莫名其妙一直不生效，日志里只有一句无关
痛痒的话」。真实案例：`migrate_resource_index` 的第 2 步查询了一个早已删除的
列（videos.local_path），异常导致第 4 步「模式归属回填」从未运行，全库视频
因此长期缺少归属行。

改造目标
--------
1. **步骤隔离**：每步独立事务，失败只影响自己；
2. **可观测**：结果写入 `schema_migrations` 表，成功过的步骤自动跳过，
   失败的步骤留痕并可查询；
3. **不静默**：启动末尾汇总，失败项打 WARN 并可从接口查看。

用法：
    from backend import migration_runner as mr
    mr.ensure_table()
    summary = mr.run_all([
        ('step_name', fn),
        ...
    ])
"""
from datetime import datetime

_db = None


def init(db_obj):
    """注入 SQLAlchemy 实例（测试或复用现成会话时用）。"""
    global _db
    _db = db_obj


def _session():
    global _db
    if _db is None:
        from core.models import db as _core_db
        _db = _core_db
    return _db


def ensure_table():
    """确保迁移记录表存在（用裸 SQL，便于在 create_all 之前调用）。"""
    db = _session()
    try:
        db.session.execute(db.text(
            'CREATE TABLE IF NOT EXISTS schema_migrations ('
            ' step TEXT PRIMARY KEY,'
            ' applied_at TIMESTAMP,'
            ' ok INTEGER,'
            ' note TEXT)'))
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


def _state(name):
    db = _session()
    try:
        row = db.session.execute(
            db.text('SELECT ok FROM schema_migrations WHERE step = :s'),
            {'s': name}).fetchone()
        return int(row[0]) if row is not None else None
    except Exception:
        return None


def _record(name, ok, note=''):
    db = _session()
    try:
        db.session.execute(
            db.text('INSERT OR REPLACE INTO schema_migrations'
                    ' (step, applied_at, ok, note) VALUES (:s, :t, :ok, :n)'),
            {'s': name, 't': datetime.utcnow(), 'ok': 1 if ok else 0,
             'n': (note or '')[:500]})
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


def run(name, fn):
    """执行一步迁移，返回 'applied' | 'skipped' | 'failed'。"""
    if _state(name) == 1:
        return 'skipped'
    try:
        fn()
    except Exception as e:
        _record(name, 0, '%s: %s' % (type(e).__name__, e))
        return 'failed'
    _record(name, 1, '')
    return 'applied'


def run_all(steps):
    """按序执行，返回汇总。

    steps: [(name, callable), ...]
    """
    result = {'applied': [], 'skipped': [], 'failed': {}}
    for name, fn in steps:
        state = run(name, fn)
        if state == 'applied':
            result['applied'].append(name)
        elif state == 'skipped':
            result['skipped'].append(name)
        else:
            result['failed'][name] = _last_error(name)
    return result


def _last_error(name):
    db = _session()
    try:
        row = db.session.execute(
            db.text('SELECT note FROM schema_migrations WHERE step = :s'),
            {'s': name}).fetchone()
        return (row[0] if row else '') or ''
    except Exception:
        return ''


def status():
    """列出已记录的迁移步骤（供健康检查展示）。"""
    db = _session()
    try:
        rows = db.session.execute(db.text(
            'SELECT step, applied_at, ok, note FROM schema_migrations'
            ' ORDER BY step')).fetchall()
    except Exception:
        return []
    out = []
    for r in rows:
        out.append({
            'step': r[0],
            'applied_at': str(r[1])[:19] if r[1] else None,
            'ok': bool(r[2]),
            'note': r[3] or '',
        })
    return out
