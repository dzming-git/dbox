# -*- coding: utf-8 -*-
"""
播放历史 API

提供播放进度记录、续播、观看历史等接口
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Blueprint, request, jsonify, g
from functools import wraps

history_bp = Blueprint('history', __name__, url_prefix='/api/history')

# 全局总线客户端引用（由 main.py 传入）
_history_bus = None


def init_history_api(history_bus):
    """初始化历史 API，注入总线客户端"""
    global _history_bus
    _history_bus = history_bus


def auth_or_guest(f):
    """装饰器：支持登录用户或匿名访客"""
    @wraps(f)
    def decorated(*args, **kwargs):
        # 获取用户ID（从 session 或 JWT）
        user_id = getattr(g, 'user_id', None)
        if user_id is None:
            # 尝试从 request.args 获取 user_id（用于简单测试）
            user_id = request.args.get('user_id', type=int)
        return f(user_id=user_id, *args, **kwargs)
    return decorated


# ============ 播放进度 ============


@history_bp.route('/progress/<video_hash>', methods=['GET'])
def get_progress(video_hash):
    """获取播放进度"""
    if not _history_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    user_id = request.args.get('user_id', type=int)

    try:
        result = _history_bus.call_method(
            service='com.dplayer.historyd',
            interface='com.dplayer.Historyd',
            method='GetProgress',
            params={'video_hash': video_hash, 'user_id': user_id}
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@history_bp.route('/progress', methods=['POST'])
@auth_or_guest
def record_progress(user_id=None):
    """记录播放进度"""
    if not _history_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    if user_id is None:
        return jsonify({'success': False, 'error': '需要登录'}), 401

    data = request.get_json()
    video_hash = data.get('video_hash', '').strip()
    progress = data.get('progress', 0)
    duration = data.get('duration', 0)

    if not video_hash:
        return jsonify({'success': False, 'error': '缺少 video_hash'}), 400

    try:
        result = _history_bus.call_method(
            service='com.dplayer.historyd',
            interface='com.dplayer.Historyd',
            method='RecordProgress',
            params={
                'video_hash': video_hash,
                'user_id': user_id,
                'progress': progress,
                'duration': duration,
            }
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ 观看历史列表 ============


@history_bp.route('/history', methods=['GET'])
@auth_or_guest
def get_watch_history(user_id=None):
    """获取观看历史列表"""
    if not _history_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    if user_id is None:
        return jsonify({'success': False, 'error': '需要登录'}), 401

    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)

    try:
        result = _history_bus.call_method(
            service='com.dplayer.historyd',
            interface='com.dplayer.Historyd',
            method='GetWatchHistory',
            params={
                'user_id': user_id,
                'limit': limit,
                'offset': offset,
            }
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@history_bp.route('/continue-watch', methods=['GET'])
@auth_or_guest
def get_continue_watch(user_id=None):
    """获取继续观看列表（未看完的视频）"""
    if not _history_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    if user_id is None:
        return jsonify({'success': False, 'error': '需要登录'}), 401

    limit = request.args.get('limit', 10, type=int)

    try:
        result = _history_bus.call_method(
            service='com.dplayer.historyd',
            interface='com.dplayer.Historyd',
            method='GetContinueWatch',
            params={
                'user_id': user_id,
                'limit': limit,
            }
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ 完成标记 ============


@history_bp.route('/complete/<video_hash>', methods=['POST'])
@auth_or_guest
def mark_completed(user_id=None):
    """标记视频已看完"""
    if not _history_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    if user_id is None:
        return jsonify({'success': False, 'error': '需要登录'}), 401

    video_hash = request.view_args.get('video_hash')

    try:
        result = _history_bus.call_method(
            service='com.dplayer.historyd',
            interface='com.dplayer.Historyd',
            method='MarkCompleted',
            params={
                'video_hash': video_hash,
                'user_id': user_id,
            }
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ 删除历史 ============


@history_bp.route('/history/<int:history_id>', methods=['DELETE'])
@auth_or_guest
def delete_history(history_id, user_id=None):
    """删除单条播放历史"""
    if not _history_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    if user_id is None:
        return jsonify({'success': False, 'error': '需要登录'}), 401

    try:
        result = _history_bus.call_method(
            service='com.dplayer.historyd',
            interface='com.dplayer.Historyd',
            method='DeleteHistory',
            params={'history_id': history_id}
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@history_bp.route('/clear', methods=['DELETE'])
@auth_or_guest
def clear_history(user_id=None):
    """清空用户的所有播放历史"""
    if not _history_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    if user_id is None:
        return jsonify({'success': False, 'error': '需要登录'}), 401

    try:
        result = _history_bus.call_method(
            service='com.dplayer.historyd',
            interface='com.dplayer.Historyd',
            method='ClearUserHistory',
            params={'user_id': user_id}
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ 健康检查 ============


@history_bp.route('/health', methods=['GET'])
def health_check():
    """健康检查"""
    if not _history_bus:
        return jsonify({'status': 'unavailable'}), 503

    try:
        result = _history_bus.call_method(
            service='com.dplayer.historyd',
            interface='com.dplayer.Historyd',
            method='HealthCheck',
            params={}
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500
