"""Auto-split blueprint: video_api (moved from main.py)."""
from backend.paths import DATA_DIR
from backend.helpers import _ensure_interaction
from backend.access import current_interaction_key
from core.models import LibraryUserGroupMember
from backend.helpers import get_or_create_tag_by_path
from backend.trash import move_to_trash
from core.models import VideoTag
from core.models import Tag
from urllib.parse import quote, unquote
from sqlalchemy.orm import joinedload
from backend.audit import log_operation
from core.models import User
from core.models import ResourceLibrary
from backend.utils.media import extract_mp4_duration
from core.models import LibraryPermission
from core.models import ResourceIndex
from core.models import UserInteraction
from backend.helpers import _resolve_resource_library_id
from core.models import db
import os
from backend.helpers import _build_tag_tree
from core.models import Video
from core.models import UserRole
import re
from backend.trash import purge_trash
from backend.runtime import runtime
from backend.access import (
    resolve_identity, get_allowed_library_ids, apply_video_visibility,
    is_video_visible, deny_missing, default_library_id, _user_can_write_library,
)
from backend.access import admin_required, auth_required
from flask import Blueprint, request, jsonify, send_file, send_from_directory, session, g, abort, Response, current_app
from liblog import get_service_logger
from unified_tasks import init_task_manager as _init_tm, create_task, update_task
import threading
log = get_service_logger('dbox-web')

bp = Blueprint('video_api', __name__)

@bp.route('/api/videos', methods=['GET'])
def get_videos():
    try:
        limit = request.args.get('limit', 20, type=int)
        offset = request.args.get('offset', 0, type=int)
        tag_id = request.args.get('tag_id', type=int)
        search = request.args.get('search', '').strip()
        filter_library_id = request.args.get('library_id', type=int)  # 管理员按库筛选
        sort = request.args.get('sort', 'recommended')  # 排序方式: recommended, name, created_at, view_count, like_count
        order = request.args.get('order', 'desc')  # 排序方向: asc, desc
        # 默认屏蔽不喜欢的视频（可在设置中关闭）
        exclude_disliked = request.args.get('exclude_disliked', 'true').lower() != 'false'
        # 仅看点赞 / 仅看收藏
        only_liked = request.args.get('only_liked', '').lower() == 'true'
        only_favorited = request.args.get('only_favorited', '').lower() == 'true'

        query = Video.query.options(joinedload(Video.resource_index))

        # ============ 资源库可见性（统一收敛点）============
        # 仅激活库 + 未删除 + 未隐藏的资源对外可见；取消所有库激活后返回空。
        # 主库（library_id 为 NULL）已通过 migrate_main_library 归入「主资源库」，
        # 因此不再有 NULL 例外。
        allowed_library_ids = get_allowed_library_ids()
        query = apply_video_visibility(query, allowed_library_ids)

        # 如果调用方指定了 library_id（按库精确筛选），需要校验权限：
        # 管理员/ROOT 可筛选任意库；普通用户只能筛选其有权限访问的库，否则返回空
        if filter_library_id is not None:
            _uid, _urole = resolve_identity()
            if _urole in [UserRole.ADMIN, UserRole.ROOT] or filter_library_id in allowed_library_ids:
                query = query.filter(Video.library_id == filter_library_id)
            else:
                # 无权限访问该库，返回空结果（使用一个不可能匹配的 id）
                query = query.filter(Video.library_id == -1)

        # 搜索功能
        if search:
            query = query.filter(Video.title.ilike(f'%{search}%'))

        # 标签筛选 - 支持父子标签继承（选择父标签时同时显示子标签的视频）
        if tag_id:
            # 获取该标签及其所有子标签的ID
            selected_tag = Tag.query.get(tag_id)
            if selected_tag:
                tag_ids = selected_tag.get_all_child_ids()
                query = query.join(VideoTag).filter(VideoTag.tag_id.in_(tag_ids))
            else:
                query = query.join(VideoTag).filter(VideoTag.tag_id == tag_id)

        # 筛选未标记（没有任何标签）的视频——用于「待整理 / 补标签」场景
        untagged = request.args.get('untagged', type=int)
        if untagged:
            # 没有关联任何 VideoTag 的视频
            tagged_video_ids = db.session.query(VideoTag.video_id)
            query = query.filter(Video.id.notin_(tagged_video_ids))


        # ============ 排除不喜欢的视频（默认屏蔽） ============
        disliked_ids = set()
        liked_ids = set()
        favorited_ids = set()
        try:
            user_session = current_interaction_key()
        except Exception:
            user_session = None
        if user_session:
            disliked_ids = {row[0] for row in db.session.query(
                UserInteraction.video_id
            ).filter_by(user_session=user_session, interaction_type='dislike').all()}
            liked_ids = {row[0] for row in db.session.query(
                UserInteraction.video_id
            ).filter_by(user_session=user_session, interaction_type='like').all()}
            favorited_ids = {row[0] for row in db.session.query(
                UserInteraction.video_id
            ).filter_by(user_session=user_session, interaction_type='favorite').all()}
            if exclude_disliked and disliked_ids:
                query = query.filter(Video.id.notin_(disliked_ids))

        # 仅看点赞 / 仅看收藏（用户未登录或对应集合为空时返回空）
        if only_liked:
            query = query.filter(Video.id.in_(liked_ids) if liked_ids else Video.id.in_([-1]))
        if only_favorited:
            query = query.filter(Video.id.in_(favorited_ids) if favorited_ids else Video.id.in_([-1]))

        # ============ 重要：total 统计必须在权限过滤之后 ============
        # 获取总数（已应用权限过滤与不喜欢排除）
        total = query.count()

        # ============ 排序策略 ============
        from sqlalchemy import func, case

        # 根据 order 参数确定排序方向
        is_desc = order.lower() == 'desc'

        # 排序方式映射
        if sort == 'name':
            # 按视频名排序
            videos = query.order_by(Video.title.desc() if is_desc else Video.title.asc()).offset(offset).limit(limit).all()
        elif sort == 'created_at':
            # 按文件创建时间排序
            videos = query.order_by(Video.created_at.desc() if is_desc else Video.created_at.asc()).offset(offset).limit(limit).all()
        elif sort == 'view_count':
            # 按播放量排序
            videos = query.order_by(Video.view_count.desc() if is_desc else Video.view_count.asc()).offset(offset).limit(limit).all()
        elif sort == 'like_count':
            # 按点赞数排序
            videos = query.order_by(Video.like_count.desc() if is_desc else Video.like_count.asc()).offset(offset).limit(limit).all()
        elif sort == 'download_count':
            # 按下载数排序
            videos = query.order_by(Video.download_count.desc() if is_desc else Video.download_count.asc()).offset(offset).limit(limit).all()
        else:
            # 默认推荐排序：首页推荐带随机成分（仅支持倒序）
            # 如果没有指定 tag_id 和 search，则认为是首页推荐，加入随机成分
            if not tag_id and not search and not untagged:
                # 使用 func.random() 为每个视频赋予随机权重
                # 排序公式：view_count * 0.1 + random() * 50
                # 这样热门视频仍有优势，但随机视频也有机会排在前面
                videos = query.order_by(
                    (Video.view_count * 0.1 + func.random() * 50).desc()
                ).offset(offset).limit(limit).all()
            else:
                # 标签页或搜索结果按播放量排序
                videos = query.order_by(
                    Video.view_count.desc()
                ).offset(offset).limit(limit).all()

        return jsonify({
            'success': True,
            'videos': [dict(v.to_dict(), disliked=(v.id in disliked_ids),
                            is_liked=(v.id in liked_ids),
                            is_favorited=(v.id in favorited_ids)) for v in videos],
            'total': total,
            'sort': sort,
            'order': order
        })
    except Exception as e:
        log.debug('ERROR', f"获取视频列表失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/video/<video_hash>', methods=['GET'])
def get_video(video_hash):
    """获取单个视频详情 - 需要检查资源库权限"""
    try:
        video = Video.query.filter_by(hash=video_hash).first()

        # ============ 权限检查（统一收敛点）============
        # 一律以资源库可见性为准，不再为管理员开后门：
        # 资源库未激活即等同不存在。响应与「资源真的不存在」完全一致，
        # 避免通过状态码或文案差异探测资源是否存在。
        if not is_video_visible(video):
            return deny_missing()

        video_dict = video.to_dict()
        # 注入当前用户对视频的交互状态（以后端为准，登录用户绑定账号，跨设备一致）
        key = current_interaction_key()
        for _itype, _flag in (('favorite', 'is_favorited'), ('like', 'is_liked'), ('dislike', 'is_disliked')):
            video_dict[_flag] = UserInteraction.query.filter_by(
                video_id=video.id, user_session=key, interaction_type=_itype
            ).first() is not None
        return jsonify({'success': True, 'video': video_dict})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/videos/by-hashes', methods=['POST'])
def get_videos_by_hashes():
    """根据一组 hash 返回视频概要（hash/title/thumbnail/duration）。

    用于「继续观看」等本地历史场景：localStorage 中可能残留迁移前的旧 hash
    或空的 thumbnail 字段，这里统一以后端权威数据为准重建，过滤掉已不存在的视频。
    """
    try:
        data = request.get_json(silent=True) or {}
        hashes = data.get('hashes')
        if not isinstance(hashes, list) or len(hashes) == 0 or len(hashes) > 300:
            return jsonify({'success': True, 'videos': []})

        # 走统一可见性收敛：未激活资源库的视频不得通过 hash 批量反查出来
        videos = apply_video_visibility(
            Video.query.filter(Video.hash.in_(hashes))).all()
        result = [{
            'hash': v.hash,
            'title': v.title,
            'thumbnail': f'/thumbnail/{v.hash}',
            'duration': getattr(v, 'duration', None),
        } for v in videos]

        return jsonify({'success': True, 'videos': result})
    except Exception as e:
        log.debug('ERROR', f"get_videos_by_hashes 失败: {e}")
        return jsonify({'success': False, 'message': str(e), 'videos': []}), 500

@bp.route('/api/video/<video_hash>/like', methods=['POST'])
def like_video(video_hash):
    try:
        video = Video.query.filter_by(hash=video_hash).first()
        if not is_video_visible(video):
            return deny_missing()
        user_session = current_interaction_key()

        interaction = UserInteraction.query.filter_by(
            video_id=video.id, user_session=user_session, interaction_type='like'
        ).first()

        if interaction:
            db.session.delete(interaction)
            liked = False
        else:
            interaction = UserInteraction(
                video_id=video.id, user_session=user_session,
                interaction_type='like', interaction_score=2.0
            )
            db.session.add(interaction)
            liked = True

        # 计算新的点赞数量
        like_count = UserInteraction.query.filter_by(
            video_id=video.id, interaction_type='like'
        ).count()
        video.like_count = like_count
        db.session.commit()

        log.operation('WEB', f"{'点赞' if liked else '取消点赞'}视频: {video.title}")
        return jsonify({'success': True, 'liked': liked, 'like_count': like_count})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"点赞操作失败: {video_hash}, {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/video/<video_hash>/favorite', methods=['POST'])
def toggle_favorite(video_hash):
    try:
        video = Video.query.filter_by(hash=video_hash).first()
        if not is_video_visible(video):
            return deny_missing()
        user_session = current_interaction_key()
        
        interaction = UserInteraction.query.filter_by(
            video_id=video.id, user_session=user_session, interaction_type='favorite'
        ).first()
        
        if interaction:
            db.session.delete(interaction)
            favorited = False
        else:
            interaction = UserInteraction(
                video_id=video.id, user_session=user_session,
                interaction_type='favorite', interaction_score=5.0
            )
            db.session.add(interaction)
            favorited = True
        
        # 计算新的收藏数量
        favorite_count = UserInteraction.query.filter_by(
            video_id=video.id, interaction_type='favorite'
        ).count()
        video.favorite_count = favorite_count
        db.session.commit()
        
        log.operation('WEB', f"{'收藏' if favorited else '取消收藏'}视频: {video.title}")
        return jsonify({'success': True, 'favorited': favorited, 'favorite_count': favorite_count})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"收藏操作失败: {video_hash}, {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/favorites', methods=['GET'])
def get_favorites():
    """获取当前用户的收藏列表（以后端为唯一数据源，登录用户绑定账号，跨设备一致）

    仅返回当前用户可见（资源库已激活）的视频；库已取消激活的资源从收藏列表隐藏。
    """
    try:
        allowed = set(get_allowed_library_ids())
        key = current_interaction_key()
        rows = UserInteraction.query.filter_by(
            user_session=key, interaction_type='favorite'
        ).order_by(UserInteraction.created_at.desc()).all()

        videos = []
        for row in rows:
            video = Video.query.get(row.video_id)
            if not video or video.in_trash:
                continue
            if video.library_id not in allowed:
                continue
            v = video.to_dict()
            v['favorited_at'] = row.created_at.isoformat() if row.created_at else None
            videos.append(v)

        return jsonify({'success': True, 'videos': videos, 'total': len(videos)})
    except Exception as e:
        log.debug('ERROR', f"获取收藏列表失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/likes', methods=['GET'])
def get_likes():
    """获取当前用户点赞过的视频列表（以后端为唯一数据源，登录用户绑定账号，跨设备一致）

    仅返回当前用户可见（资源库已激活）的视频；库已取消激活的资源从点赞列表隐藏。
    """
    try:
        allowed = set(get_allowed_library_ids())
        key = current_interaction_key()
        rows = UserInteraction.query.filter_by(
            user_session=key, interaction_type='like'
        ).order_by(UserInteraction.created_at.desc()).all()

        videos = []
        for row in rows:
            video = Video.query.get(row.video_id)
            if not video or video.in_trash:
                continue
            if video.library_id not in allowed:
                continue
            v = video.to_dict()
            v['liked_at'] = row.created_at.isoformat() if row.created_at else None
            videos.append(v)

        return jsonify({'success': True, 'videos': videos, 'total': len(videos)})
    except Exception as e:
        log.debug('ERROR', f"获取点赞列表失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/disliked', methods=['GET'])
def get_disliked():
    """获取当前用户标记为不喜欢的视频列表（用于查看/撤销屏蔽）

    仅返回当前用户可见（资源库已激活）的视频；库已取消激活的资源从不喜欢列表隐藏。
    """
    try:
        allowed = set(get_allowed_library_ids())
        key = current_interaction_key()
        rows = UserInteraction.query.filter_by(
            user_session=key, interaction_type='dislike'
        ).order_by(UserInteraction.created_at.desc()).all()

        videos = []
        for row in rows:
            video = Video.query.get(row.video_id)
            if not video or video.in_trash:
                continue
            if video.library_id not in allowed:
                continue
            v = video.to_dict()
            v['disliked_at'] = row.created_at.isoformat() if row.created_at else None
            videos.append(v)

        return jsonify({'success': True, 'videos': videos, 'total': len(videos)})
    except Exception as e:
        log.debug('ERROR', f"获取不喜欢列表失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/videos/batch-interact', methods=['POST'])
def batch_interact():
    """批量互动：对多个视频批量点赞/收藏/标记不喜欢"""
    try:
        data = request.get_json(force=True) or {}
        hashes = data.get('hashes') or []
        action = data.get('action')  # like / favorite / dislike
        if not isinstance(hashes, list) or not hashes:
            return jsonify({'success': False, 'message': '缺少视频列表'}), 400
        if action not in ('like', 'favorite', 'dislike'):
            return jsonify({'success': False, 'message': '未知操作'}), 400

        user_session = current_interaction_key()
        score_map = {'like': 2.0, 'favorite': 5.0, 'dislike': -1.0}
        affected = 0
        _allowed = get_allowed_library_ids()
        for h in hashes:
            video = Video.query.filter_by(hash=h).first()
            # 不可见资源不得被互动（否则可借批量接口探测其存在）
            if not is_video_visible(video, _allowed):
                continue
            _ensure_interaction(video, user_session, action, score_map[action])
            # 同步计数
            if action == 'like':
                video.like_count = UserInteraction.query.filter_by(
                    video_id=video.id, interaction_type='like').count()
            elif action == 'favorite':
                video.favorite_count = UserInteraction.query.filter_by(
                    video_id=video.id, interaction_type='favorite').count()
            affected += 1
        db.session.commit()
        return jsonify({'success': True, 'affected': affected, 'action': action})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"批量互动失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/video/<video_hash>/dislike', methods=['POST'])
def toggle_dislike(video_hash):
    """标记/取消标记不喜欢（踩），默认在列表中屏蔽该视频"""
    try:
        video = Video.query.filter_by(hash=video_hash).first()
        if not is_video_visible(video):
            return deny_missing()
        user_session = current_interaction_key()

        interaction = UserInteraction.query.filter_by(
            video_id=video.id, user_session=user_session, interaction_type='dislike'
        ).first()

        if interaction:
            db.session.delete(interaction)
            disliked = False
        else:
            interaction = UserInteraction(
                video_id=video.id, user_session=user_session,
                interaction_type='dislike', interaction_score=-1.0
            )
            db.session.add(interaction)
            disliked = True

        db.session.commit()

        log.operation('WEB', f"{'不喜欢' if disliked else '取消不喜欢'}视频: {video.title}")
        return jsonify({'success': True, 'disliked': disliked})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"不喜欢操作失败: {video_hash}, {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/video/<video_hash>', methods=['DELETE'])
def delete_video(video_hash):
    try:
        body = request.get_json(silent=True) or {}
        # delete_file / permanent 表示「永久删除」（仅管理员可用），否则移入回收站
        permanent = bool(body.get('delete_file', False) or body.get('permanent', False))

        video = Video.query.filter_by(hash=video_hash).first_or_404()

        # 资源所属权校验：仅本人或管理员/ROOT 可删除
        user_id, user_role = resolve_identity()
        if user_role not in (UserRole.ADMIN, UserRole.ROOT) and video.owner_id not in (None, user_id):
            return jsonify({'success': False, 'message': '无权删除该资源（仅上传者或管理员可操作）', 'code': 403}), 403

        if permanent:
            if user_role not in (UserRole.ADMIN, UserRole.ROOT):
                return jsonify({'success': False, 'message': '仅管理员可永久删除', 'code': 403}), 403
            purge_trash(video, 'video')
            log.maintenance('INFO', f"永久删除视频: {video.title} (hash: {video_hash})")
            return jsonify({'success': True, 'message': '视频已永久删除'})
        else:
            move_to_trash(video, 'video')
            log.maintenance('INFO', f"视频移入回收站: {video.title} (hash: {video_hash})")
            return jsonify({'success': True, 'message': '已移入回收站'})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"删除视频失败: {video_hash}, {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/video/<video_hash>/view', methods=['POST'])
def increment_view_count(video_hash):
    """增加视频观看次数"""
    try:
        video = Video.query.filter_by(hash=video_hash).first()
        if not is_video_visible(video):
            return deny_missing()
        video.view_count = (video.view_count or 0) + 1
        db.session.commit()
        return jsonify({'success': True, 'view_count': video.view_count})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/videos/<int:video_id>/play', methods=['GET'])
@auth_required
def play_video(video_id):
    """播放视频 - 需要检查资源库权限"""
    try:
        video = Video.query.get(video_id)
        if not video:
            return jsonify({'success': False, 'message': '视频不存在'}), 404
        
        # ============ 权限检查 ============
        # 检查视频是否属于某个资源库
        if video.library_id:
            # 获取用户ID和角色
            user_id = g.user_id
            user_role = g.role
            
            # 管理员和ROOT可以访问所有视频
            if user_role not in [UserRole.ADMIN, UserRole.ROOT]:
                # 检查用户权限
                user_perm = LibraryPermission.query.filter_by(
                    library_id=video.library_id, user_id=user_id
                ).first()
                
                # 检查用户组权限
                has_access = bool(user_perm)
                if not has_access:
                    user_groups = LibraryUserGroupMember.query.filter_by(user_id=user_id).all()
                    for ugm in user_groups:
                        group_perm = LibraryPermission.query.filter_by(
                            library_id=video.library_id, group_id=ugm.group_id
                        ).first()
                        if group_perm:
                            has_access = True
                            break
                
                if not has_access:
                    return jsonify({
                        'success': False,
                        'message': '无权播放此视频',
                        'code': 403
                    }), 403
        
        video_path = video.local_path or video.url
        if not video_path or not os.path.exists(video_path):
            return jsonify({'success': False, 'message': '视频文件不存在'}), 404
        
        range_header = request.headers.get('Range', None)
        file_size = os.path.getsize(video_path)

        # 优化：使用更大的缓冲区提升视频流传输性能
        CHUNK_SIZE = 1024 * 1024  # 1MB 块大小

        if range_header:
            match = re.search(r'bytes=(\d+)-(\d*)', range_header)
            byte1 = int(match.group(1)) if match else 0
            byte2 = int(match.group(2)) if match and match.group(2) else file_size - 1
            length = byte2 - byte1 + 1

            def generate():
                with open(video_path, 'rb') as f:
                    f.seek(byte1)
                    remaining = length
                    while remaining > 0:
                        # 分块读取，避免一次性加载大Range到内存
                        chunk_size = min(CHUNK_SIZE, remaining)
                        data = f.read(chunk_size)
                        if not data:
                            break
                        yield data
                        remaining -= len(data)

            resp = Response(generate(), 206, mimetype='video/mp4')
            resp.headers.add('Content-Range', f'bytes {byte1}-{byte2}/{file_size}')
            resp.headers.add('Content-Length', str(length))
            # 允许浏览器缓存视频范围
            resp.headers.add('Accept-Ranges', 'bytes')
        else:
            def generate():
                with open(video_path, 'rb') as f:
                    while data := f.read(CHUNK_SIZE):
                        yield data
            resp = Response(generate(), 200, mimetype='video/mp4')
            resp.headers.add('Content-Length', str(file_size))
            resp.headers.add('Accept-Ranges', 'bytes')

        return resp
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/video/<video_hash>/tags', methods=['POST'])
@auth_required
def set_video_tags(video_hash):
    """
    为视频设置标签（自动创建不存在的标签）
    请求体（兼容两种格式）:
      旧: { "tags": ["/动物/狗", "/动物/猫"] }
      新: { "tags": [{"path":"/动物/猫","qualifiers":["白","长毛"]}] }
    qualifiers 为该视频在此标签上勾选的补充项（须为标签预设集合的子集）；
    用 "/" 分隔层级，如 "/动物/狗/哈士奇"
    """
    try:
        video = Video.query.filter_by(hash=video_hash).first()
        if not video:
            return jsonify({'success': False, 'message': '视频不存在'}), 404
        
        data = request.get_json()
        tags_input = data.get('tags', []) or []
        
        # 获取资源库ID（用于标签隔离）
        library_id = video.library_id
        
        # 先移除所有现有标签关联
        VideoTag.query.filter_by(video_id=video.id).delete()
        
        # 添加新标签（兼容字符串路径与对象格式）
        created_tags = []
        for item in tags_input:
            if isinstance(item, dict):
                tag_path = item.get('path')
                quals = item.get('qualifiers') or []
            elif isinstance(item, str):
                tag_path = item
                quals = []
            else:
                return jsonify({'success': False, 'message': '标签格式错误（需为字符串或对象）'}), 400
            if not tag_path:
                continue
            # 自动创建标签（如果不存在）
            tag = get_or_create_tag_by_path(tag_path, library_id)
            if tag:
                vt = VideoTag(video_id=video.id, tag_id=tag.id)
                vt.set_selected_qualifiers(quals)
                db.session.add(vt)
                tag_dict = tag.to_dict()
                tag_dict['selected_qualifiers'] = vt.get_selected_qualifiers()
                created_tags.append(tag_dict)
        
        db.session.commit()
        
        log.runtime('INFO', f"为视频设置标签: {len(created_tags)}个标签 (video_hash: {video_hash})")
        
        return jsonify({
            'success': True,
            'message': f'已设置 {len(created_tags)} 个标签',
            'tags': created_tags
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/video/<video_hash>/tags', methods=['DELETE'])
@admin_required
def remove_video_tag(video_hash):
    """
    从视频移除单个标签（引用计数为0时自动删除标签）
    请求体: { "tag_path": "/动物/狗" }
    """
    try:
        video = Video.query.filter_by(hash=video_hash).first()
        if not video:
            return jsonify({'success': False, 'message': '视频不存在'}), 404
        
        data = request.get_json()
        tag_path = data.get('tag_path', '').strip()
        
        if not tag_path:
            return jsonify({'success': False, 'message': '标签路径不能为空'}), 400
        
        # 查找标签
        library_id = video.library_id
        tag = Tag.query.filter_by(path=tag_path, library_id=library_id).first()
        
        if not tag:
            return jsonify({'success': False, 'message': '标签不存在'}), 404
        
        # 移除关联
        VideoTag.query.filter_by(video_id=video.id, tag_id=tag.id).delete()
        
        # 检查引用计数，如果为0则删除标签
        remaining_count = VideoTag.query.filter_by(tag_id=tag.id).count()
        if remaining_count == 0:
            # 删除标签及其子标签
            def delete_tag_and_children(tag_id):
                # 先递归删除子标签
                children = Tag.query.filter_by(parent_id=tag_id).all()
                for child in children:
                    delete_tag_and_children(child.id)
                # 删除标签
                Tag.query.filter_by(id=tag_id).delete()
            
            delete_tag_and_children(tag.id)
        
        db.session.commit()
        log.runtime('INFO', f"从视频移除标签: {tag_path} (video_hash: {video_hash})")
        
        return jsonify({
            'success': True,
            'message': '标签已移除' + ('（标签已删除）' if remaining_count == 0 else '')
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/videos/<video_hash>/update', methods=['POST'])
@auth_required
def update_video_info(video_hash):
    """更新视频信息"""
    try:
        video = Video.query.filter_by(hash=video_hash).first_or_404()
        data = request.get_json()
        
        if 'title' in data:
            video.title = data['title'].strip()
        if 'description' in data:
            video.description = data.get('description', '').strip()

        # 支持修改所属资源库
        if 'library_id' in data:
            library_id = data['library_id']
            if library_id is not None:
                library = ResourceLibrary.query.get(int(library_id))
                if not library:
                    return jsonify({'success': False, 'message': '资源库不存在'}), 400
            video.library_id = library_id

        db.session.commit()
        log.runtime('INFO', f"更新视频信息: {video.title}")
        return jsonify({'success': True, 'video': video.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/upload', methods=['POST'])
@auth_required
def upload_video():
    """上传视频文件"""
    try:
        user_id = g.user_id  # @auth_required 已确保存在
        if 'video' not in request.files:
            return jsonify({'success': False, 'message': '未找到视频文件'}), 400

        file = request.files['video']
        if file.filename == '':
            return jsonify({'success': False, 'message': '未选择文件'}), 400

        # 检查文件格式
        allowed_extensions = {'.mp4', '.avi', '.mkv', '.mov', '.webm', '.flv', '.wmv'}
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in allowed_extensions:
            return jsonify({
                'success': False,
                'message': f'不支持的文件格式，请上传 {", ".join(allowed_extensions)} 格式的视频'
            }), 400

        # 初始化统一任务管理器（幂等）
        try:
            _init_tm(DATA_DIR)
        except Exception:
            pass

        # 获取表单数据
        title = request.form.get('title', '').strip() or os.path.splitext(file.filename)[0]
        description = request.form.get('description', '').strip()
        library_id = request.form.get('library_id')

        # 所有资源必须有归属，且只能上传到「已激活且有写入权限」的资源库。
        # 未激活的库对外不可见，自然也不可作为上传目标；只读用户无写入权限。
        try:
            library_id = int(library_id) if library_id else None
        except (TypeError, ValueError):
            library_id = None
        _uid, _role = resolve_identity()
        if library_id is None:
            library_id = default_library_id()
        if library_id is not None and not _user_can_write_library(_uid, library_id, _role):
            return jsonify({'success': False, 'message': '该资源库无写入权限', 'code': 403}), 403
        if library_id is None:
            return jsonify({'success': False, 'message': '资源不存在', 'code': 404}), 404

        # 确定上传目录
        upload_dir = os.path.join(DATA_DIR, 'uploads')  # 默认上传目录

        # 获取该库的默认上传路径
        if library_id:
            try:
                # 使用 resource.db 中的库 ID
                res_lib_id = _resolve_resource_library_id(library_id)
                # 通过总线查询 resourced 服务的默认路径
                if resource_bus:
                    result = resource_bus.call_method(
                        'com.dbox.resourced',
                        'com.dbox.Resourced',
                        'GetDefaultUploadPath',
                        {'library_id': res_lib_id},
                        timeout=3000
                    )
                    if result and result.get('success') and result.get('path'):
                        upload_dir = result['path']
                        log.debug('INFO', f'使用库 {library_id} 的默认上传路径: {upload_dir}')
            except Exception as e:
                log.debug('WARN', f'获取库默认路径失败，使用默认上传目录: {e}')

        # 确保上传目录存在
        os.makedirs(upload_dir, exist_ok=True)

        # 生成唯一文件名
        import uuid
        unique_id = str(uuid.uuid4())[:8]
        safe_filename = f"{unique_id}_{file.filename}"
        file_path = os.path.join(upload_dir, safe_filename)

        # 保存文件
        file.save(file_path)

        # 创建上传任务（统一任务管理器），用于前端「任务」页展示进度
        upload_task_id = 'upload:' + os.path.splitext(safe_filename)[0]
        try:
            create_task(
                upload_task_id, 'upload', f'上传：{title}',
                owner_id=user_id, library_id=library_id if isinstance(library_id, int) else None,
                status='running', progress=50, stage='保存文件', detail='文件已接收，正在计算指纹',
                params={'title': title, 'filename': safe_filename, 'library_id': library_id}
            )
        except Exception as e:
            log.debug('WARN', f'创建上传任务失败: {e}')

        # 生成视频hash
        video_hash = Video.generate_hash(file_path)

        # 检查是否已存在
        existing = Video.query.filter_by(hash=video_hash).first()
        if existing:
            os.remove(file_path)
            try:
                update_task(upload_task_id, status='failed', stage='重复', detail='该视频已存在，已取消上传')
            except Exception:
                pass
            return jsonify({
                'success': False,
                'message': '该视频已存在',
                'video': existing.to_dict()
            }), 409

        # 获取文件大小
        file_size = os.path.getsize(file_path)

        # 检查视频集权限（仅管理员可上传到任意视频集）
        if library_id:
            library = ResourceLibrary.query.get(library_id)
            if not library:
                os.remove(file_path)
                return jsonify({'success': False, 'message': '视频集不存在'}), 400

            # 检查权限 - ROOT 和管理员可以上传到任意资源库
            if g.role not in [UserRole.ADMIN, UserRole.ROOT]:
                # 检查直接权限
                perm = LibraryPermission.query.filter_by(
                    library_id=library_id, user_id=g.user_id
                ).first()
                # 检查用户组权限
                has_permission = False
                if perm and perm.access_level in ['full', 'write']:
                    has_permission = True
                else:
                    members = LibraryUserGroupMember.query.filter_by(user_id=g.user_id).all()
                    for m in members:
                        group_perm = LibraryPermission.query.filter_by(
                            library_id=library_id, group_id=m.group_id
                        ).first()
                        if group_perm and group_perm.access_level in ['full', 'write']:
                            has_permission = True
                            break

                if not has_permission:
                    os.remove(file_path)
                    return jsonify({'success': False, 'message': '无权上传到该视频集'}), 403
        else:
            library_id = None

        # 创建视频记录
        video = Video(
            hash=video_hash,
            title=title,
            description=description,
            url=f'/local_video/{quote(file_path.replace(chr(92), "/"), safe=":/")}',
            local_path=file_path,
            file_size=file_size,
            duration=extract_mp4_duration(file_path),
            thumbnail=f'/thumbnail/{video_hash}',
            library_id=library_id,
            owner_id=user_id  # 归属上传者
        )

        db.session.add(video)
        db.session.commit()
        log.maintenance('INFO', f"上传视频: {title} (hash: {video_hash}, 大小: {file_size}, 路径: {file_path})")

        # 更新上传任务进度（入库完成）
        try:
            update_task(upload_task_id, progress=60, stage='入库完成', detail='视频记录已写入数据库')
        except Exception as e:
            log.debug('WARN', f'更新上传任务失败: {e}')

        # 异步生成真实缩略图（走 thumbnaild 总线，产出 poster/sprite/vtt 三件套）
        try:
            def _gen_thumb():
                try:
                    update_task(upload_task_id, progress=80, stage='生成缩略图', detail='正在生成预览图')
                except Exception:
                    pass
                try:
                    bus = runtime.thumbnail_bus
                    if bus is not None:
                        bus.call_method(
                            service='com.dbox.thumbnaild',
                            interface='com.dbox.Thumbnaild',
                            method='Generate',
                            params={
                                'video_path': file_path,
                                'video_hash': video_hash,
                                'output_format': runtime.app_config.get('thumbnails', {}).get('output_format', 'sprite'),
                            }
                        )
                    update_task(upload_task_id, progress=100, status='completed',
                                stage='完成', detail='上传成功，缩略图已生成')
                except Exception as e:
                    log.debug('WARN', f'上传后异步生成缩略图失败: hash={video_hash}, 错误={e}')
                    # 缩略图失败不影响主任务，仍标记为完成
                    update_task(upload_task_id, progress=100, status='completed',
                                stage='完成', detail='上传成功（缩略图生成失败，可稍后重试）')

            threading.Thread(target=_gen_thumb, daemon=True).start()
        except Exception as e:
            log.debug('WARN', f'启动缩略图生成线程失败: {e}')
            try:
                update_task(upload_task_id, progress=100, status='completed',
                            stage='完成', detail='上传成功')
            except Exception:
                pass

        log_operation('upload video', target=video.hash, detail=f'标题={title}', success=True)
        return jsonify({
            'success': True,
            'message': '上传成功',
            'video': video.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f'上传视频失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/videos/batch-delete', methods=['POST'])
@admin_required
def batch_delete_videos():
    """批量删除视频"""
    try:
        data = request.get_json()
        hashes = data.get('hashes', [])
        # 获取是否同时删除文件的选项（默认不删除文件）
        delete_file = data.get('delete_file', False)

        if not hashes:
            return jsonify({'success': False, 'message': '未选择视频'}), 400

        deleted_count = 0
        for video_hash in hashes:
            video = Video.query.filter_by(hash=video_hash).first()
            if not video:
                continue
            if delete_file:
                # 管理员选择「永久删除」
                purge_trash(video, 'video')
            else:
                # 默认移入回收站（软删除，保留关联记录以便恢复）
                move_to_trash(video, 'video')
            deleted_count += 1

        db.session.commit()
        log.maintenance('INFO', f"批量删除视频: {deleted_count}个, 删除文件: {delete_file}")
        log_operation('batch delete videos', target=f'{deleted_count}个', detail=f'删除文件={delete_file}', success=True)
        return jsonify({
            'success': True,
            'message': f'已删除 {deleted_count} 个视频',
            'deleted_count': deleted_count
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/stats/overview', methods=['GET'])
def stats_overview():
    """统计概览：视频总数、各资源库数量、按标签视频数 Top、最热视频

    所有计数均经 apply_video_visibility 收敛，仅统计「当前用户可见（库已激活 +
    未删除 + 未隐藏）」的资源，确保取消资源库激活后统计数字同步下降、外界不可见。
    """
    try:
        # 可见视频总数
        total = apply_video_visibility(Video.query).count()

        by_library = []
        for lib in ResourceLibrary.query.filter_by(is_active=True).all():
            cnt = apply_video_visibility(
                Video.query.filter_by(library_id=lib.id)
            ).count()
            by_library.append({'id': lib.id, 'name': lib.name, 'count': cnt})

        # 按标签视频数 Top 10（仅可见视频的标签）
        tag_counts = db.session.query(
            Tag.name, db.func.count(VideoTag.tag_id)
        ).join(VideoTag, Tag.id == VideoTag.tag_id).join(
            Video, Video.id == VideoTag.video_id
        ).filter(
            Video.library_id.in_(get_allowed_library_ids()),
            Video.in_trash == False,
            ~Video.resource_index.has(ResourceIndex.hidden == True),
        ).group_by(Tag.id).order_by(
            db.func.count(VideoTag.tag_id).desc()
        ).limit(10).all()
        top_tags = [{'name': t[0], 'count': t[1]} for t in tag_counts]

        # 最热视频（点赞最多 / 收藏最多），仅可见视频
        top_liked = [v.to_dict() for v in apply_video_visibility(
            Video.query.order_by(Video.like_count.desc())
        ).options(joinedload(Video.resource_index)).limit(10).all()]
        top_favorited = [v.to_dict() for v in apply_video_visibility(
            Video.query.order_by(Video.favorite_count.desc())
        ).options(joinedload(Video.resource_index)).limit(10).all()]

        # 标签总数与用户总数（用于后台仪表盘概览卡片）
        total_tags = Tag.query.count()
        total_users = User.query.count()

        return jsonify({
            'success': True,
            'total': total,
            'total_tags': total_tags,
            'total_users': total_users,
            'by_library': by_library,
            'top_tags': top_tags,
            'top_liked': top_liked,
            'top_favorited': top_favorited,
        })
    except Exception as e:
        log.debug('ERROR', f"统计概览失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/tags/search', methods=['GET'])
def search_tags():
    """搜索标签 - 用于智能提示，按路径匹配"""
    try:
        keyword = request.args.get('q', '').strip()
        library_id = request.args.get('library_id', type=int)  # 可选，按资源库筛选
        limit = request.args.get('limit', 20, type=int)

        if not keyword:
            return jsonify({'success': True, 'tags': []})

        # 获取当前用户权限
        user_id = getattr(g, 'user_id', None)
        user_role = getattr(g, 'role', None)

        # 判断是否是管理员/ROOT
        is_admin = user_id and user_role in [2, 3]  # ADMIN=2, ROOT=3

        # 构建查询：匹配路径包含关键词的标签
        query = Tag.query.filter(Tag.path.like(f'%{keyword}%'))

        # ============ 优先级：如果指定了 library_id，优先返回该资源库的标签 ============
        if library_id:
            # 验证用户是否有权限访问该资源库
            if not is_admin:
                # 管理员/ROOT 可以搜索任何资源库的标签
                # 检查用户是否有权限访问该资源库
                user_perm = LibraryPermission.query.filter_by(
                    library_id=library_id, user_id=user_id
                ).first()

                # 检查用户组权限
                has_access = bool(user_perm)
                if not has_access:
                    user_groups = LibraryUserGroupMember.query.filter_by(user_id=user_id).all()
                    for ugm in user_groups:
                        group_perm = LibraryPermission.query.filter_by(
                            library_id=library_id, group_id=ugm.group_id
                        ).first()
                        if group_perm:
                            has_access = True
                            break

                # 如果没有权限，只能看全局标签
                if not has_access:
                    query = query.filter(Tag.library_id == None)
                else:
                    # 有权限：全局标签 + 该资源库标签
                    query = query.filter(
                        (Tag.library_id == None) |
                        (Tag.library_id == library_id)
                    )
            else:
                # 管理员：全局标签 + 该资源库标签
                query = query.filter(
                    (Tag.library_id == None) |
                    (Tag.library_id == library_id)
                )
        else:
            # 未指定 library_id：普通用户只能看到自己有权限的库的标签 + 全局标签
            if not is_admin:
                allowed_library_ids = []

                if user_id:
                    # 已登录普通用户：获取有权限的资源库ID
                    # 直接权限
                    perms = LibraryPermission.query.filter_by(user_id=user_id).all()
                    allowed_library_ids.extend([p.library_id for p in perms])

                    # 用户组权限
                    group_members = LibraryUserGroupMember.query.filter_by(user_id=user_id).all()
                    for gm in group_members:
                        group_perms = LibraryPermission.query.filter_by(group_id=gm.group_id).all()
                        allowed_library_ids.extend([p.library_id for p in group_perms])

                    # 允许查看：全局标签(null) + 有权限的资源库标签
                    if allowed_library_ids:
                        query = query.filter(
                            (Tag.library_id == None) |
                            (Tag.library_id.in_(allowed_library_ids))
                        )
                # else: 未登录用户，只能看到全局标签

        # 限制结果数量
        tags = query.order_by(Tag.path).limit(limit).all()

        return jsonify({
            'success': True,
            'tags': [t.to_dict() for t in tags]
        })
    except Exception as e:
        log.debug('ERROR', f"搜索标签失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/scan', methods=['POST'])
def scan_videos():
    try:
        # 扫描发现的资源归属 root（id=1），管理员对所有资源有权限
        root_user = User.query.filter_by(role=UserRole.ROOT).order_by(User.id).first()
        root_id = root_user.id if root_user else 1
        total_added = 0
        for dir_cfg in runtime.app_config.get('scan_directories', []):
            if not dir_cfg.get('enabled', True):
                continue
            
            dir_path = dir_cfg.get('path', '')
            if not os.path.exists(dir_path):
                continue
            
            for root, _, files in os.walk(dir_path):
                for f in files:
                    if any(f.lower().endswith(ext) for ext in runtime.app_config.get('supported_formats', [])):
                        video_path = os.path.join(root, f)
                        video_hash = Video.generate_hash(video_path)
                        
                        if Video.query.filter_by(hash=video_hash).first():
                            continue
                        
                        title = os.path.splitext(f)[0]
                        video = Video(
                            hash=video_hash,
                            title=title,
                            description=f'本地视频: {f}',
                            url=f'/local_video/{quote(video_path.replace(chr(92), "/"), safe=":/")}',
                            thumbnail=f'/thumbnail/{video_hash}',
                            is_downloaded=True,
                            local_path=video_path,
                            owner_id=root_id
                        )
                        db.session.add(video)
                        db.session.flush()
                        
                        for tag_name in runtime.app_config.get('default_tags', []):
                            tag = Tag.query.filter_by(name=tag_name).first()
                            if not tag:
                                tag = Tag(name=tag_name, category='类型')
                                tag.path = f'/{tag_name}'  # 计算完整路径
                                db.session.add(tag)
                                db.session.flush()
                            db.session.add(VideoTag(video_id=video.id, tag_id=tag.id))
                        
                        total_added += 1
        
        db.session.commit()
        log_operation('scan new videos', target=f'{total_added}个', success=True)
        return jsonify({'success': True, 'message': f'添加了 {total_added} 个视频', 'total_added': total_added})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/tags', methods=['GET'])
def get_tags():
    """获取标签列表 - 支持树形结构，融合模式可跨资源库聚合"""
    try:
        # 获取参数
        tree_mode = request.args.get('tree', 'false').lower() == 'true'
        library_id = request.args.get('library_id', type=int)  # 可选，按资源库筛选
        merge_mode = request.args.get('merge', 'false').lower() == 'true'  # 融合模式
        
        # ============ 获取用户可访问的资源库 ============
        user_id = None
        user_role = 0
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            try:
                from authlib.jose import jwt as _jwt
                _secret = 'dbox-jwt-secret-key-change-in-production-2024'
                _payload = _jwt.decode(auth_header[7:], _secret)
                user_id = _payload.get('user_id')
                user_role = _payload.get('role', 0)
            except Exception:
                pass
        user_id, user_role = resolve_identity()

        allowed_library_ids = []
        
        if user_id:
            if user_role in [UserRole.ADMIN, UserRole.ROOT]:
                all_active_libs = ResourceLibrary.query.filter_by(is_active=True).all()
                allowed_library_ids = [lib.id for lib in all_active_libs]
            else:
                user_perms = LibraryPermission.query.filter_by(user_id=user_id).all()
                for perm in user_perms:
                    lib = ResourceLibrary.query.get(perm.library_id)
                    if lib and lib.is_active:
                        allowed_library_ids.append(perm.library_id)
                
                user_groups = LibraryUserGroupMember.query.filter_by(user_id=user_id).all()
                for ugm in user_groups:
                    group_perms = LibraryPermission.query.filter_by(group_id=ugm.group_id).all()
                    for perm in group_perms:
                        lib = ResourceLibrary.query.get(perm.library_id)
                        if lib and lib.is_active and perm.library_id not in allowed_library_ids:
                            allowed_library_ids.append(perm.library_id)
        
        is_admin = user_id and user_role in [2, 3]
        
        # 检查用户是否有资源库权限
        has_library_access = is_admin or (user_id and allowed_library_ids)
        
        # ============ 融合模式：合并相同路径的标签 ============
        if merge_mode:
            # 查询所有用户可见的标签（只有有资源库权限时才过滤）
            if has_library_access and not is_admin:
                query = Tag.query.filter(
                    (Tag.library_id == None) | 
                    (Tag.library_id.in_(allowed_library_ids))
                )
            else:
                query = Tag.query
            
            all_tags = query.all()
            
            # 按路径分组，合并视频数量
            from sqlalchemy import or_ as sql_or
            path_video_map = {}  # {path: total_video_count}
            
            for tag in all_tags:
                tag_ids = tag.get_all_child_ids()
                video_query = Video.query.join(VideoTag).filter(VideoTag.tag_id.in_(tag_ids)).filter(Video.in_trash == False)
                
                if has_library_access and not is_admin:
                    video_query = video_query.filter(
                        sql_or(
                            Video.library_id == None,
                            Video.library_id.in_(allowed_library_ids)
                        )
                    )
                
                video_count = video_query.count()
                
                if tag.path in path_video_map:
                    path_video_map[tag.path] += video_count
                else:
                    path_video_map[tag.path] = video_count
            
            # 构建融合后的标签列表
            result_tags = []
            seen_paths = set()
            for tag in all_tags:
                if tag.path in seen_paths:
                    continue
                seen_paths.add(tag.path)
                
                video_count = path_video_map.get(tag.path, 0)
                # 非管理员用户：如果没有资源库权限，不显示任何标签
                if not has_library_access:
                    continue
                # 如果没有可访问的活跃资源库（即使管理员），也不显示标签
                if not allowed_library_ids:
                    continue
                if video_count > 0:
                    tag_dict = tag.to_dict()
                    tag_dict['video_count'] = video_count
                    result_tags.append(tag_dict)
            
            result_tags.sort(key=lambda t: t['video_count'], reverse=True)
            
            if tree_mode:
                tree = _build_tag_tree(result_tags)
                return jsonify({'success': True, 'tags': tree})
            
            return jsonify({'success': True, 'tags': result_tags})
        
        # ============ 普通模式（原有逻辑）==========
        if has_library_access and not is_admin:
            query = Tag.query.filter(
                (Tag.library_id == None) | 
                (Tag.library_id.in_(allowed_library_ids))
            )
        else:
            query = Tag.query
        
        if library_id:
            query = query.filter(
                (Tag.library_id == None) | 
                (Tag.library_id == library_id)
            )
        
        tags = query.all()
        
        from sqlalchemy import or_ as sql_or
        result_tags = []
        for tag in tags:
            tag_ids = tag.get_all_child_ids()
            video_query = Video.query.join(VideoTag).filter(VideoTag.tag_id.in_(tag_ids)).filter(Video.in_trash == False)
            
            if has_library_access and not is_admin:
                video_query = video_query.filter(
                    sql_or(
                        Video.library_id == None,
                        Video.library_id.in_(allowed_library_ids)
                    )
                )
            
            video_count = video_query.count()
            
            # 非管理员用户：如果没有资源库权限，不显示任何标签
            if not has_library_access:
                continue

            # 如果没有可访问的活跃资源库（即使管理员），也不显示标签
            if not allowed_library_ids:
                continue

            if video_count > 0:
                tag_dict = tag.to_dict()
                tag_dict['video_count'] = video_count
                result_tags.append(tag_dict)
        
        result_tags.sort(key=lambda t: t['video_count'], reverse=True)
        
        if tree_mode:
            tree = _build_tag_tree(result_tags)
            return jsonify({'success': True, 'tags': tree})
        
        return jsonify({'success': True, 'tags': result_tags})
    except Exception as e:
        log.debug('ERROR', f"获取标签列表失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/tags/all', methods=['GET'])
def get_all_tags():
    """获取所有标签（不进行权限过滤）。
    支持 library_id 筛选：传入时只返回该资源库标签 + 全局标签（library_id 为 null），
    实现「视频属于哪个资源库，就只能使用该资源库的标签集」的隔离。"""
    try:
        library_id = request.args.get('library_id', type=int)
        query = Tag.query
        if library_id is not None:
            query = query.filter(
                (Tag.library_id == library_id) | (Tag.library_id.is_(None))
            )
        tags = query.all()
        result = []
        for tag in tags:
            result.append({
                'id': tag.id,
                'name': tag.name,
                'path': tag.path,  # 添加完整路径
                'category': tag.category,
                'parent_id': tag.parent_id,
                'library_id': tag.library_id,
                'video_count': tag.video_count()
            })
        return jsonify({'success': True, 'tags': result})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
