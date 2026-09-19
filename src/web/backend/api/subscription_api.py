# -*- coding: utf-8 -*-
"""订阅与用户通知 API（Blueprint）。

- 通知中心：拉取 / 标记已读（订阅事件通知的统一展现层）。
- 订阅：用户关注来源（X 账号 / pixiv 画师）的 CRUD，供对应扩展读取后轮询拉新。

所有接口要求登录（auth_required），数据按当前用户隔离。
"""
import json
from flask import Blueprint, request, jsonify

from core.models import db, UserNotification, Subscription
from backend.access import auth_required, resolve_identity

bp = Blueprint('subscription_api', __name__)


def _current_user_id():
    user_id, _ = resolve_identity()
    return user_id


# ---------------- 通知 ----------------
@bp.route('/api/notifications', methods=['GET'])
@auth_required
def list_notifications():
    uid = _current_user_id()
    unread_only = request.args.get('unread_only') == '1'
    limit = request.args.get('limit', type=int, default=50)
    offset = request.args.get('offset', type=int, default=0)
    q = UserNotification.query.filter_by(user_id=uid)
    if unread_only:
        q = q.filter_by(read=False)
    total = q.count()
    unread = UserNotification.query.filter_by(user_id=uid, read=False).count()
    rows = (q.order_by(UserNotification.created_at.desc())
            .limit(limit).offset(offset).all())
    return jsonify({'success': True, 'items': [r.to_dict() for r in rows],
                    'total': total, 'unread': unread})


@bp.route('/api/notifications/<int:nid>/read', methods=['POST'])
@auth_required
def mark_read(nid):
    uid = _current_user_id()
    n = UserNotification.query.filter_by(id=nid, user_id=uid).first()
    if not n:
        return jsonify({'success': False, 'message': '通知不存在'}), 404
    n.read = True
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/api/notifications/read-all', methods=['POST'])
@auth_required
def mark_all_read():
    uid = _current_user_id()
    UserNotification.query.filter_by(user_id=uid, read=False).update({'read': True})
    db.session.commit()
    return jsonify({'success': True})


# ---------------- 订阅 ----------------
@bp.route('/api/subscriptions', methods=['GET'])
@auth_required
def list_subscriptions():
    uid = _current_user_id()
    rows = (Subscription.query.filter_by(user_id=uid)
            .order_by(Subscription.created_at.desc()).all())
    return jsonify({'success': True, 'items': [r.to_dict() for r in rows]})


@bp.route('/api/subscriptions', methods=['POST'])
@auth_required
def create_subscription():
    uid = _current_user_id()
    data = request.get_json(silent=True) or {}
    source_type = (data.get('sourceType') or '').strip().lower()
    source_id = (data.get('sourceId') or '').strip()
    if not source_type or not source_id:
        return jsonify({'success': False, 'message': 'sourceType 与 sourceId 必填'}), 400
    if Subscription.query.filter_by(user_id=uid, source_type=source_type,
                                    source_id=source_id).first():
        return jsonify({'success': False, 'message': '该来源已订阅'}), 409
    sub = Subscription(
        user_id=uid,
        source_type=source_type,
        source_id=source_id,
        source_name=(data.get('sourceName') or '').strip() or None,
        target_mode=(data.get('targetMode') or 'video').strip() or 'video',
        library_id=data.get('libraryId'),
        filters=(json.dumps(data['filters'], ensure_ascii=False)
                 if isinstance(data.get('filters'), dict) else None),
        enabled=bool(data.get('enabled', True)),
    )
    db.session.add(sub)
    db.session.commit()
    return jsonify({'success': True, 'subscription': sub.to_dict()})


@bp.route('/api/subscriptions/<int:sid>', methods=['PUT'])
@auth_required
def update_subscription(sid):
    uid = _current_user_id()
    sub = Subscription.query.filter_by(id=sid, user_id=uid).first()
    if not sub:
        return jsonify({'success': False, 'message': '订阅不存在'}), 404
    data = request.get_json(silent=True) or {}
    if 'sourceName' in data:
        sub.source_name = (data['sourceName'] or '').strip() or None
    if 'targetMode' in data:
        sub.target_mode = (data['targetMode'] or 'video').strip() or 'video'
    if 'libraryId' in data:
        sub.library_id = data['libraryId']
    if 'enabled' in data:
        sub.enabled = bool(data['enabled'])
    if 'filters' in data and isinstance(data['filters'], dict):
        sub.filters = json.dumps(data['filters'], ensure_ascii=False)
    db.session.commit()
    return jsonify({'success': True, 'subscription': sub.to_dict()})


@bp.route('/api/subscriptions/<int:sid>', methods=['DELETE'])
@auth_required
def delete_subscription(sid):
    uid = _current_user_id()
    sub = Subscription.query.filter_by(id=sid, user_id=uid).first()
    if not sub:
        return jsonify({'success': False, 'message': '订阅不存在'}), 404
    db.session.delete(sub)
    db.session.commit()
    return jsonify({'success': True})
