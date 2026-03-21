#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
播放列表管理模块
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict
from core.models import db, Playlist, PlaylistItem, Video
from sqlalchemy import desc, asc

logger = logging.getLogger(__name__)


class PlaylistManager:
    """播放列表管理器"""

    @staticmethod
    def create_playlist(
        name: str,
        user_session: str,
        description: str = None,
        is_public: bool = False,
        shuffle_play: bool = False,
        repeat_mode: str = 'none'
    ) -> Dict:
        """
        创建播放列表

        Args:
            name: 播放列表名称
            user_session: 用户会话ID
            description: 描述
            is_public: 是否公开
            shuffle_play: 是否随机播放
            repeat_mode: 重复模式（none, all, one）

        Returns:
            播放列表字典
        """
        try:
            playlist = Playlist(
                name=name,
                description=description,
                user_session=user_session,
                is_public=is_public,
                shuffle_play=shuffle_play,
                repeat_mode=repeat_mode
            )

            db.session.add(playlist)
            db.session.commit()
            db.session.refresh(playlist)

            logger.info(f"创建播放列表成功: {name}")
            return playlist.to_dict()

        except Exception as e:
            db.session.rollback()
            logger.error(f"创建播放列表失败: {e}", exc_info=True)
            raise

    @staticmethod
    def get_playlist(playlist_id: int) -> Optional[Dict]:
        """
        获取播放列表

        Args:
            playlist_id: 播放列表ID

        Returns:
            播放列表字典，如果不存在返回None
        """
        try:
            playlist = Playlist.query.get(playlist_id)
            if playlist:
                return playlist.to_dict()
            return None

        except Exception as e:
            logger.error(f"获取播放列表失败: {e}", exc_info=True)
            raise

    @staticmethod
    def get_user_playlists(
        user_session: str,
        page: int = 1,
        per_page: int = 20,
        include_public: bool = True
    ) -> Dict:
        """
        获取用户的播放列表

        Args:
            user_session: 用户会话ID
            page: 页码
            per_page: 每页数量
            include_public: 是否包含公开列表

        Returns:
            播放列表字典
        """
        try:
            query = Playlist.query.filter_by(user_session=user_session)

            if include_public:
                query = query.union(
                    Playlist.query.filter_by(is_public=True)
                )

            query = query.order_by(desc(Playlist.updated_at))
            pagination = query.paginate(page=page, per_page=per_page)

            return {
                'total': pagination.total,
                'pages': pagination.pages,
                'current_page': page,
                'per_page': per_page,
                'playlists': [playlist.to_dict() for playlist in pagination.items]
            }

        except Exception as e:
            logger.error(f"获取用户播放列表失败: {e}", exc_info=True)
            raise

    @staticmethod
    def update_playlist(
        playlist_id: int,
        name: str = None,
        description: str = None,
        is_public: bool = None,
        shuffle_play: bool = None,
        repeat_mode: str = None,
        thumbnail: str = None
    ) -> Optional[Dict]:
        """
        更新播放列表

        Args:
            playlist_id: 播放列表ID
            name: 名称
            description: 描述
            is_public: 是否公开
            shuffle_play: 是否随机播放
            repeat_mode: 重复模式
            thumbnail: 缩略图

        Returns:
            更新后的播放列表字典
        """
        try:
            playlist = Playlist.query.get(playlist_id)
            if not playlist:
                return None

            if name is not None:
                playlist.name = name
            if description is not None:
                playlist.description = description
            if is_public is not None:
                playlist.is_public = is_public
            if shuffle_play is not None:
                playlist.shuffle_play = shuffle_play
            if repeat_mode is not None:
                playlist.repeat_mode = repeat_mode
            if thumbnail is not None:
                playlist.thumbnail = thumbnail

            playlist.updated_at = datetime.utcnow()
            db.session.commit()

            logger.info(f"更新播放列表成功: {playlist_id}")
            return playlist.to_dict()

        except Exception as e:
            db.session.rollback()
            logger.error(f"更新播放列表失败: {e}", exc_info=True)
            raise

    @staticmethod
    def delete_playlist(playlist_id: int) -> bool:
        """
        删除播放列表

        Args:
            playlist_id: 播放列表ID

        Returns:
            是否删除成功
        """
        try:
            playlist = Playlist.query.get(playlist_id)
            if not playlist:
                return False

            db.session.delete(playlist)
            db.session.commit()

            logger.info(f"删除播放列表成功: {playlist_id}")
            return True

        except Exception as e:
            db.session.rollback()
            logger.error(f"删除播放列表失败: {e}", exc_info=True)
            raise

    @staticmethod
    def add_video_to_playlist(
        playlist_id: int,
        video_id: int,
        position: int = None
    ) -> Dict:
        """
        添加视频到播放列表

        Args:
            playlist_id: 播放列表ID
            video_id: 视频ID
            position: 位置（可选，默认添加到末尾）

        Returns:
            播放列表项字典
        """
        try:
            # 检查是否已存在
            existing_item = PlaylistItem.query.filter_by(
                playlist_id=playlist_id,
                video_id=video_id
            ).first()

            if existing_item:
                logger.warning(f"视频已存在于播放列表中: {video_id}")
                return existing_item.to_dict()

            # 如果没有指定位置，添加到末尾
            if position is None:
                max_position = db.session.query(db.func.max(PlaylistItem.position)).filter_by(
                    playlist_id=playlist_id
                ).scalar()
                position = (max_position or 0) + 1

            # 创建播放列表项
            item = PlaylistItem(
                playlist_id=playlist_id,
                video_id=video_id,
                position=position
            )

            db.session.add(item)
            db.session.commit()
            db.session.refresh(item)

            # 更新播放列表统计
            playlist = Playlist.query.get(playlist_id)
            if playlist:
                playlist.update_video_count()
                db.session.commit()

            logger.info(f"添加视频到播放列表成功: playlist_id={playlist_id}, video_id={video_id}")
            return item.to_dict()

        except Exception as e:
            db.session.rollback()
            logger.error(f"添加视频到播放列表失败: {e}", exc_info=True)
            raise

    @staticmethod
    def remove_video_from_playlist(playlist_id: int, video_id: int) -> bool:
        """
        从播放列表移除视频

        Args:
            playlist_id: 播放列表ID
            video_id: 视频ID

        Returns:
            是否移除成功
        """
        try:
            item = PlaylistItem.query.filter_by(
                playlist_id=playlist_id,
                video_id=video_id
            ).first()

            if not item:
                return False

            db.session.delete(item)
            db.session.commit()

            # 更新播放列表统计
            playlist = Playlist.query.get(playlist_id)
            if playlist:
                playlist.update_video_count()
                db.session.commit()

            logger.info(f"从播放列表移除视频成功: playlist_id={playlist_id}, video_id={video_id}")
            return True

        except Exception as e:
            db.session.rollback()
            logger.error(f"从播放列表移除视频失败: {e}", exc_info=True)
            raise

    @staticmethod
    def get_playlist_items(
        playlist_id: int,
        page: int = 1,
        per_page: int = 50
    ) -> Dict:
        """
        获取播放列表中的视频

        Args:
            playlist_id: 播放列表ID
            page: 页码
            per_page: 每页数量

        Returns:
            播放列表项字典
        """
        try:
            query = PlaylistItem.query.filter_by(playlist_id=playlist_id)

            # 根据shuffle_play决定排序方式
            playlist = Playlist.query.get(playlist_id)
            if playlist and playlist.shuffle_play:
                import random
                items = query.all()
                random.shuffle(items)
                total = len(items)
                start = (page - 1) * per_page
                end = start + per_page
                items = items[start:end]
            else:
                query = query.order_by(asc(PlaylistItem.position))
                pagination = query.paginate(page=page, per_page=per_page)
                items = pagination.items
                total = pagination.total

            return {
                'total': total,
                'current_page': page,
                'per_page': per_page,
                'items': [item.to_dict() for item in items]
            }

        except Exception as e:
            logger.error(f"获取播放列表项失败: {e}", exc_info=True)
            raise

    @staticmethod
    def update_video_position(playlist_id: int, video_id: int, new_position: int) -> bool:
        """
        更新视频在播放列表中的位置

        Args:
            playlist_id: 播放列表ID
            video_id: 视频ID
            new_position: 新位置

        Returns:
            是否更新成功
        """
        try:
            item = PlaylistItem.query.filter_by(
                playlist_id=playlist_id,
                video_id=video_id
            ).first()

            if not item:
                return False

            # 如果新位置与当前位置相同，直接返回
            if item.position == new_position:
                return True

            old_position = item.position

            # 更新其他项的位置
            if new_position < old_position:
                # 向前移动，中间的项后移
                PlaylistItem.query.filter(
                    PlaylistItem.playlist_id == playlist_id,
                    PlaylistItem.position >= new_position,
                    PlaylistItem.position < old_position
                ).update({'position': PlaylistItem.position + 1})
            else:
                # 向后移动，中间的项前移
                PlaylistItem.query.filter(
                    PlaylistItem.playlist_id == playlist_id,
                    PlaylistItem.position > old_position,
                    PlaylistItem.position <= new_position
                ).update({'position': PlaylistItem.position - 1})

            # 更新当前项的位置
            item.position = new_position
            db.session.commit()

            logger.info(f"更新视频位置成功: playlist_id={playlist_id}, video_id={video_id}, position={new_position}")
            return True

        except Exception as e:
            db.session.rollback()
            logger.error(f"更新视频位置失败: {e}", exc_info=True)
            raise

    @staticmethod
    def batch_add_videos_to_playlist(playlist_id: int, video_ids: List[int]) -> Dict:
        """
        批量添加视频到播放列表

        Args:
            playlist_id: 播放列表ID
            video_ids: 视频ID列表

        Returns:
            批量添加结果
        """
        try:
            results = []
            success_count = 0
            failed_count = 0

            for video_id in video_ids:
                try:
                    item = PlaylistManager.add_video_to_playlist(playlist_id, video_id)
                    results.append({
                        'video_id': video_id,
                        'success': True,
                        'item': item
                    })
                    success_count += 1
                except Exception as e:
                    logger.error(f"添加视频到播放列表失败: video_id={video_id}, 错误={e}")
                    results.append({
                        'video_id': video_id,
                        'success': False,
                        'error': str(e)
                    })
                    failed_count += 1

            return {
                'total': len(video_ids),
                'success': success_count,
                'failed': failed_count,
                'results': results
            }

        except Exception as e:
            logger.error(f"批量添加视频到播放列表失败: {e}", exc_info=True)
            raise

    @staticmethod
    def set_current_video(playlist_id: int, video_id: int) -> bool:
        """
        设置当前播放的视频

        Args:
            playlist_id: 播放列表ID
            video_id: 视频ID

        Returns:
            是否设置成功
        """
        try:
            playlist = Playlist.query.get(playlist_id)
            if not playlist:
                return False

            playlist.current_video_id = video_id
            playlist.play_count += 1
            playlist.updated_at = datetime.utcnow()
            db.session.commit()

            logger.info(f"设置当前播放视频: playlist_id={playlist_id}, video_id={video_id}")
            return True

        except Exception as e:
            db.session.rollback()
            logger.error(f"设置当前播放视频失败: {e}", exc_info=True)
            raise

    @staticmethod
    def get_next_video(playlist_id: int, current_video_id: int = None) -> Optional[Dict]:
        """
        获取下一个视频

        Args:
            playlist_id: 播放列表ID
            current_video_id: 当前视频ID

        Returns:
            下一个视频字典，如果没有则返回None
        """
        try:
            playlist = Playlist.query.get(playlist_id)
            if not playlist:
                return None

            # 如果没有指定当前视频，使用播放列表的当前视频
            if current_video_id is None:
                current_video_id = playlist.current_video_id

            # 获取当前视频的位置
            if current_video_id:
                current_item = PlaylistItem.query.filter_by(
                    playlist_id=playlist_id,
                    video_id=current_video_id
                ).first()

                if current_item:
                    # 获取下一个视频
                    next_item = PlaylistItem.query.filter(
                        PlaylistItem.playlist_id == playlist_id,
                        PlaylistItem.position > current_item.position
                    ).order_by(asc(PlaylistItem.position)).first()

                    if next_item and next_item.video:
                        # 更新当前视频
                        playlist.current_video_id = next_item.video_id
                        db.session.commit()
                        return next_item.video.to_dict()

            # 如果没有下一个视频，根据重复模式处理
            if playlist.repeat_mode == 'all':
                # 重复播放所有，回到第一个视频
                first_item = PlaylistItem.query.filter_by(
                    playlist_id=playlist_id
                ).order_by(asc(PlaylistItem.position)).first()

                if first_item and first_item.video:
                    playlist.current_video_id = first_item.video_id
                    db.session.commit()
                    return first_item.video.to_dict()

            return None

        except Exception as e:
            db.session.rollback()
            logger.error(f"获取下一个视频失败: {e}", exc_info=True)
            raise

    @staticmethod
    def get_previous_video(playlist_id: int, current_video_id: int = None) -> Optional[Dict]:
        """
        获取上一个视频

        Args:
            playlist_id: 播放列表ID
            current_video_id: 当前视频ID

        Returns:
            上一个视频字典，如果没有则返回None
        """
        try:
            playlist = Playlist.query.get(playlist_id)
            if not playlist:
                return None

            # 如果没有指定当前视频，使用播放列表的当前视频
            if current_video_id is None:
                current_video_id = playlist.current_video_id

            if not current_video_id:
                return None

            # 获取当前视频的位置
            current_item = PlaylistItem.query.filter_by(
                playlist_id=playlist_id,
                video_id=current_video_id
            ).first()

            if current_item:
                # 获取上一个视频
                prev_item = PlaylistItem.query.filter(
                    PlaylistItem.playlist_id == playlist_id,
                    PlaylistItem.position < current_item.position
                ).order_by(desc(PlaylistItem.position)).first()

                if prev_item and prev_item.video:
                    # 更新当前视频
                    playlist.current_video_id = prev_item.video_id
                    db.session.commit()
                    return prev_item.video.to_dict()

            return None

        except Exception as e:
            db.session.rollback()
            logger.error(f"获取上一个视频失败: {e}", exc_info=True)
            raise
