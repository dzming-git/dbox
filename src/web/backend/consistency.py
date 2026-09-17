# -*- coding: utf-8 -*-
"""资源索引一致性巡检。

背景
----
富化实体（videos / galleries）与 `resource_index` + `resource_memberships`
是两套写入，而归属行被定义为「单资源模式可见性的唯一真相源」。任意一侧漏写
就会漂移，且症状往往很间接——真实案例：迁移步骤静默失败导致全库视频缺归属行，
表现为「帖子引用选择器里一个视频都选不到」，排查很久才定位到是双写漂移。

因此需要一个**可定期跑的对账**：把漂移量化出来，并提供安全的修复。

原则（与 backup_api / db_snapshot 一致）：**只补不删**。
- 缺失的关联行可以补；
- 「有索引无实体」这类孤儿**只报告不清理**——是否删除交给用户判断，
  绝不自动永久删除数据。
"""
from datetime import datetime

_db = None


def init(db_obj):
    global _db
    _db = db_obj


def _session():
    global _db
    if _db is None:
        from core.models import db as _core_db
        _db = _core_db
    return _db


def _scalar(sql, params=None):
    db = _session()
    try:
        row = db.session.execute(db.text(sql), params or {}).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return -1        # -1 表示该查询无法执行（表/列不存在等）


def check():
    """只读巡检，返回各漂移项的数量。"""
    return {
        'video_without_index': _scalar(
            'SELECT COUNT(*) FROM videos WHERE resource_index_id IS NULL'),
        'video_without_membership': _scalar(
            'SELECT COUNT(*) FROM videos v'
            ' JOIN resource_index ri ON ri.id = v.resource_index_id'
            " WHERE NOT EXISTS (SELECT 1 FROM resource_memberships m"
            "                   WHERE m.resource_index_id = ri.id AND m.mode = 'video')"),
        'gallery_without_index': _scalar(
            'SELECT COUNT(*) FROM galleries WHERE resource_index_id IS NULL'),
        'gallery_without_membership': _scalar(
            'SELECT COUNT(*) FROM galleries g'
            ' JOIN resource_index ri ON ri.id = g.resource_index_id'
            " WHERE NOT EXISTS (SELECT 1 FROM resource_memberships m"
            "                   WHERE m.resource_index_id = ri.id AND m.mode = 'gallery')"),
        'orphan_video_index': _scalar(
            "SELECT COUNT(*) FROM resource_index ri WHERE ri.kind = 'video_file'"
            ' AND NOT EXISTS (SELECT 1 FROM videos v WHERE v.resource_index_id = ri.id)'),
        'orphan_gallery_index': _scalar(
            "SELECT COUNT(*) FROM resource_index ri WHERE ri.kind = 'gallery_folder'"
            ' AND NOT EXISTS (SELECT 1 FROM galleries g WHERE g.resource_index_id = ri.id)'),
        'membership_without_index': _scalar(
            'SELECT COUNT(*) FROM resource_memberships m'
            ' WHERE NOT EXISTS (SELECT 1 FROM resource_index ri'
            '                   WHERE ri.id = m.resource_index_id)'),
    }


def _has_column(table, col):
    db = _session()
    try:
        rows = db.session.execute(db.text('PRAGMA table_info(%s)' % table)).fetchall()
        return any(r[1] == col for r in rows)
    except Exception:
        return False


def repair():
    """补齐缺失的关联行；返回各项修复数量。

    能做：
      - 给「有索引无归属」的实体补 membership 行；
      - 若库里仍保留历史路径列（local_path / folder_path），据此重建索引。
    不做：
      - 不删除任何孤儿索引（只报告）。
    """
    db = _session()
    now = datetime.utcnow()
    fixed = {}

    # 顺序很关键：**先补索引、再补归属**。
    # 若先补归属，那些刚被重建出索引的实体就会漏掉归属行（巡检仍报缺失）。

    # 1) 历史路径列仍在的库：据此重建缺失的索引（模型早已不再映射这两列）
    legacy = {'videos': ('local_path', 'video_file'),
              'galleries': ('folder_path', 'gallery_folder')}
    for table, (col, kind) in legacy.items():
        key = '%s_index_rebound' % table.rstrip('s')
        if not _has_column(table, col):
            fixed[key] = 0
            continue
        try:
            res = db.session.execute(db.text(
                'INSERT INTO resource_index (kind, location, created_at, updated_at)'
                ' SELECT :kind, e.%s, :now, :now FROM %s e'
                ' WHERE e.resource_index_id IS NULL'
                "   AND e.%s IS NOT NULL AND e.%s != ''"
                % (col, table, col, col)), {'kind': kind, 'now': now})
            db.session.execute(db.text(
                'UPDATE %s SET resource_index_id ='
                ' (SELECT ri.id FROM resource_index ri'
                '  WHERE ri.location = %s.%s ORDER BY ri.id DESC LIMIT 1)'
                ' WHERE resource_index_id IS NULL' % (table, table, col)))
            db.session.commit()
            fixed[key] = int(res.rowcount or 0)
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            fixed[key] = -1

    # 2) 给「有索引无归属」的实体补 membership 行
    for mode, entity in (('video', 'videos'), ('gallery', 'galleries')):
        try:
            res = db.session.execute(db.text(
                'INSERT INTO resource_memberships'
                ' (resource_index_id, mode, position, created_at)'
                ' SELECT ri.id, :mode, 0, :now FROM %s e'
                ' JOIN resource_index ri ON ri.id = e.resource_index_id'
                ' WHERE NOT EXISTS (SELECT 1 FROM resource_memberships m'
                '                   WHERE m.resource_index_id = ri.id AND m.mode = :mode)'
                % entity), {'mode': mode, 'now': now})
            fixed['%s_membership_added' % mode] = int(res.rowcount or 0)
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            fixed['%s_membership_added' % mode] = -1

    return fixed


def summary_text(rep):
    """把巡检结果压成一行日志文本。"""
    return ', '.join('%s=%s' % (k, v) for k, v in (rep or {}).items())


# 仍被帖子引用的索引不能当作孤儿清理
_KIND_BY_MODE = {'video': 'video_file', 'gallery': 'gallery_folder'}


def _orphan_ids(kind):
    db = _session()
    try:
        rows = db.session.execute(db.text(
            'SELECT ri.id FROM resource_index ri'
            ' WHERE ri.kind = :k'
            '   AND NOT EXISTS (SELECT 1 FROM videos v WHERE v.resource_index_id = ri.id)'
            '   AND NOT EXISTS (SELECT 1 FROM galleries g WHERE g.resource_index_id = ri.id)'
            '   AND NOT EXISTS (SELECT 1 FROM post_refs pr WHERE pr.resource_index_id = ri.id)'
        ), {'k': kind}).fetchall()
        return [r[0] for r in rows]
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return []


def purge_orphans(confirm=False, mode='all', snapshot=True):
    """清理「没有任何实体、也没有帖子引用」的孤儿索引。

    破坏性操作，因此：
      - **默认试运行**（confirm=False）只返回将要删除的数量，不动数据；
      - 真正执行前先做一份数据库快照，出问题可回滚（snapshot=False 可关闭，
        供单元测试使用，避免测试碰到真实数据目录）；
      - 仍被帖子引用的一律跳过。
    """
    kinds = ([_KIND_BY_MODE[mode]] if mode in _KIND_BY_MODE
             else list(_KIND_BY_MODE.values()))
    plan = {}
    for k in kinds:
        ids = _orphan_ids(k)
        plan[k] = len(ids)
        if not confirm:
            continue
        if not ids:
            continue
        db = _session()
        if snapshot:
            try:
                from backend import db_snapshot
                db_snapshot.snapshot('pre-purge')
            except Exception:
                pass
        try:
            for i in range(0, len(ids), 200):
                chunk = ids[i:i + 200]
                db.session.execute(db.text(
                    'DELETE FROM resource_memberships WHERE resource_index_id IN :ids'
                ).bindparams(db.bindparam('ids', expanding=True)), {'ids': chunk})
                db.session.execute(db.text(
                    'DELETE FROM resource_index WHERE id IN :ids'
                ).bindparams(db.bindparam('ids', expanding=True)), {'ids': chunk})
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            plan[k] = -1
    return {'dry_run': not confirm, 'plan': plan}
