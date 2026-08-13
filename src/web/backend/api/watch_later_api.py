"""Auto-split blueprint: watch_later_api (moved from main.py)."""
from datetime import datetime, timedelta

from core.models import WatchLater
from backend.access import current_interaction_key, filter_visible_snapshots
from core.models import db
from flask import Blueprint, request, jsonify, send_file, send_from_directory, session, g, abort, Response, current_app
from liblog import get_service_logger
log = get_service_logger('dbox-web')

bp = Blueprint('watch_later_api', __name__)

# 被删除条目的墓碑保留时长：超过该时长的墓碑会物理清除，
# 之后用户可再次主动加入「稍后再看」。在此期间任何回推/恢复都不会让已删条目复活。
WATCH_LATER_TOMBSTONE_RETENTION_DAYS = 30


def _purge_old_tombstones():
    """清理超过保留时长的墓碑行，避免表无限增长，并允许日后重新加入。"""
    try:
        cutoff = datetime.utcnow() - timedelta(days=WATCH_LATER_TOMBSTONE_RETENTION_DAYS)
        WatchLater.query.filter(WatchLater.deleted_at < cutoff).delete()
        db.session.commit()
    except Exception:
        db.session.rollback()


@bp.route('/api/watch-later', methods=['GET'])
def get_watch_later():
    """获取当前用户的「稍后再看」列表（后端为唯一数据源，登录账号跨设备一致）。

    与观看历史同理，条目为快照型记录，需回源资源库校验可见性；
    post/text 无独立资源库归属，按原样透传（其自身接口另有权限收敛）。

    软删除：已打墓碑（deleted_at 非空）的条目视为「用户已删除」，永不返回，
    即使其底层视频被恢复/重新入库也不会复活（修复「删了又回来」）。
    """
    try:
        _purge_old_tombstones()
        key = current_interaction_key()
        rows = (WatchLater.query
                .filter_by(user_key=key)
                .filter(WatchLater.deleted_at.is_(None))
                .order_by(WatchLater.added_at.desc())
                .all())
        rows = filter_visible_snapshots(rows, passthrough_types=('post', 'text'))
        items = [r.to_dict() for r in rows]
        return jsonify({'success': True, 'items': items, 'total': len(items)})
    except Exception as e:
        log.debug('ERROR', f"获取稍后再看列表失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/watch-later', methods=['POST'])
def add_watch_later():
    """添加条目到「稍后再看」。

    软删除语义：若条目已存在（含已打墓碑的「已删除」态），一律视为无需新增——
    墓碑态不会被回推/重复操作复活，确保「用户删除过」这件事被服务端权威记住。
    仅当条目确实不存在时才新建。
    """
    try:
        _purge_old_tombstones()
        key = current_interaction_key()
        data = request.get_json(force=True, silent=True) or {}
        item_type = data.get('type')
        item_id = data.get('id')
        if not item_type or not item_id:
            return jsonify({'success': False, 'message': '缺少 type 或 id'}), 400
        item_id = str(item_id)
        exists = WatchLater.query.filter_by(
            user_key=key, item_type=item_type, item_id=item_id).first()
        if exists is None:
            wl = WatchLater(
                user_key=key, item_type=item_type, item_id=item_id,
                title=data.get('title'), thumbnail=data.get('thumbnail'),
            )
            db.session.add(wl)
            db.session.commit()
        # 已存在（无论是否已删除）：不做任何改变，避免复活已删条目
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"添加稍后再看失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/watch-later/<item_type>/<item_id>', methods=['DELETE'])
def remove_watch_later(item_type, item_id):
    """从「稍后再看」移除某条目。

    采用软删除：仅打墓碑（deleted_at），不物理删除行。这样即便底层视频随后被
    恢复、或某客户端把本地残留列表再次回推，该条目也不会「复活」重新出现在列表。
    """
    try:
        key = current_interaction_key()
        now = datetime.utcnow()
        n = (WatchLater.query
             .filter_by(user_key=key, item_type=item_type, item_id=item_id)
             .update({'deleted_at': now}, synchronize_session=False))
        db.session.commit()
        return jsonify({'success': True, 'removed': n})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"删除稍后再看失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/watch-later', methods=['DELETE'])
def clear_watch_later():
    """清空当前用户「稍后再看」列表（软删除：全部打墓碑）。"""
    try:
        key = current_interaction_key()
        now = datetime.utcnow()
        n = (WatchLater.query
             .filter_by(user_key=key)
             .update({'deleted_at': now}, synchronize_session=False))
        db.session.commit()
        return jsonify({'success': True, 'removed': n})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"清空稍后再看失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
