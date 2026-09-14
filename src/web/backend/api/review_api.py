# -*- coding: utf-8 -*-
"""整理与清洗：审阅队列（管理员）。

媒体库规模上来后必然堆积问题数据：文件已不在磁盘、元数据残缺、没有封面、
内容重复、还没打标签。逐个翻列表找它们不现实，这里把「可疑项」聚成几条队列，
让人照着清单处理，并支持批量处置。

设计要点：
- **只做检测与处置，不做自动清理**：是否删除由人决定，删除一律走既有回收站（可恢复）；
- 检测按「问题类型」分离，便于看清每一类各有多少；
- 耗时操作（元数据补齐）走统一任务，具备进度与取消能力。
"""
import os
import time

from flask import Blueprint, request, jsonify, g
from sqlalchemy import func

from core.models import (
    db, Video, VideoTag, ResourceIndex, Gallery, LibraryPermission,
    LibraryUserGroupMember, ResourceLibrary,
)
from backend.access import (
    admin_required, get_allowed_library_ids, apply_video_visibility, resolve_identity,
)
from backend.trash import move_to_trash
from liblog import get_service_logger

log = get_service_logger('dbox-web')

bp = Blueprint('review', __name__)

BACKFILL_TASK_ID = 'review:backfill'

# 缩略图扩展名（与 thumbnail_helpers 保持一致）
_THUMB_EXTS = ('gif', 'jpg', 'png', 'sprite.jpg', 'vtt')


def _thumb_dir():
    from backend.paths import DATA_DIR
    return os.path.join(DATA_DIR, 'thumbnails')


def _has_thumb(vhash):
    d = _thumb_dir()
    for ext in _THUMB_EXTS:
        if os.path.exists(os.path.join(d, f'{vhash}.{ext}')):
            return True
    return False


def _visible_videos():
    """当前管理员可见的视频（复用与列表接口一致的可见性判定）。"""
    allowed = get_allowed_library_ids()
    return apply_video_visibility(
        Video.query.options(db.joinedload(Video.resource_index)), allowed
    )


def _video_item(v, reason):
    return {
        'id': v.id,
        'hash': v.hash,
        'title': v.title,
        'library_id': v.library_id,
        'duration': v.duration,
        'file_size': v.file_size,
        'path': (v.resource_index.location if v.resource_index else None)
        or getattr(v, 'local_path', None),
        'reason': reason,
    }


def _collect(kind, limit):
    """按问题类型收集条目。返回 (items, 是否有更多)。"""
    q = _visible_videos()
    items = []

    if kind == 'missing_file':
        # 磁盘上已经没有文件：记录还在，但点开必然失败
        for v in q.limit(limit * 3).all():
            p = (v.resource_index.location if v.resource_index else None)
            if not p or not os.path.exists(p):
                items.append(_video_item(v, '文件已不在磁盘'))
                if len(items) >= limit:
                    break
    elif kind == 'no_metadata':
        for v in q.filter(
            db.or_(Video.duration.is_(None), Video.file_size.is_(None))
        ).limit(limit).all():
            items.append(_video_item(v, '缺少时长或文件大小'))
    elif kind == 'no_cover':
        for v in q.limit(limit * 3).all():
            if not _has_thumb(v.hash):
                items.append(_video_item(v, '没有封面'))
                if len(items) >= limit:
                    break
    elif kind == 'untagged':
        tagged = db.session.query(VideoTag.video_id)
        for v in q.filter(Video.id.notin_(tagged)).limit(limit).all():
            items.append(_video_item(v, '没有标签'))
    elif kind == 'duplicate':
        # 内容指纹相同：同一份内容被重复登记（历史上多次导入 / 改名后重新扫描）
        dup = (
            db.session.query(Video.hash, func.count(Video.id).label('c'))
            .group_by(Video.hash)
            .having(func.count(Video.id) > 1)
            .limit(limit)
            .all()
        )
        hashes = [h for h, _c in dup]
        if hashes:
            for v in (
                Video.query.options(db.joinedload(Video.resource_index))
                .filter(Video.hash.in_(hashes))
                .limit(limit * 4)
                .all()
            ):
                items.append(_video_item(v, '内容指纹与其他条目相同'))
    return items, len(items) >= limit


@bp.route('/api/admin/review/summary', methods=['GET'])
@admin_required
def review_summary():
    """各类问题的数量概览（供审阅页展示与红点）。"""
    kinds = ['missing_file', 'no_metadata', 'no_cover', 'untagged', 'duplicate']
    out = {}
    # 概览只统计数量：每类最多扫描 500 条即止，避免大库把接口拖垮
    for k in kinds:
        try:
            items, more = _collect(k, 500)
            out[k] = len(items)
            out[k + '_more'] = more
        except Exception as e:
            log.debug('ERROR', f'统计审阅项 {k} 失败: {e}')
            out[k] = 0
    out['success'] = True
    return jsonify(out)


@bp.route('/api/admin/review/items', methods=['GET'])
@admin_required
def review_items():
    """某一类问题的条目列表。query: type, limit, offset"""
    kind = request.args.get('type', 'missing_file')
    try:
        limit = min(int(request.args.get('limit', 50)), 200)
    except (TypeError, ValueError):
        limit = 50
    try:
        offset = max(int(request.args.get('offset', 0)), 0)
    except (TypeError, ValueError):
        offset = 0

    try:
        items, more = _collect(kind, limit + offset)
    except Exception as e:
        log.debug('ERROR', f'获取审阅项失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500
    return jsonify({
        'success': True,
        'type': kind,
        'items': items[offset:offset + limit],
        'has_more': more or len(items) > offset + limit,
    })


@bp.route('/api/admin/review/action', methods=['POST'])
@admin_required
def review_action():
    """对一批条目执行处置。

    body: { action: 'trash' | 'remap' | 'tag', ids?: [video_id], items?: [{id, path}], tag?: string }
    - trash：移入回收站（软删除，可恢复），不直接删文件
    - remap：文件换了位置，按新路径重新指向索引（所有引用它的实体自动跟随）
    - tag：批量打标签（标签不存在则创建）
    """
    data = request.get_json(silent=True) or {}
    action = data.get('action')
    if action not in ('trash', 'remap', 'tag'):
        return jsonify({'success': False, 'message': '不支持的操作'}), 400

    done, failed = 0, []

    if action == 'trash':
        for vid in (data.get('ids') or []):
            v = Video.query.get(vid)
            if not v:
                failed.append(f'{vid}: 不存在')
                continue
            try:
                move_to_trash(v, 'video')
                done += 1
            except Exception as e:
                failed.append(f'{v.title or vid}: {e}')
        return jsonify({'success': True, 'done': done, 'failed': failed})

    if action == 'remap':
        for it in (data.get('items') or []):
            vid, new_path = it.get('id'), (it.get('path') or '').strip()
            v = Video.query.get(vid)
            if not v:
                failed.append(f'{vid}: 不存在')
                continue
            if not new_path or not os.path.exists(new_path):
                failed.append(f'{v.title or vid}: 新路径不存在')
                continue
            try:
                ri = v.resource_index
                if ri is None:
                    failed.append(f'{v.title or vid}: 缺少资源索引')
                    continue
                ri.location = os.path.abspath(new_path)
                db.session.add(ri)
                db.session.commit()
                done += 1
            except Exception as e:
                db.session.rollback()
                failed.append(f'{v.title or vid}: {e}')
        return jsonify({'success': True, 'done': done, 'failed': failed})

    # tag：批量打标签，标签不存在则新建
    tag_name = (data.get('tag') or '').strip()
    if not tag_name:
        return jsonify({'success': False, 'message': '缺少标签名'}), 400
    from core.models import Tag
    tag = Tag.query.filter_by(name=tag_name).first()
    if not tag:
        tag = Tag(name=tag_name, category='类型', path=f'/{tag_name}')
        db.session.add(tag)
        db.session.flush()
    for vid in (data.get('ids') or []):
        v = Video.query.get(vid)
        if not v:
            failed.append(f'{vid}: 不存在')
            continue
        try:
            exists = VideoTag.query.filter_by(video_id=v.id, tag_id=tag.id).first()
            if not exists:
                db.session.add(VideoTag(video_id=v.id, tag_id=tag.id))
            done += 1
        except Exception as e:
            failed.append(f'{v.title or vid}: {e}')
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    return jsonify({'success': True, 'done': done, 'failed': failed})


@bp.route('/api/admin/review/backfill', methods=['POST'])
@admin_required
def review_backfill():
    """补齐缺失的时长与文件大小（后台任务，可查看进度与停止）。

    扫描入库的历史数据这两项可能为空，会让时长显示为 0、按长度筛选失效。
    逐个解析视频头需要时间，因此走统一任务而不是同步等待。
    """
    # 直接复用 library_helpers 的回填实现，不在这里再写一份——
    # 两份实现迟早行为漂移（例如时长探测方式不一致），而且任务中心会出现两个入口。
    owner_id = getattr(g, 'user_id', None)
    try:
        from backend.library_helpers import start_metadata_backfill
        ok, message = start_metadata_backfill(owner_id=owner_id)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    if not ok:
        return jsonify({'success': False, 'message': message}), 400
    return jsonify({'success': True, 'message': message, 'task_id': BACKFILL_TASK_ID})



