# -*- coding: utf-8 -*-
"""扫描预演（dry-run）与撤销。

为什么需要
----------
扫描同步天然带破坏性：它会把「磁盘上看不见」的记录剔除。即便现在剔除动作
已经改成移入回收站（可恢复），让用户在**执行前**看到「这次会加多少、删多少」
仍然是必要的——尤其是当某个盘/目录临时不可见时，一次同步可能整批剔除，
而用户在界面上看到的只是「视频少了」。

两个能力：
1. preview()：只读预演，不改动任何数据；删除量异常时标记 need_confirm。
2. undo_recent()：把最近一段时间内被隔离（进回收站）的记录撤回来，
   默认只撤回「文件确实还在」的那些——真正丢失的不该被复活。
"""
import os
from datetime import datetime, timedelta

# 与 library_watcher._plan_orphan_deletions 保持一致的判据
THRESHOLD_ABS = 20
THRESHOLD_RATIO = 0.1


def plan_for_roots(roots, to_add, to_remove, in_db,
                   threshold_abs=THRESHOLD_ABS, threshold_ratio=THRESHOLD_RATIO):
    """纯计算：给出每个扫描根的预演结果。

    to_add / to_remove / in_db 都是 {root: 数量}。

    「删除量异常」要同时看绝对条数与占比：只看占比会让小库被误判（3/5 条
    就是 60%），只看绝对数又会让大库漏判（1000 条里删 200 条显然不对）。
    """
    plans = []
    total_add = 0
    total_remove = 0
    need_confirm = False
    for r in roots:
        add = int(to_add.get(r, 0) or 0)
        rm = int(to_remove.get(r, 0) or 0)
        dbn = int(in_db.get(r, 0) or 0)
        suspicious = rm > threshold_abs and rm > threshold_ratio * max(dbn, 1)
        plans.append({
            'root': r,
            'to_add': add,
            'to_remove': rm,
            'in_db': dbn,
            'need_confirm': suspicious,
        })
        total_add += add
        total_remove += rm
        need_confirm = need_confirm or suspicious
    return {
        'roots': plans,
        'to_add': total_add,
        'to_remove': total_remove,
        'need_confirm': need_confirm,
    }


def _targets(watcher, library_id=None):
    """收集预演目标。

    不给 library_id 时要覆盖**各资源库目标的并集**，而不是实时监控目标
    （`_collect_watch_targets`）：后者只包含开了实时监控的目录，会漏掉
    M:\\bang 这类只按库配置的路径——而按库扫描恰好扫的是那些目录，
    于是「全部预演」反而看不到真正会被改动的地方。
    """
    if library_id is not None:
        return watcher._targets_for_library(library_id) or []
    try:
        from core.models import ResourceLibrary
        lib_ids = [r[0] for r in ResourceLibrary.query.with_entities(
            ResourceLibrary.id).all()]
    except Exception:
        lib_ids = []
    out = []
    seen = set()
    for lid in lib_ids:
        for t in (watcher._targets_for_library(lid) or []):
            root = t[0] if isinstance(t, (list, tuple)) else t
            if root and root not in seen:
                seen.add(root)
                out.append(t)
    if not out:
        return watcher._collect_watch_targets() or []
    return out


def preview(library_id=None, watcher=None):
    """只读预演：枚举各监控目录并与库内记录比对，**不写入任何数据**。

    返回 plan（见 plan_for_roots）；监控器未初始化时返回 None。
    """
    if watcher is None:
        from library_watcher import get_watcher
        watcher = get_watcher()
    if not watcher:
        return None

    from core.models import db
    targets = _targets(watcher, library_id)
    if not targets:
        return {'roots': [], 'to_add': 0, 'to_remove': 0, 'need_confirm': False}

    to_add, to_remove, in_db = {}, {}, {}
    seen = set()
    for root, lib_id in targets:
        if not root or root in seen:
            continue
        seen.add(root)
        disk = watcher._collect_disk_videos(root, lib_id) or {}
        disk_norms = set(disk.keys())

        prefix = root if root.endswith(os.sep) else root + os.sep
        try:
            rows = db.session.execute(db.text(
                'SELECT ri.location FROM resource_index ri'
                ' JOIN videos v ON v.resource_index_id = ri.id'
                ' WHERE ri.kind = :k'
                '   AND (ri.location = :r OR ri.location LIKE :p)'
            ), {'k': 'video_file', 'r': root, 'p': prefix + '%'}).fetchall()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            rows = []

        db_norms = set()
        for (loc,) in rows:
            if loc:
                db_norms.add(os.path.normcase(os.path.abspath(loc)))

        to_add[root] = len(disk_norms - db_norms)
        to_remove[root] = len(db_norms - disk_norms)
        in_db[root] = len(db_norms)

    return plan_for_roots(list(seen), to_add, to_remove, in_db)


def undo_recent(minutes=60, require_file=True):
    """撤回最近 minutes 分钟内被隔离（进回收站）的记录。

    require_file=True 时只撤回**文件确实还在**的：真正丢失的文件不该被复活，
    否则列表里会出现打不开的条目。返回 {'restored': n, 'skipped_missing': m}。
    """
    from core.models import db, Video
    cutoff = datetime.utcnow() - timedelta(minutes=max(1, int(minutes)))
    try:
        rows = Video.query.filter(Video.in_trash == True,          # noqa: E712
                                  Video.trashed_at >= cutoff).all()
    except Exception:
        return {'restored': 0, 'skipped_missing': 0}

    restored = 0
    skipped = 0
    for v in rows:
        loc = None
        try:
            loc = (v.resource_index.location if v.resource_index else None)
        except Exception:
            loc = None
        loc = loc or getattr(v, 'local_path', None)
        if require_file and (not loc or not os.path.isfile(loc)):
            skipped += 1
            continue
        v.in_trash = False
        v.trashed_at = None
        restored += 1
    if restored:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return {'restored': 0, 'skipped_missing': skipped}
    return {'restored': restored, 'skipped_missing': skipped}
