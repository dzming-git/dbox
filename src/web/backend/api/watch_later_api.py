"""Auto-split blueprint: watch_later_api (moved from main.py)."""
from flask import Blueprint, request, jsonify, send_file, send_from_directory, session, g, abort, Response, current_app

bp = Blueprint('watch_later_api', __name__)

@bp.route('/api/watch-later', methods=['GET'])
def get_watch_later():
    import main
    """获取当前用户的「稍后再看」列表（后端为唯一数据源，登录账号跨设备一致）。"""
    try:
        key = main.current_interaction_key()
        rows = main.WatchLater.query.filter_by(user_key=key).order_by(main.WatchLater.added_at.desc()).all()
        items = [r.to_dict() for r in rows]
        return main.jsonify({'success': True, 'items': items, 'total': len(items)})
    except Exception as e:
        main.log.debug('ERROR', f"获取稍后再看列表失败: {e}")
        return main.jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/watch-later', methods=['POST'])
def add_watch_later():
    import main
    """添加条目到「稍后再看」。"""
    try:
        key = main.current_interaction_key()
        data = main.request.get_json(force=True, silent=True) or {}
        item_type = data.get('type')
        item_id = data.get('id')
        if not item_type or not item_id:
            return main.jsonify({'success': False, 'message': '缺少 type 或 id'}), 400
        exists = main.WatchLater.query.filter_by(user_key=key, item_type=item_type, item_id=item_id).first()
        if not exists:
            wl = main.WatchLater(
                user_key=key, item_type=item_type, item_id=str(item_id),
                title=data.get('title'), thumbnail=data.get('thumbnail'),
            )
            main.db.session.add(wl)
            main.db.session.commit()
        return main.jsonify({'success': True})
    except Exception as e:
        main.db.session.rollback()
        main.log.debug('ERROR', f"添加稍后再看失败: {e}")
        return main.jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/watch-later/<item_type>/<item_id>', methods=['DELETE'])
def remove_watch_later(item_type, item_id):
    import main
    """从「稍后再看」移除某条目。"""
    try:
        key = main.current_interaction_key()
        main.WatchLater.query.filter_by(user_key=key, item_type=item_type, item_id=item_id).delete()
        main.db.session.commit()
        return main.jsonify({'success': True})
    except Exception as e:
        main.db.session.rollback()
        main.log.debug('ERROR', f"删除稍后再看失败: {e}")
        return main.jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/watch-later', methods=['DELETE'])
def clear_watch_later():
    import main
    """清空当前用户「稍后再看」列表。"""
    try:
        key = main.current_interaction_key()
        main.WatchLater.query.filter_by(user_key=key).delete()
        main.db.session.commit()
        return main.jsonify({'success': True})
    except Exception as e:
        main.db.session.rollback()
        main.log.debug('ERROR', f"清空稍后再看失败: {e}")
        return main.jsonify({'success': False, 'message': str(e)}), 500
