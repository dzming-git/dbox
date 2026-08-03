"""Auto-split blueprint: watch_later_api (moved from main.py)."""
from core.models import WatchLater
from backend.access import current_interaction_key, filter_visible_snapshots
from core.models import db
from flask import Blueprint, request, jsonify, send_file, send_from_directory, session, g, abort, Response, current_app
from liblog import get_service_logger
log = get_service_logger('dbox-web')

bp = Blueprint('watch_later_api', __name__)

@bp.route('/api/watch-later', methods=['GET'])
def get_watch_later():
    """获取当前用户的「稍后再看」列表（后端为唯一数据源，登录账号跨设备一致）。

    与观看历史同理，条目为快照型记录，需回源资源库校验可见性；
    post/text 无独立资源库归属，按原样透传（其自身接口另有权限收敛）。
    """
    try:
        key = current_interaction_key()
        rows = WatchLater.query.filter_by(user_key=key).order_by(WatchLater.added_at.desc()).all()
        rows = filter_visible_snapshots(rows, passthrough_types=('post', 'text'))
        items = [r.to_dict() for r in rows]
        return jsonify({'success': True, 'items': items, 'total': len(items)})
    except Exception as e:
        log.debug('ERROR', f"获取稍后再看列表失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/watch-later', methods=['POST'])
def add_watch_later():
    """添加条目到「稍后再看」。"""
    try:
        key = current_interaction_key()
        data = request.get_json(force=True, silent=True) or {}
        item_type = data.get('type')
        item_id = data.get('id')
        if not item_type or not item_id:
            return jsonify({'success': False, 'message': '缺少 type 或 id'}), 400
        exists = WatchLater.query.filter_by(user_key=key, item_type=item_type, item_id=item_id).first()
        if not exists:
            wl = WatchLater(
                user_key=key, item_type=item_type, item_id=str(item_id),
                title=data.get('title'), thumbnail=data.get('thumbnail'),
            )
            db.session.add(wl)
            db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"添加稍后再看失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/watch-later/<item_type>/<item_id>', methods=['DELETE'])
def remove_watch_later(item_type, item_id):
    """从「稍后再看」移除某条目。"""
    try:
        key = current_interaction_key()
        WatchLater.query.filter_by(user_key=key, item_type=item_type, item_id=item_id).delete()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"删除稍后再看失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/watch-later', methods=['DELETE'])
def clear_watch_later():
    """清空当前用户「稍后再看」列表。"""
    try:
        key = current_interaction_key()
        WatchLater.query.filter_by(user_key=key).delete()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"清空稍后再看失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
