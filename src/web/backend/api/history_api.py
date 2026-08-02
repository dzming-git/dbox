"""观看历史接口：视频/图集观看进度统一后端存储，取代 localStorage 分散记录。"""
from core.models import WatchHistory, Video, Gallery
from backend.access import current_interaction_key
from core.models import db
from datetime import datetime
from flask import Blueprint, request, jsonify
from liblog import get_service_logger
log = get_service_logger('dplayer-web')

bp = Blueprint('history_api', __name__)


def _item_title_thumb(item_type, item_id):
    """根据类型与 id 反查标题与封面。"""
    if item_type == 'video':
        v = Video.query.filter_by(hash=item_id).first()
        if v:
            return v.title, v.cover_url
    elif item_type == 'gallery':
        g = Gallery.query.filter_by(hash=item_id).first()
        if g:
            return g.title, g.cover_url
    return None, None


@bp.route('/api/history', methods=['GET'])
def get_history():
    """获取当前用户的观看历史（视频+图集），按观看时间倒序。"""
    try:
        key = current_interaction_key()
        rows = WatchHistory.query.filter_by(user_key=key).order_by(
            WatchHistory.watched_at.desc()).all()
        items = [r.to_dict() for r in rows]
        return jsonify({'success': True, 'items': items, 'total': len(items)})
    except Exception as e:
        log.debug('ERROR', f"获取观看历史失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/history', methods=['POST'])
def add_history():
    """记录/更新一条观看进度（同一 user_key+类型+id 幂等更新）。"""
    try:
        key = current_interaction_key()
        data = request.get_json(force=True, silent=True) or {}
        item_type = data.get('type')
        item_id = data.get('id')
        if item_type not in ('video', 'gallery') or not item_id:
            return jsonify({'success': False, 'message': '缺少合法的 type 或 id'}), 400
        item_id = str(item_id)
        progress = float(data.get('progress', 0) or 0)
        duration = float(data.get('duration', 0) or 0)

        rec = WatchHistory.query.filter_by(
            user_key=key, item_type=item_type, item_id=item_id).first()
        if not rec:
            title = data.get('title')
            thumbnail = data.get('thumbnail')
            if not title or not thumbnail:
                t, th = _item_title_thumb(item_type, item_id)
                title = title or t
                thumbnail = thumbnail or th
            rec = WatchHistory(
                user_key=key, item_type=item_type, item_id=item_id,
                title=title, thumbnail=thumbnail,
            )
            db.session.add(rec)
        rec.progress = progress
        rec.duration = duration
        rec.watched_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True, 'item': rec.to_dict()})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"记录观看历史失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/history/<item_type>/<item_id>', methods=['DELETE'])
def remove_history(item_type, item_id):
    """删除单条历史。"""
    try:
        key = current_interaction_key()
        WatchHistory.query.filter_by(
            user_key=key, item_type=item_type, item_id=item_id).delete()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"删除观看历史失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/history', methods=['DELETE'])
def clear_history():
    """清空当前用户全部观看历史。"""
    try:
        key = current_interaction_key()
        WatchHistory.query.filter_by(user_key=key).delete()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"清空观看历史失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
