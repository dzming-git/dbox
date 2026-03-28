# -*- coding: utf-8 -*-
"""
搜索 API

提供全文搜索、自动补全、标签管理等接口
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Blueprint, request, jsonify, g

search_bp = Blueprint('search', __name__, url_prefix='/api/search')

# 全局总线客户端引用（由 main.py 传入）
_search_bus = None


def init_search_api(search_bus):
    """初始化搜索 API，注入总线客户端"""
    global _search_bus
    _search_bus = search_bus


# ============ 搜索 ============


@search_bp.route('/', methods=['GET'])
def search():
    """全文搜索"""
    if not _search_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    query = request.args.get('q', '').strip()
    library_id = request.args.get('library_id', type=int)
    limit = request.args.get('limit', 50, type=int)
    offset = request.args.get('offset', 0, type=int)

    if not query:
        return jsonify({'success': False, 'error': '缺少查询词'}), 400

    try:
        result = _search_bus.call_method(
            service='com.dplayer.searchd',
            interface='com.dplayer.Searchd',
            method='Search',
            params={
                'query': query,
                'library_id': library_id,
                'limit': limit,
                'offset': offset,
            }
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@search_bp.route('/suggest', methods=['GET'])
def suggest():
    """获取搜索建议（自动补全）"""
    if not _search_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    keyword = request.args.get('keyword', '').strip()
    limit = request.args.get('limit', 10, type=int)

    if not keyword:
        return jsonify({'success': True, 'suggestions': []})

    try:
        result = _search_bus.call_method(
            service='com.dplayer.searchd',
            interface='com.dplayer.Searchd',
            method='Suggest',
            params={
                'keyword': keyword,
                'limit': limit,
            }
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ 标签管理 ============


@search_bp.route('/tags', methods=['GET'])
def get_all_tags():
    """获取所有标签"""
    if not _search_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    library_id = request.args.get('library_id', type=int)

    try:
        result = _search_bus.call_method(
            service='com.dplayer.searchd',
            interface='com.dplayer.Searchd',
            method='GetAllTags',
            params={'library_id': library_id}
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ 索引管理（管理员） ============


@search_bp.route('/index', methods=['POST'])
def index_video():
    """索引视频"""
    if not _search_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    data = request.get_json()
    video_hash = data.get('video_hash', '').strip()

    if not video_hash:
        return jsonify({'success': False, 'error': '缺少 video_hash'}), 400

    try:
        result = _search_bus.call_method(
            service='com.dplayer.searchd',
            interface='com.dplayer.Searchd',
            method='IndexVideo',
            params={
                'video_hash': video_hash,
                'title': data.get('title', ''),
                'description': data.get('description', ''),
                'tags': data.get('tags', ''),
                'duration': data.get('duration', 0),
                'library_id': data.get('library_id', 0),
                'path': data.get('path', ''),
            }
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@search_bp.route('/index/<video_hash>', methods=['DELETE'])
def delete_from_index(video_hash):
    """从索引删除"""
    if not _search_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    try:
        result = _search_bus.call_method(
            service='com.dplayer.searchd',
            interface='com.dplayer.Searchd',
            method='DeleteFromIndex',
            params={'video_hash': video_hash}
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@search_bp.route('/rebuild', methods=['POST'])
def rebuild_index():
    """重建搜索索引"""
    if not _search_bus:
        return jsonify({'success': False, 'error': '服务不可用'}), 503

    try:
        result = _search_bus.call_method(
            service='com.dplayer.searchd',
            interface='com.dplayer.Searchd',
            method='RebuildIndex',
            params={}
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============ 健康检查 ============


@search_bp.route('/health', methods=['GET'])
def health_check():
    """健康检查"""
    if not _search_bus:
        return jsonify({'status': 'unavailable'}), 503

    try:
        result = _search_bus.call_method(
            service='com.dplayer.searchd',
            interface='com.dplayer.Searchd',
            method='HealthCheck',
            params={}
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500
