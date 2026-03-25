# -*- coding: utf-8 -*-
"""
共享观看API
实现一对一视频同步播放功能
"""
from flask import Blueprint, request, jsonify, g
from datetime import datetime, timedelta
import secrets
import string
from functools import wraps

from core.models import db, Video, User, SharedWatchSession, UserRole

shared_watch_bp = Blueprint('shared_watch', __name__)


def require_auth(f):
    """认证装饰器 - 支持 JWT 和 Session"""
    @wraps(f)
    def decorated(*args, **kwargs):
        # 优先检查 JWT token
        token = request.headers.get('Authorization', '')
        if token.startswith('Bearer '):
            token = token[7:]

        if token:
            try:
                from authlib.jose import jwt
                SECRET_KEY = 'dplayer-jwt-secret-key-change-in-production-2024'
                payload = jwt.decode(token, SECRET_KEY)

                if payload.get('type') != 'access':
                    return jsonify({'success': False, 'message': 'token 类型错误'}), 401

                user = User.query.get(payload.get('user_id'))
                if not user:
                    return jsonify({'success': False, 'message': '用户不存在'}), 401

                g.user = user
                g.user_id = user.id
                g.role = user.role

                return f(*args, **kwargs)
            except Exception as e:
                return jsonify({'success': False, 'message': f'无效的 token: {str(e)}'}), 401

        # 检查 Session
        from flask import session
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': '请先登录'}), 401

        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 401

        g.user = user
        g.user_id = user.id
        g.role = user.role

        return f(*args, **kwargs)
    return decorated


def generate_share_code(length=8):
    """生成分享码"""
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


@shared_watch_bp.route('/api/shared-watch/create', methods=['POST'])
@require_auth
def create_shared_session():
    """创建共享观看会话"""
    data = request.get_json()
    video_hash = data.get('video_hash')

    if not video_hash:
        return jsonify({'success': False, 'message': '缺少视频hash'}), 400

    # 检查视频是否存在
    video = Video.query.filter_by(hash=video_hash).first()
    if not video:
        return jsonify({'success': False, 'message': '视频不存在'}), 404

    # 检查是否已有未结束的会话
    existing = SharedWatchSession.query.filter_by(
        creator_id=g.user.id,
        video_hash=video_hash,
        status='pending'
    ).first()

    if existing:
        return jsonify({
            'success': True,
            'share_code': existing.share_code,
            'share_url': f"/shared/{existing.share_code}",
            'session': existing.to_dict()
        })

    # 创建新会话
    share_code = generate_share_code()
    while SharedWatchSession.query.filter_by(share_code=share_code).first():
        share_code = generate_share_code()

    session = SharedWatchSession(
        share_code=share_code,
        video_hash=video_hash,
        creator_id=g.user.id,
        current_time=0.0,
        is_playing=False,
        status='pending',
        expires_at=datetime.utcnow() + timedelta(hours=24)
    )

    db.session.add(session)
    db.session.commit()

    return jsonify({
        'success': True,
        'share_code': share_code,
        'share_url': f"/shared/{share_code}",
        'session': session.to_dict()
    })


@shared_watch_bp.route('/api/shared-watch/<share_code>/info', methods=['GET'])
def get_shared_session_info(share_code):
    """获取共享会话信息（无需登录，用于判断链接类型）"""
    session = SharedWatchSession.query.filter_by(share_code=share_code).first()

    if not session:
        return jsonify({'success': False, 'message': '分享链接不存在', 'is_shared': False}), 404

    if session.status == 'ended':
        return jsonify({'success': False, 'message': '分享链接已过期', 'is_shared': False}), 410

    if session.expires_at and session.expires_at < datetime.utcnow():
        session.status = 'ended'
        db.session.commit()
        return jsonify({'success': False, 'message': '分享链接已过期', 'is_shared': False}), 410

    return jsonify({
        'success': True,
        'is_shared': True,
        'session': session.to_dict(),
        'video_hash': session.video_hash
    })


@shared_watch_bp.route('/api/shared-watch/<share_code>/join', methods=['POST'])
@require_auth
def join_shared_session(share_code):
    """加入共享观看会话"""
    session = SharedWatchSession.query.filter_by(share_code=share_code).first()

    if not session:
        return jsonify({'success': False, 'message': '分享链接不存在'}), 404

    if session.status == 'ended':
        return jsonify({'success': False, 'message': '分享链接已过期'}), 410

    if session.expires_at and session.expires_at < datetime.utcnow():
        session.status = 'ended'
        db.session.commit()
        return jsonify({'success': False, 'message': '分享链接已过期'}), 410

    # 检查权限：只有创建者和被邀请者可以加入
    if g.user.id != session.creator_id:
        if session.invitee_id is None:
            # 第一个加入的非创建者成为被邀请者
            session.invitee_id = g.user.id
            session.status = 'active'
            db.session.commit()
        elif g.user.id != session.invitee_id:
            return jsonify({'success': False, 'message': '此链接仅限邀请用户使用'}), 403

    return jsonify({
        'success': True,
        'session': session.to_dict(),
        'is_creator': g.user.id == session.creator_id
    })


@shared_watch_bp.route('/api/shared-watch/<share_code>/sync', methods=['POST'])
@require_auth
def sync_playback(share_code):
    """同步播放状态"""
    session = SharedWatchSession.query.filter_by(share_code=share_code).first()

    if not session:
        return jsonify({'success': False, 'message': '会话不存在'}), 404

    # 检查权限
    if g.user.id not in [session.creator_id, session.invitee_id]:
        return jsonify({'success': False, 'message': '无权限'}), 403

    data = request.get_json()
    current_time = data.get('current_time')
    is_playing = data.get('is_playing')
    client_timestamp = data.get('timestamp')  # 客户端发送时的时间戳

    if current_time is not None:
        session.current_time = float(current_time)
    if is_playing is not None:
        session.is_playing = bool(is_playing)
    
    # 保存客户端时间戳，用于计算网络延迟
    if client_timestamp:
        session.client_timestamp = client_timestamp
        session.server_timestamp = datetime.utcnow().isoformat()

    session.last_sync_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'success': True,
        'session': session.to_dict(),
        'server_timestamp': datetime.utcnow().isoformat()  # 返回服务器时间戳
    })


@shared_watch_bp.route('/api/shared-watch/<share_code>/state', methods=['GET'])
@require_auth
def get_playback_state(share_code):
    """获取当前播放状态"""
    session = SharedWatchSession.query.filter_by(share_code=share_code).first()

    if not session:
        return jsonify({'success': False, 'message': '会话不存在'}), 404

    # 检查权限
    if g.user.id not in [session.creator_id, session.invitee_id]:
        return jsonify({'success': False, 'message': '无权限'}), 403

    return jsonify({
        'success': True,
        'current_time': session.current_time,
        'is_playing': session.is_playing,
        'last_sync_at': session.last_sync_at.isoformat() if session.last_sync_at else None
    })


@shared_watch_bp.route('/api/shared-watch/<share_code>/end', methods=['POST'])
@require_auth
def end_shared_session(share_code):
    """结束共享会话"""
    session = SharedWatchSession.query.filter_by(share_code=share_code).first()

    if not session:
        return jsonify({'success': False, 'message': '会话不存在'}), 404

    # 只有创建者可以结束
    if g.user.id != session.creator_id:
        return jsonify({'success': False, 'message': '只有创建者可以结束会话'}), 403

    session.status = 'ended'
    session.ended_at = datetime.utcnow()
    db.session.commit()

    return jsonify({'success': True})
