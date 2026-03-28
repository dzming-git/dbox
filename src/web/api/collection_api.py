# -*- coding: utf-8 -*-
"""
收藏夹 API

提供收藏夹管理、视频收藏等接口
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Blueprint, request, jsonify, g
from functools import wraps

collection_bp = Blueprint('collection', __name__, url_prefix='/api/collection')

# 全局总线客户端引用（由 main.py 传入）
_collection_bus = None


def init_collection_api(collection_bus):
    """初始化收藏夹 API，注入总线客户端"""
    global _collection_bus
    _collection_bus = collection_bus


def auth_required(f):
    """装饰器：需要登录"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = getattr(g, 'user_id', None)
        if user_id is None:
            return jsonify({'success': False, 'error': '需要登录'}), 401
        return f(user_id=user_id, *args, **kwargs)
    return decorated


# ============ 收藏夹管理 ============


@collection_bp.route('/', methods=['GET'])
@auth_required
def list_collections(user_id=None):
    """列出用户的收藏夹"""
    if not _collection_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    include_public = request.args.get('include_public', 'true').lower() == 'true'

    try:
        result = _collection_bus.call_method(
            service='com.dplayer.collectiond',
            interface='com.dplayer.Collectiond',
            method='ListCollections',
            params={
                'user_id': user_id,
                'include_public': include_public,
            }
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@collection_bp.route('/<int:collection_id>', methods=['GET'])
def get_collection(collection_id):
    """获取收藏夹详情"""
    if not _collection_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    try:
        result = _collection_bus.call_method(
            service='com.dplayer.collectiond',
            interface='com.dplayer.Collectiond',
            method='GetCollection',
            params={'collection_id': collection_id}
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@collection_bp.route('/', methods=['POST'])
@auth_required
def create_collection(user_id=None):
    """创建收藏夹"""
    if not _collection_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    data = request.get_json()
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    is_public = data.get('is_public', False)

    if not name:
        return jsonify({'success': False, 'error': '收藏夹名称不能为空'}), 400

    try:
        result = _collection_bus.call_method(
            service='com.dplayer.collectiond',
            interface='com.dplayer.Collectiond',
            method='CreateCollection',
            params={
                'name': name,
                'description': description,
                'user_id': user_id,
                'is_public': is_public,
            }
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@collection_bp.route('/<int:collection_id>', methods=['PUT'])
@auth_required
def update_collection(collection_id, user_id=None):
    """更新收藏夹"""
    if not _collection_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    data = request.get_json()

    try:
        result = _collection_bus.call_method(
            service='com.dplayer.collectiond',
            interface='com.dplayer.Collectiond',
            method='UpdateCollection',
            params={
                'collection_id': collection_id,
                **data,
            }
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@collection_bp.route('/<int:collection_id>', methods=['DELETE'])
@auth_required
def delete_collection(collection_id, user_id=None):
    """删除收藏夹"""
    if not _collection_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    try:
        result = _collection_bus.call_method(
            service='com.dplayer.collectiond',
            interface='com.dplayer.Collectiond',
            method='DeleteCollection',
            params={'collection_id': collection_id}
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ 收藏夹条目管理 ============


@collection_bp.route('/<int:collection_id>/items', methods=['GET'])
def get_collection_items(collection_id):
    """获取收藏夹中的视频列表"""
    if not _collection_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 50, type=int)

    try:
        result = _collection_bus.call_method(
            service='com.dplayer.collectiond',
            interface='com.dplayer.Collectiond',
            method='GetCollectionItems',
            params={
                'collection_id': collection_id,
                'page': page,
                'limit': limit,
            }
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@collection_bp.route('/<int:collection_id>/items', methods=['POST'])
@auth_required
def add_to_collection(collection_id, user_id=None):
    """添加视频到收藏夹"""
    if not _collection_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    data = request.get_json()
    video_hash = data.get('video_hash', '').strip()
    note = data.get('note', '').strip()

    if not video_hash:
        return jsonify({'success': False, 'error': '缺少 video_hash'}), 400

    try:
        result = _collection_bus.call_method(
            service='com.dplayer.collectiond',
            interface='com.dplayer.Collectiond',
            method='AddToCollection',
            params={
                'collection_id': collection_id,
                'video_hash': video_hash,
                'note': note,
            }
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@collection_bp.route('/<int:collection_id>/items/<video_hash>', methods=['DELETE'])
@auth_required
def remove_from_collection(collection_id, video_hash, user_id=None):
    """从收藏夹移除视频"""
    if not _collection_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    try:
        result = _collection_bus.call_method(
            service='com.dplayer.collectiond',
            interface='com.dplayer.Collectiond',
            method='RemoveFromCollection',
            params={
                'collection_id': collection_id,
                'video_hash': video_hash,
            }
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@collection_bp.route('/check/<int:collection_id>/<video_hash>', methods=['GET'])
def check_in_collection(collection_id, video_hash):
    """检查视频是否在收藏夹中"""
    if not _collection_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    try:
        result = _collection_bus.call_method(
            service='com.dplayer.collectiond',
            interface='com.dplayer.Collectiond',
            method='IsInCollection',
            params={
                'collection_id': collection_id,
                'video_hash': video_hash,
            }
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@collection_bp.route('/video/<video_hash>', methods=['GET'])
def get_collections_for_video(video_hash):
    """获取包含指定视频的所有收藏夹"""
    if not _collection_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    user_id = getattr(g, 'user_id', None)

    try:
        result = _collection_bus.call_method(
            service='com.dplayer.collectiond',
            interface='com.dplayer.Collectiond',
            method='GetCollectionsForVideo',
            params={
                'video_hash': video_hash,
                'user_id': user_id,
            }
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ 健康检查 ============


@collection_bp.route('/health', methods=['GET'])
def health_check():
    """健康检查"""
    if not _collection_bus:
        return jsonify({'status': 'unavailable'}), 503

    try:
        result = _collection_bus.call_method(
            service='com.dplayer.collectiond',
            interface='com.dplayer.Collectiond',
            method='HealthCheck',
            params={}
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500
