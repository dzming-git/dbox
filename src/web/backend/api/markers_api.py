"""精彩片段标记 API：为单位用户的视频标记时间戳（支持备注、跳转、删除）。

身份严格复用主应用 main.current_interaction_key()：
  - 登录用户 -> 'u{user_id}'（无论 JWT Bearer 还是 Flask 会话，跨设备一致）
  - 游客     -> 随机会话（仅当前浏览器有效）
标记仅本人可见、仅本人可删除，与文件名/标题完全解耦。
"""
from flask import Blueprint, request, jsonify

from core.models import db, Video, VideoMarker

markers_bp = Blueprint('markers', __name__)


def current_interaction_key():
    """对齐主应用身份约定，确保登录用户跨设备一致。

    延迟导入 main，避免与 main 注册本蓝图时的循环依赖。
    """
    from main import current_interaction_key as _cik
    return _cik()


def _video_by_hash(hash_):
    return Video.query.filter_by(hash=hash_).first()


@markers_bp.route('/api/video/<hash_>/markers', methods=['GET'])
def list_markers(hash_):
    video = _video_by_hash(hash_)
    if not video:
        return jsonify({'error': 'video not found'}), 404
    key = current_interaction_key()
    markers = (
        VideoMarker.query
        .filter_by(video_id=video.id, user_session=key)
        .order_by(VideoMarker.time_seconds)
        .all()
    )
    return jsonify([m.to_dict() for m in markers])


@markers_bp.route('/api/video/<hash_>/markers', methods=['POST'])
def add_marker(hash_):
    video = _video_by_hash(hash_)
    if not video:
        return jsonify({'error': 'video not found'}), 404
    data = request.get_json(silent=True) or {}
    time_seconds = data.get('time')
    if time_seconds is None:
        return jsonify({'error': 'time required'}), 400
    try:
        time_seconds = float(time_seconds)
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid time'}), 400
    if time_seconds < 0:
        return jsonify({'error': 'invalid time'}), 400
    note = (data.get('note') or '').strip()[:200]
    key = current_interaction_key()
    marker = VideoMarker(
        video_id=video.id,
        user_session=key,
        time_seconds=time_seconds,
        note=note,
    )
    db.session.add(marker)
    db.session.commit()
    return jsonify(marker.to_dict()), 201


@markers_bp.route('/api/video/<hash_>/markers/<int:mid>', methods=['DELETE'])
def delete_marker(hash_, mid):
    video = _video_by_hash(hash_)
    if not video:
        return jsonify({'error': 'video not found'}), 404
    key = current_interaction_key()
    marker = VideoMarker.query.filter_by(
        id=mid, video_id=video.id, user_session=key
    ).first()
    if not marker:
        return jsonify({'error': 'not found'}), 404
    db.session.delete(marker)
    db.session.commit()
    return jsonify({'success': True})
