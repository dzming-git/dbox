# -*- coding: utf-8 -*-
"""备份 / 迁移 / 导出。

用户把数年积累托付给本地库，最深的顾虑是「哪天它没了」。这里提供两类能力：

1. **导出**：把元数据（视频索引、标签、合集、稍后再看、观看进度）与
   「在库里但文件已不在」的清单导成 JSON / M3U，通用格式、留得住也带得走。
2. **换机迁移**：目录整体搬家后按前缀批量重映射——这是换机最常见的场景，
   逐条改不现实。默认试运行，先给人看清楚会改什么。

原则：**只导出与重指向，绝不删数据**；破坏性决策一律交给用户。
"""
import io
import json
import os
from datetime import datetime

from flask import Blueprint, request, jsonify, send_file, g, Response

from core.models import (
    db, Video, VideoTag, Tag, Collection, ResourceModeMembership,
    ResourceIndex, WatchLater, WatchHistory,
)
from backend.access import admin_required, current_interaction_key
from liblog import get_service_logger

log = get_service_logger('dbox-web')

bp = Blueprint('backup', __name__)

EXPORT_KINDS = ('videos', 'tags', 'collections', 'watchlater', 'history',
                'missing', 'all')


def _iso(dt):
    return dt.isoformat() + 'Z' if isinstance(dt, datetime) else None


def _location(v):
    return (v.resource_index.location if v.resource_index else None)


def _visible_videos():
    """备份范围内的视频：**全部**，不受资源库启用状态限制。

    为什么不用列表接口的可见性过滤：可见性会剔除「所属资源库已停用」的记录，
    而停用库的记录恰恰是备份最该留底的那一批（本机就有 888 条里 817 条属于
    停用库，按可见性导出只有 70 条，等于什么都没备份）。本蓝图的所有接口都是
    @admin_required，导出全量不会造成越权；浏览类接口仍按可见性过滤。
    """
    return Video.query.options(db.joinedload(Video.resource_index))


def _video_row(v, with_tags=True):
    row = {
        'hash': v.hash,
        'title': v.title,
        'path': _location(v),
        'library_id': v.library_id,
        'duration': v.duration,
        'file_size': v.file_size,
        'created_at': _iso(v.created_at),
        'updated_at': _iso(v.updated_at),
    }
    if with_tags:
        names = (
            db.session.query(Tag.name)
            .join(VideoTag, VideoTag.tag_id == Tag.id)
            .filter(VideoTag.video_id == v.id)
            .all()
        )
        row['tags'] = [n[0] for n in names]
    return row


def _dump(kind):
    """按类型产出可序列化的导出内容。"""
    user_key = current_interaction_key()

    if kind == 'videos':
        return {'kind': 'videos', 'items': [_video_row(v) for v in _visible_videos().all()]}

    if kind == 'tags':
        return {
            'kind': 'tags',
            'items': [{
                'name': t.name,
                'path': t.path,
                'category': t.category,
                'qualifiers': t.qualifiers,
                'library_id': t.library_id,
            } for t in Tag.query.all()],
        }

    if kind == 'collections':
        out = []
        for c in Collection.query.all():
            members = (
                db.session.query(ResourceIndex.location)
                .join(ResourceModeMembership,
                      ResourceModeMembership.resource_index_id == ResourceIndex.id)
                .filter(ResourceModeMembership.collection_id == c.id)
                .all()
            )
            out.append({
                'id': c.id,
                'name': c.name,
                'mode': c.mode,
                'library_id': c.library_id,
                'created_at': _iso(c.created_at),
                'items': [m[0] for m in members if m[0]],
            })
        return {'kind': 'collections', 'items': out}

    if kind == 'watchlater':
        rows = (WatchLater.query.filter_by(user_key=user_key).all() if user_key else [])
        return {'kind': 'watchlater', 'items': [r.to_dict() for r in rows]}

    if kind == 'history':
        rows = (WatchHistory.query.filter_by(user_key=user_key)
                .order_by(WatchHistory.watched_at.desc()).all() if user_key else [])
        return {'kind': 'history', 'items': [r.to_dict() for r in rows]}

    if kind == 'missing':
        # 「在库里但文件已不在」：换机 / 误删后最需要的一份对账清单
        items = []
        for v in _visible_videos().all():
            p = _location(v)
            if not p or not os.path.exists(p):
                row = _video_row(v, with_tags=False)
                row['reason'] = '文件已不在磁盘'
                items.append(row)
        return {'kind': 'missing', 'items': items}

    if kind == 'all':
        data = {'kind': 'all', 'exported_at': _iso(datetime.utcnow())}
        for k in ('videos', 'tags', 'collections', 'watchlater', 'history', 'missing'):
            try:
                data[k] = _dump(k)['items']
            except Exception as e:
                log.debug('ERROR', f'导出 {k} 失败: {e}')
                data[k] = []
        return data

    return None


@bp.route('/api/admin/backup/export', methods=['GET'])
@admin_required
def backup_export():
    """导出元数据为 JSON 文件。

    query: what=videos|tags|collections|watchlater|history|missing|all
    """
    kind = request.args.get('what', 'all')
    if kind not in EXPORT_KINDS:
        return jsonify({'success': False, 'message': '不支持的导出类型'}), 400
    try:
        data = _dump(kind)
    except Exception as e:
        log.debug('ERROR', f'导出 {kind} 失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500
    if data is None:
        return jsonify({'success': False, 'message': '不支持的导出类型'}), 400

    payload = json.dumps(data, ensure_ascii=False, indent=2)
    filename = f'dbox-{kind}-{datetime.utcnow().strftime("%Y%m%d-%H%M%S")}.json'
    return Response(
        payload,
        mimetype='application/json; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@bp.route('/api/admin/backup/remap-prefix', methods=['POST'])
@admin_required
def remap_prefix():
    """按前缀批量重映射路径（换机 / 目录搬家）。

    body: { old_prefix, new_prefix, dry_run }
    默认 dry_run=true：先返回「会改多少 + 前几条示例」，确认后再真实执行。

    只改资源索引里的位置（引用它的实体自动跟随），不移动任何文件。
    """
    data = request.get_json(silent=True) or {}
    old_prefix = (data.get('old_prefix') or '').strip()
    new_prefix = (data.get('new_prefix') or '').strip()
    dry_run = data.get('dry_run')
    dry_run = True if dry_run is None else bool(dry_run)

    if not old_prefix or not new_prefix:
        return jsonify({'success': False, 'message': '缺少旧前缀或新前缀'}), 400

    old_norm = os.path.normcase(os.path.abspath(old_prefix))
    new_abs = os.path.abspath(new_prefix)

    matched, would_change, missing_target, samples = 0, 0, 0, []
    try:
        for v in _visible_videos().all():
            p = _location(v)
            if not p:
                continue
            if not os.path.normcase(os.path.abspath(p)).startswith(old_norm):
                continue
            matched += 1
            rel = os.path.relpath(p, os.path.abspath(old_prefix))
            target = os.path.normpath(os.path.join(new_abs, rel))
            if not os.path.exists(target):
                missing_target += 1
                if len(samples) < 5:
                    samples.append({'title': v.title, 'from': p, 'to': target,
                                    'ok': False})
                continue
            would_change += 1
            if len(samples) < 5:
                samples.append({'title': v.title, 'from': p, 'to': target, 'ok': True})
            if not dry_run:
                v.resource_index.location = target
                db.session.add(v.resource_index)
        if not dry_run:
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f'按前缀重映射失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500

    return jsonify({
        'success': True,
        'dry_run': dry_run,
        'matched': matched,
        'updated': 0 if dry_run else would_change,
        'would_update': would_change,
        'missing_target': missing_target,
        'samples': samples,
    })


# ---------------- 数据库快照（可回滚的底线能力） ----------------
# 导出是「带得走」，快照是「回得来」。索引可能被扫描/迁移/误操作批量改写
# （真实事故见 backend/db_snapshot.py 的模块说明），只有能恢复到出事前，
# 才谈得上数据安全。因此这里补齐：查看 / 立即创建 / 恢复。

@bp.route('/api/admin/backup/snapshots', methods=['GET'])
@admin_required
def snapshot_list():
    """列出数据库快照（按时间倒序）。"""
    try:
        from backend import db_snapshot
        items = db_snapshot.list_snapshots()
        return jsonify({'success': True, 'items': items, 'total': len(items)})
    except Exception as e:
        log.debug('ERROR', f'列出快照失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/admin/backup/snapshot', methods=['POST'])
@admin_required
def snapshot_create():
    """立即创建一份数据库快照。

    在**任何批量/破坏性操作之前**都应先做一份（扫描、迁移、库配置变更）。
    """
    try:
        from backend import db_snapshot
        data = request.get_json(force=True, silent=True) or {}
        info = db_snapshot.snapshot((data.get('reason') or 'manual').strip() or 'manual')
        if not info:
            return jsonify({'success': False, 'message': '创建快照失败（主库不可读？）'}), 500
        return jsonify({'success': True, **info})
    except Exception as e:
        log.debug('ERROR', f'创建快照失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/admin/backup/restore', methods=['POST'])
@admin_required
def snapshot_restore():
    """从快照恢复主库。

    恢复前会先把当前库另存为回滚点，失败还能再退回。
    **恢复后必须重启服务**（进程持有数据库连接，换文件不会自动生效）。
    """
    try:
        from backend import db_snapshot
        data = request.get_json(force=True, silent=True) or {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'success': False, 'message': '缺少快照名'}), 400
        ok, msg = db_snapshot.restore(name)
        return jsonify({'success': ok, 'message': msg}), (200 if ok else 400)
    except Exception as e:
        log.debug('ERROR', f'恢复快照失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500
