"""互动数据管理：提供当前用户清空全部互动数据（收藏/点赞/踩/历史/稍后）的端点。

身份键沿用 current_interaction_key：登录用户为 u{user_id}（跨设备一致），
未登录游客为随机会话（仅当前设备有效）。
"""
from datetime import datetime
from core.models import db, UserInteraction, GalleryInteraction, WatchLater, WatchHistory
from backend.access import current_interaction_key
from flask import Blueprint, jsonify
from liblog import get_service_logger
log = get_service_logger('dplayer-web')

bp = Blueprint('interaction_api', __name__)


@bp.route('/api/interactions/all', methods=['DELETE'])
def clear_all_interactions():
    """清空当前用户全部互动数据：视频互动、图集互动、稍后再看、观看历史。"""
    try:
        key = current_interaction_key()
        # 视频互动（收藏/点赞/踩等统一存于 user_interactions，按 user_session 归属）
        UserInteraction.query.filter_by(user_session=key).delete()
        # 图集互动（字段为 user_session，与视频互动一致）
        GalleryInteraction.query.filter_by(user_session=key).delete()
        # 稍后再看
        WatchLater.query.filter_by(user_key=key).delete()
        # 观看历史
        WatchHistory.query.filter_by(user_key=key).delete()
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"清空互动数据失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
