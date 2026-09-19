# -*- coding: utf-8 -*-
"""订阅缓存 API（Blueprint）。

扩展轮询到的新内容先经 /internal/subscription-cache 写入缓存（不入库），
本蓝图提供用户侧浏览与「是否入库」的决策入口：

- GET  /api/subscription-cache          列出缓存（可按 source_type / 是否已入库过滤）
- POST /api/subscription-cache/<id>/ingest  用户决定入库：标记 ingested=True
                                          （实际下载由前端经扩展代理 /api/ext/<src>/run 触发）
- DELETE /api/subscription-cache/<id>   忽略一条缓存

所有接口要求登录，数据按当前用户隔离。
"""
from flask import Blueprint, request, jsonify

from core.models import db, SubscriptionCache
from backend.access import auth_required, resolve_identity

bp = Blueprint('subscription_cache_api', __name__)


def _current_user_id():
    user_id, _ = resolve_identity()
    return user_id


@bp.route('/api/subscription-cache', methods=['GET'])
@auth_required
def list_cache():
    uid = _current_user_id()
    source_type = request.args.get('source_type')
    ingested = request.args.get('ingested')  # '0' / '1' / None
    q = SubscriptionCache.query.filter_by(user_id=uid)
    if source_type:
        q = q.filter_by(source_type=source_type)
    if ingested in ('0', '1'):
        q = q.filter_by(ingested=(ingested == '1'))
    rows = q.order_by(SubscriptionCache.cached_at.desc()).all()
    return jsonify({'success': True, 'items': [r.to_dict() for r in rows]})


@bp.route('/api/subscription-cache/<int:cid>', methods=['DELETE'])
@auth_required
def dismiss(cid):
    uid = _current_user_id()
    row = SubscriptionCache.query.filter_by(id=cid, user_id=uid).first()
    if not row:
        return jsonify({'success': False, 'message': '不存在'}), 404
    db.session.delete(row)
    db.session.commit()
    return jsonify({'success': True})


@bp.route('/api/subscription-cache/<int:cid>/ingest', methods=['POST'])
@auth_required
def ingest(cid):
    """用户决定把某条缓存内容入库：仅标记 ingested=True（去重「待入库」列表）。

    真正的下载由前端带着用户凭证经扩展代理 /api/ext/<sourceType>/run 触发，
    复用各扩展既有下载管线；本接口只记录用户意图。
    """
    uid = _current_user_id()
    row = SubscriptionCache.query.filter_by(id=cid, user_id=uid).first()
    if not row:
        return jsonify({'success': False, 'message': '不存在'}), 404
    row.ingested = True
    db.session.commit()
    return jsonify({'success': True})
