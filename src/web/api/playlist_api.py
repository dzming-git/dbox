#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
播放列表API端点
提供播放列表的创建、管理和操作功能
"""

from flask import Blueprint, jsonify, request, abort
from core.models import db, Playlist, PlaylistItem, Video
from datetime import datetime
from liblog import get_module_logger
log = get_module_logger()

playlist_bp = Blueprint('playlist', __name__, url_prefix='/api/playlist')


@playlist_bp.route('/', methods=['GET'])
def get_playlists():
    """获取所有播放列表"""
    try:
        user_session = request.args.get('user_session', 'default')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)

        query = Playlist.query.filter_by(user_session=user_session)
        pagination = query.order_by(Playlist.updated_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

        playlists = []
        for playlist in pagination.items:
            playlists.append(playlist.to_dict())

        return jsonify({
            'success': True,
            'playlists': playlists,
            'total': pagination.total,
            'pages': pagination.pages,
            'current_page': page
        })
    except Exception as e:
        log.debug('ERROR', f"获取播放列表失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@playlist_bp.route('/<int:playlist_id>', methods=['GET'])
def get_playlist(playlist_id):
    """获取指定播放列表"""
    try:
        playlist = Playlist.query.get_or_404(playlist_id)
        return jsonify({
            'success': True,
            'playlist': playlist.to_dict()
        })
    except Exception as e:
        log.debug('ERROR', f"获取播放列表失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@playlist_bp.route('/', methods=['POST'])
def create_playlist():
    """创建播放列表"""
    try:
        data = request.get_json()

        name = data.get('name')
        if not name:
            return jsonify({'success': False, 'error': '播放列表名称不能为空'}), 400

        user_session = data.get('user_session', 'default')
        description = data.get('description', '')
        is_public = data.get('is_public', False)
        video_ids = data.get('video_ids', [])

        # 创建播放列表
        playlist = Playlist(
            name=name,
            description=description,
            user_session=user_session,
            is_public=is_public
        )
        db.session.add(playlist)
        db.session.flush()  # 获取playlist.id

        # 添加视频
        for i, video_id in enumerate(video_ids):
            video = Video.query.get(video_id)
            if video:
                item = PlaylistItem(
                    playlist_id=playlist.id,
                    video_id=video_id,
                    position=i + 1
                )
                db.session.add(item)

        playlist.update_video_count()
        db.session.commit()

        log.runtime('INFO', f"创建播放列表: {name}, 视频数: {len(video_ids)}")

        return jsonify({
            'success': True,
            'playlist': playlist.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"创建播放列表失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@playlist_bp.route('/<int:playlist_id>', methods=['PUT'])
def update_playlist(playlist_id):
    """更新播放列表"""
    try:
        playlist = Playlist.query.get_or_404(playlist_id)
        data = request.get_json()

        if 'name' in data:
            playlist.name = data['name']
        if 'description' in data:
            playlist.description = data['description']
        if 'is_public' in data:
            playlist.is_public = data['is_public']
        if 'shuffle_play' in data:
            playlist.shuffle_play = data['shuffle_play']
        if 'repeat_mode' in data:
            playlist.repeat_mode = data['repeat_mode']
        if 'current_video_id' in data:
            playlist.current_video_id = data['current_video_id']

        playlist.updated_at = datetime.utcnow()
        db.session.commit()

        log.runtime('INFO', f"更新播放列表: {playlist.name}")

        return jsonify({
            'success': True,
            'playlist': playlist.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"更新播放列表失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@playlist_bp.route('/<int:playlist_id>', methods=['DELETE'])
def delete_playlist(playlist_id):
    """删除播放列表"""
    try:
        playlist = Playlist.query.get_or_404(playlist_id)

        # 删除所有播放列表项（级联删除）
        PlaylistItem.query.filter_by(playlist_id=playlist_id).delete()

        db.session.delete(playlist)
        db.session.commit()

        log.runtime('INFO', f"删除播放列表: {playlist.name}")

        return jsonify({
            'success': True,
            'message': '播放列表已删除'
        })

    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"删除播放列表失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@playlist_bp.route('/<int:playlist_id>/items', methods=['POST'])
def add_to_playlist(playlist_id):
    """添加视频到播放列表"""
    try:
        playlist = Playlist.query.get_or_404(playlist_id)
        data = request.get_json()

        video_ids = data.get('video_ids', [])
        if not video_ids:
            return jsonify({'success': False, 'error': '视频ID不能为空'}), 400

        # 获取当前最大position
        max_position = db.session.query(db.func.max(PlaylistItem.position)).filter_by(
            playlist_id=playlist_id
        ).scalar() or 0

        # 添加视频
        added_count = 0
        for video_id in video_ids:
            # 检查视频是否已存在
            existing = PlaylistItem.query.filter_by(
                playlist_id=playlist_id,
                video_id=video_id
            ).first()

            if existing:
                continue

            video = Video.query.get(video_id)
            if video:
                max_position += 1
                item = PlaylistItem(
                    playlist_id=playlist_id,
                    video_id=video_id,
                    position=max_position
                )
                db.session.add(item)
                added_count += 1

        playlist.update_video_count()
        db.session.commit()

        log.runtime('INFO', f"添加{added_count}个视频到播放列表: {playlist.name}")

        return jsonify({
            'success': True,
            'added_count': added_count,
            'playlist': playlist.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"添加视频到播放列表失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@playlist_bp.route('/<int:playlist_id>/items/<int:item_id>', methods=['DELETE'])
def remove_from_playlist(playlist_id, item_id):
    """从播放列表移除视频"""
    try:
        playlist = Playlist.query.get_or_404(playlist_id)
        item = PlaylistItem.query.get_or_404(item_id)

        if item.playlist_id != playlist_id:
            return jsonify({'success': False, 'error': '播放列表项不匹配'}), 400

        # 获取被删除项的position
        deleted_position = item.position

        db.session.delete(item)

        # 更新后面项的position
        PlaylistItem.query.filter(
            PlaylistItem.playlist_id == playlist_id,
            PlaylistItem.position > deleted_position
        ).update({
            'position': PlaylistItem.position - 1
        })

        playlist.update_video_count()
        db.session.commit()

        log.runtime('INFO', f"从播放列表移除视频: {playlist.name}")

        return jsonify({
            'success': True,
            'message': '视频已从播放列表移除',
            'playlist': playlist.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"从播放列表移除视频失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@playlist_bp.route('/<int:playlist_id>/items/reorder', methods=['POST'])
def reorder_playlist(playlist_id):
    """重新排序播放列表"""
    try:
        playlist = Playlist.query.get_or_404(playlist_id)
        data = request.get_json()

        item_ids = data.get('item_ids', [])
        if not item_ids:
            return jsonify({'success': False, 'error': '项目ID不能为空'}), 400

        # 更新每个项的position
        for position, item_id in enumerate(item_ids, 1):
            item = PlaylistItem.query.get(item_id)
            if item and item.playlist_id == playlist_id:
                item.position = position

        playlist.updated_at = datetime.utcnow()
        db.session.commit()

        log.runtime('INFO', f"重新排序播放列表: {playlist.name}")

        return jsonify({
            'success': True,
            'playlist': playlist.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"重新排序播放列表失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@playlist_bp.route('/<int:playlist_id>/play', methods=['POST'])
def play_playlist(playlist_id):
    """播放播放列表"""
    try:
        playlist = Playlist.query.get_or_404(playlist_id)

        # 更新播放次数
        playlist.play_count += 1

        # 获取第一个视频
        first_item = PlaylistItem.query.filter_by(
            playlist_id=playlist_id
        ).order_by(PlaylistItem.position).first()

        if first_item:
            playlist.current_video_id = first_item.video_id

        playlist.updated_at = datetime.utcnow()
        db.session.commit()

        log.runtime('INFO', f"播放播放列表: {playlist.name}")

        return jsonify({
            'success': True,
            'playlist': playlist.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"播放播放列表失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@playlist_bp.route('/<int:playlist_id>/next', methods=['GET'])
def get_next_video(playlist_id):
    """获取下一个视频"""
    try:
        playlist = Playlist.query.get_or_404(playlist_id)
        repeat_mode = playlist.repeat_mode

        # 获取当前播放位置
        current_item = PlaylistItem.query.filter_by(
            playlist_id=playlist_id,
            video_id=playlist.current_video_id
        ).first()

        if not current_item:
            # 没有当前视频，返回第一个
            next_item = PlaylistItem.query.filter_by(
                playlist_id=playlist_id
            ).order_by(PlaylistItem.position).first()
        else:
            # 获取下一个
            next_item = PlaylistItem.query.filter(
                PlaylistItem.playlist_id == playlist_id,
                PlaylistItem.position > current_item.position
            ).order_by(PlaylistItem.position).first()

            # 如果没有下一个，根据重复模式决定
            if not next_item:
                if repeat_mode == 'all':
                    # 重复播放，返回第一个
                    next_item = PlaylistItem.query.filter_by(
                        playlist_id=playlist_id
                    ).order_by(PlaylistItem.position).first()
                elif repeat_mode == 'one':
                    # 单曲循环，返回当前
                    next_item = current_item
                else:
                    # 不重复，返回None
                    next_item = None

        if next_item:
            playlist.current_video_id = next_item.video_id
            db.session.commit()

            return jsonify({
                'success': True,
                'video': next_item.video.to_dict() if next_item.video else None,
                'position': next_item.position
            })
        else:
            return jsonify({
                'success': True,
                'video': None,
                'message': '播放列表已结束'
            })

    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"获取下一个视频失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@playlist_bp.route('/<int:playlist_id>/previous', methods=['GET'])
def get_previous_video(playlist_id):
    """获取上一个视频"""
    try:
        playlist = Playlist.query.get_or_404(playlist_id)

        # 获取当前播放位置
        current_item = PlaylistItem.query.filter_by(
            playlist_id=playlist_id,
            video_id=playlist.current_video_id
        ).first()

        if not current_item:
            # 没有当前视频，返回第一个
            prev_item = PlaylistItem.query.filter_by(
                playlist_id=playlist_id
            ).order_by(PlaylistItem.position).first()
        else:
            # 获取上一个
            prev_item = PlaylistItem.query.filter(
                PlaylistItem.playlist_id == playlist_id,
                PlaylistItem.position < current_item.position
            ).order_by(PlaylistItem.position.desc()).first()

        if prev_item:
            playlist.current_video_id = prev_item.video_id
            db.session.commit()

            return jsonify({
                'success': True,
                'video': prev_item.video.to_dict() if prev_item.video else None,
                'position': prev_item.position
            })
        else:
            return jsonify({
                'success': True,
                'video': None,
                'message': '已是第一个视频'
            })

    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"获取上一个视频失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@playlist_bp.route('/<int:playlist_id>/shuffle', methods=['POST'])
def shuffle_playlist(playlist_id):
    """随机播放列表"""
    try:
        playlist = Playlist.query.get_or_404(playlist_id)

        # 获取所有项目
        items = PlaylistItem.query.filter_by(playlist_id=playlist_id).all()

        import random
        random.shuffle(items)

        # 更新position
        for i, item in enumerate(items, 1):
            item.position = i

        playlist.shuffle_play = True
        playlist.updated_at = datetime.utcnow()
        db.session.commit()

        log.runtime('INFO', f"随机排序播放列表: {playlist.name}")

        return jsonify({
            'success': True,
            'playlist': playlist.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"随机播放列表失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
