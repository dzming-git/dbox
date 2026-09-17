# -*- coding: utf-8 -*-
"""数据库快照：自动备份、保留策略、恢复。

为什么需要它
------------
主库承载着用户数年积累的**唯一索引**。而它可能被扫描逻辑、迁移或误操作
批量改写——真实事故：一次增量扫描把 218 条视频误判为「文件已删除」并
**硬删**（library_watcher.remove_video 走 db.session.delete，不进回收站），
只能靠重新扫描补回，历史/标签/合集等随之丢关联。

在那之前，任何"优化"都建立在沙子上：**能恢复到出事前**才是数据安全的底线。

设计
----
- 一致性拷贝：优先用 sqlite3 的 backup API（在线备份，服务无需停止）；
  失败时退回文件复制。
- 落盘：`{DATA_DIR}/backups/dbox_<YYYYmmdd_HHMMSS>_<reason>.db`
- 保留策略：最近 `keep_daily` 天每天一份 + 更早按周保留 `keep_weekly` 份，
  其余清理；另有硬上限防止磁盘被快照吃满。
- 恢复：先把当前库另存为**回滚点**，再用快照覆盖；服务需重启才生效
  （进程持有连接），本模块只负责换文件。

原则（与 backup_api 一致）：**只复制与恢复，绝不主动删数据**；
清理旧快照也只清理本模块自己产生的文件。
"""
import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime

from backend.paths import DATA_DIR, get_databases_dir

_LOCK = threading.Lock()
_DB_NAME = 'dbox.db'
HARD_MAX = 60                 # 快照数量的硬上限


def backups_dir():
    d = os.path.join(DATA_DIR, 'backups')
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def db_path():
    return os.path.join(get_databases_dir(), _DB_NAME)


def _log(msg, level='INFO'):
    try:
        from liblog import get_service_logger
        get_service_logger('dbox-web').maintenance(level, msg)
    except Exception:
        pass


def snapshot(reason='manual'):
    """创建一份数据库快照，返回元信息 dict；失败返回 None。"""
    src = db_path()
    if not os.path.isfile(src):
        return None
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    name = 'dbox_%s_%s.db' % (stamp, (reason or 'manual').replace(' ', '_'))
    dst = os.path.join(backups_dir(), name)
    with _LOCK:
        ok = False
        try:
            con_src = sqlite3.connect(src)
            con_dst = sqlite3.connect(dst)
            try:
                con_src.backup(con_dst)
                ok = True
            finally:
                con_dst.close()
                con_src.close()
        except Exception as e:
            _log(f'快照（backup API）失败，退回文件复制: {e}', 'WARN')
        if not ok:
            try:
                shutil.copy2(src, dst)
                ok = True
            except Exception as e:
                _log(f'创建数据库快照失败: {e}', 'ERROR')
                return None
    try:
        size = os.path.getsize(dst)
    except OSError:
        size = 0
    _log('已创建数据库快照 %s（%d KB，原因：%s）' % (name, size // 1024, reason))
    return {
        'name': name,
        'path': dst,
        'size': size,
        'reason': reason,
        'created_at': datetime.now().isoformat(timespec='seconds'),
    }


def list_snapshots():
    """列出快照（按时间倒序）。"""
    d = backups_dir()
    out = []
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for n in sorted(names, reverse=True):
        if not (n.startswith('dbox_') and n.endswith('.db')):
            continue
        p = os.path.join(d, n)
        try:
            st = os.stat(p)
        except OSError:
            continue
        reason = ''
        core = n[:-3]
        if '_' in core:
            reason = core.rsplit('_', 1)[-1]
        out.append({
            'name': n,
            'size': st.st_size,
            'reason': reason,
            'created_at': datetime.fromtimestamp(st.st_mtime).isoformat(timespec='seconds'),
        })
    return out


def prune(keep_daily=7, keep_weekly=8):
    """按「最近每天一份 + 更早每周一份」清理旧快照，返回删除数量。"""
    snaps = list_snapshots()
    if not snaps:
        return 0

    by_day = {}
    for s in snaps:
        by_day.setdefault(s['created_at'][:10], []).append(s)
    days = sorted(by_day.keys(), reverse=True)

    keep = set()
    for d in days[:keep_daily]:
        keep.add(by_day[d][0]['name'])          # 每天留最新的一份

    weeks = set()
    for d in days[keep_daily:]:
        try:
            wk = datetime.strptime(d, '%Y-%m-%d').isocalendar()[:2]
        except ValueError:
            continue
        if wk in weeks:
            continue
        weeks.add(wk)
        keep.add(by_day[d][0]['name'])
        if len(weeks) >= keep_weekly:
            break

    # 硬上限：保留策略算出的份数若超过 HARD_MAX，只留最新的那 HARD_MAX 份
    # （snaps 已是时间倒序）。注意是「封顶」而不是「低于上限就全留」——
    # 后者会让清理彻底失效（测试 test_keeps_daily_and_weekly 抓到过）。
    ordered_keep = [s['name'] for s in snaps if s['name'] in keep]
    keep = set(ordered_keep[:HARD_MAX])

    removed = 0
    for s in snaps:
        if s['name'] in keep:
            continue
        try:
            os.remove(os.path.join(backups_dir(), s['name']))
            removed += 1
        except OSError:
            pass
    if removed:
        _log('已清理旧快照 %d 份' % removed)
    return removed


def snapshot_if_new_day(reason='auto'):
    """今天还没有快照时才创建（供启动/定时调用，避免高频重复）。"""
    today = datetime.now().strftime('%Y%m%d')
    for s in list_snapshots():
        if s['name'].startswith('dbox_%s_' % today):
            return None
    return snapshot(reason)


def restore(name):
    """用快照覆盖当前库。先另存回滚点，失败还能再退回。

    返回 (ok, message)。注意：服务进程持有数据库连接，**需重启服务**生效。
    """
    src = os.path.join(backups_dir(), name)
    if not os.path.isfile(src):
        return False, '快照不存在：%s' % name
    dst = db_path()
    rollback = 'dbox_%s_prerestore.db' % datetime.now().strftime('%Y%m%d_%H%M%S')
    try:
        shutil.copy2(dst, os.path.join(backups_dir(), rollback))
    except Exception as e:
        return False, '创建回滚点失败（已中止，未改动主库）：%s' % e
    try:
        shutil.copy2(src, dst)
    except Exception as e:
        return False, '恢复失败：%s' % e
    _log('已从快照 %s 恢复主库（回滚点 %s）' % (name, rollback), 'WARN')
    return True, '已从 %s 恢复；回滚点：%s。请重启 DBox 服务后生效。' % (name, rollback)


def start_scheduler(interval_sec=3600, keep_daily=7, keep_weekly=8):
    """启动后台快照线程：每天一份 + 顺带清理。返回线程对象。"""
    def loop():
        # 启动先小睡，避开服务初始化高峰
        time.sleep(20)
        while True:
            try:
                snapshot_if_new_day('auto')
                prune(keep_daily, keep_weekly)
            except Exception:
                pass
            time.sleep(interval_sec)

    t = threading.Thread(target=loop, daemon=True, name='db-snapshot')
    t.start()
    return t
