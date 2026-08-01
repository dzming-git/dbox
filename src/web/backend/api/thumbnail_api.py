"""Auto-split blueprint: thumbnail_api (moved from main.py)."""
from core.models import LibraryPermission
from core.models import LibraryUserGroupMember
from core.models import Video
from core.models import UserRole
from backend.thumbnail_helpers import _save_thumb_config
import threading
from backend.access import resolve_identity
from backend.thumbnail_helpers import _generate_missing_thumbnails
from backend.thumbnail_helpers import _thumb_auto_stop_event
from backend.thumbnail_helpers import _start_auto_generate
from backend.thumbnail_helpers import _thumb_auto_thread
from backend.thumbnail_helpers import _load_thumb_config
import os
from backend.access import admin_required
from backend.paths import DATA_DIR
from flask import Blueprint, request, jsonify, send_file, send_from_directory, session, g, abort, Response, current_app
from liblog import get_service_logger
log = get_service_logger('dplayer-web')

bp = Blueprint('thumbnail_api', __name__)

@bp.route('/thumbnail/<video_hash>')
def get_thumbnail(video_hash):
    """获取缩略图，支持懒加载生成 - 需要检查资源库权限"""
    thumb_dir = os.path.join(DATA_DIR, 'thumbnails')

    # 先尝试查找已存在的文件
    for ext in ['gif', 'jpg', 'png']:
        path = os.path.join(thumb_dir, f'{video_hash}.{ext}')
        if os.path.exists(path):
            resp = send_file(path, mimetype=f'image/{ext}')
            resp.cache_control.max_age = 3600
            return resp

    # 文件不存在，尝试懒加载生成
    try:
        # 查找视频的本地路径
        video = Video.query.filter_by(hash=video_hash).first()
        if not video or not video.local_path:
            # 没有视频记录或本地路径，返回404
            abort(404)

        # ============ 权限检查 ============
        # 检查视频是否属于某个资源库
        if video.library_id:
            # 获取用户ID和角色
            user_id = None
            user_role = 0

            # 方式1: 从 Authorization header 获取 token
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                try:
                    from authlib.jose import jwt as _jwt
                    _secret = 'dplayer-jwt-secret-key-change-in-production-2024'
                    _payload = _jwt.decode(auth_header[7:], _secret)
                    user_id = _payload.get('user_id')
                    user_role = _payload.get('role', 0)
                except Exception:
                    pass

            # 方式2: 从查询参数 token 获取（用于 <img> 标签）
            if not user_id:
                query_token = request.args.get('token', '')
                if query_token:
                    try:
                        from authlib.jose import jwt as _jwt
                        _secret = 'dplayer-jwt-secret-key-change-in-production-2024'
                        _payload = _jwt.decode(query_token, _secret)
                        user_id = _payload.get('user_id')
                        user_role = _payload.get('role', 0)
                    except Exception:
                        pass

            # 方式3: 从 session 获取
            user_id, user_role = resolve_identity()

            # 管理员和ROOT可以访问所有缩略图
            if user_role not in [UserRole.ADMIN, UserRole.ROOT]:
                # 检查用户权限
                user_perm = LibraryPermission.query.filter_by(
                    library_id=video.library_id, user_id=user_id
                ).first()
                
                # 检查通用权限（user_id=NULL 表示所有人都可以访问）
                general_perm = LibraryPermission.query.filter_by(
                    library_id=video.library_id, user_id=None
                ).first()

                # 检查用户组权限
                has_access = bool(user_perm) or bool(general_perm)
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
                    abort(403)

        # 调用缩略图服务异步生成（后台线程，不阻塞当前请求）
        if thumbnail_bus:
            video_path = video.local_path
            _hash = video_hash

            def _async_generate(vp, vh):
                try:
                    thumbnail_bus.call_method(
                        service='com.dplayer.thumbnaild',
                        interface='com.dplayer.Thumbnaild',
                        method='Generate',
                        params={'video_path': vp, 'video_hash': vh, 'output_format': 'gif'}
                    )
                except Exception as e:
                    log.debug('ERROR', f"后台封面生成失败: {e}")

            threading.Thread(target=_async_generate, args=(video_path, _hash), daemon=True).start()

        # 服务不可用或生成失败，返回 JSON 状态让前端轮询
        return jsonify({
            'success': False,
            'status': 'generating',
            'message': '缩略图正在生成中',
            'video_hash': video_hash
        }), 202

    except Exception as e:
        log.debug('ERROR', f"缩略图生成失败: {e}")
        return jsonify({
            'success': False,
            'status': 'error',
            'message': str(e),
            'video_hash': video_hash
        }), 202

@bp.route('/api/thumbnail/status/<video_hash>', methods=['GET'])
def get_thumbnail_status(video_hash):
    """检查缩略图是否存在（已简化，不触发生成，由后端自动生成）"""
    thumb_dir = os.path.join(DATA_DIR, 'thumbnails')

    # 检查文件是否存在
    for ext in ['gif', 'jpg', 'png']:
        path = os.path.join(thumb_dir, f'{video_hash}.{ext}')
        if os.path.exists(path):
            return jsonify({
                'success': True,
                'status': 'ready',
                'url': f'/thumbnail/{video_hash}',
                'format': ext
            })

    # 缩略图不存在
    return jsonify({
        'success': False,
        'status': 'not_found',
        'message': '缩略图尚未生成'
    })

@bp.route('/api/thumbnail/<video_hash>', methods=['DELETE'])
def delete_thumbnail(video_hash):
    """删除指定视频的缩略图"""
    thumb_dir = os.path.join(DATA_DIR, 'thumbnails')

    deleted = False
    # 删除所有格式的缩略图文件
    for ext in ['gif', 'jpg', 'png']:
        path = os.path.join(thumb_dir, f'{video_hash}.{ext}')
        if os.path.exists(path):
            try:
                os.remove(path)
                deleted = True
            except Exception as e:
                log.debug('ERROR', f"删除缩略图文件失败: {e}")

    if deleted:
        return jsonify({'success': True, 'message': '缩略图已删除'})
    else:
        return jsonify({'success': False, 'message': '缩略图文件不存在'})

@bp.route('/api/thumbnail/regenerate/<video_hash>', methods=['POST'])
def regenerate_thumbnail(video_hash):
    """重新生成指定视频的缩略图"""
    # 先删除旧缩略图
    thumb_dir = os.path.join(DATA_DIR, 'thumbnails')
    for ext in ['gif', 'jpg', 'png']:
        path = os.path.join(thumb_dir, f'{video_hash}.{ext}')
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                log.debug('ERROR', f"删除旧缩略图失败: {e}")

    # 查找视频
    video = Video.query.filter_by(hash=video_hash).first()
    if not video or not video.local_path:
        return jsonify({'success': False, 'message': '视频不存在或无本地路径'}), 404

    # 调用缩略图服务重新生成
    if thumbnail_bus:
        try:
            result = thumbnail_bus.call_method(
                service='com.dplayer.thumbnaild',
                interface='com.dplayer.Thumbnaild',
                method='Generate',
                params={'video_path': video.local_path, 'video_hash': video_hash, 'output_format': 'gif'}
            )
            if result and result.get('success'):
                return jsonify({
                    'success': True,
                    'message': '缩略图重新生成中',
                    'task_id': result.get('task_id')
                })
            else:
                return jsonify({'success': False, 'message': result.get('error', '生成失败')}), 500
        except Exception as e:
            log.debug('ERROR', f"重新生成缩略图失败: {e}")
            return jsonify({'success': False, 'message': str(e)}), 500
    else:
        return jsonify({'success': False, 'message': '缩略图服务不可用'}), 503

@bp.route('/api/admin/thumbnail/config', methods=['GET'])
@admin_required
def get_thumbnail_config():
    """获取缩略图管理配置"""
    try:
        config = _load_thumb_config()

        # 获取缩略图统计信息
        thumb_dir = os.path.join(DATA_DIR, 'thumbnails')
        total_thumbnails = 0
        if os.path.exists(thumb_dir):
            total_thumbnails = len([f for f in os.listdir(thumb_dir)
                                     if f.lower().endswith(('.gif', '.jpg', '.png'))])

        # 获取无缩略图的视频数量
        from core.models import Video
        db_videos = Video.query.all()
        no_thumb_count = 0
        for v in db_videos:
            if v.hash:
                has_thumb = any(
                    os.path.exists(os.path.join(thumb_dir, f'{v.hash}.{ext}'))
                    for ext in ['gif', 'jpg', 'png']
                )
                if not has_thumb:
                    no_thumb_count += 1

        # 获取缩略图服务状态
        thumb_service_status = 'unknown'
        thumb_service_stats = None
        if thumbnail_bus:
            try:
                thumb_service_stats = thumbnail_bus.call_method(
                    service='com.dplayer.thumbnaild',
                    interface='com.dplayer.Thumbnaild',
                    method='GetMetrics',
                    params={}
                )
                if thumb_service_stats:
                    thumb_service_status = 'running'
                else:
                    thumb_service_status = 'error'
            except Exception:
                thumb_service_status = 'offline'

        # 获取自动生成线程状态
        is_auto_running = _thumb_auto_thread is not None and _thumb_auto_thread.is_alive()

        return jsonify({
            'success': True,
            'config': config,
            'stats': {
                'total_videos': len(db_videos),
                'total_thumbnails': total_thumbnails,
                'no_thumbnail_count': no_thumb_count,
                'thumb_service_status': thumb_service_status,
                'thumb_service_stats': thumb_service_stats,
                'is_auto_generating': is_auto_running
            }
        })
    except Exception as e:
        log.debug('ERROR', f'获取缩略图配置失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/thumbnail/config', methods=['POST'])
@admin_required
def update_thumbnail_config():
    """更新缩略图管理配置"""
    try:
        data = request.get_json()
        config = _load_thumb_config()

        # 只允许更新指定字段
        allowed_fields = ['auto_generate', 'max_workers', 'task_interval', 'auto_generate_interval']
        for field in allowed_fields:
            if field in data:
                # 参数校验
                if field == 'max_workers':
                    config[field] = max(1, min(int(data[field]), 8))
                elif field == 'task_interval':
                    config[field] = max(1, min(int(data[field]), 60))
                elif field == 'auto_generate_interval':
                    config[field] = max(300, min(int(data[field]), 86400))  # 5分钟 ~ 24小时
                elif field == 'auto_generate':
                    config[field] = bool(data[field])

        if _save_thumb_config(config):
            log.maintenance('INFO', f'缩略图配置已更新: {config}')

            # 如果开启了自动生成，启动后台线程
            if config['auto_generate'] and (_thumb_auto_thread is None or not _thumb_auto_thread.is_alive()):
                _start_auto_generate(config)
            # 如果关闭了自动生成，停止后台线程
            elif not config['auto_generate'] and _thumb_auto_thread is not None:
                _thumb_auto_stop_event.set()

            return jsonify({'success': True, 'message': '配置已保存', 'config': config})
        else:
            return jsonify({'success': False, 'message': '保存配置失败'}), 500
    except Exception as e:
        log.debug('ERROR', f'更新缩略图配置失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/thumbnail/generate-missing', methods=['POST'])
@admin_required
def generate_missing_thumbnails():
    """手动触发一次批量生成缺失缩略图（不开启自动模式）"""
    try:
        config = _load_thumb_config()
        result = _generate_missing_thumbnails(config)
        return jsonify({
            'success': True,
            'message': f'已提交生成任务',
            'submitted': result.get('submitted', 0) if result else 0
        })
    except Exception as e:
        log.debug('ERROR', f'批量生成缩略图失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/thumbnail/auto-generate/status', methods=['GET'])
@admin_required
def get_auto_generate_status():
    """获取自动生成线程状态"""
    is_running = _thumb_auto_thread is not None and _thumb_auto_thread.is_alive()
    return jsonify({
        'success': True,
        'is_running': is_running
    })

@bp.route('/api/admin/thumbnail/auto-generate/stop', methods=['POST'])
@admin_required
def stop_auto_generate():
    """停止自动生成线程"""
    global _thumb_auto_thread

    if _thumb_auto_thread is not None and _thumb_auto_thread.is_alive():
        _thumb_auto_stop_event.set()
        # 更新配置文件
        config = _load_thumb_config()
        config['auto_generate'] = False
        _save_thumb_config(config)
        log.maintenance('INFO', '缩略图自动生成已手动停止')
        return jsonify({'success': True, 'message': '自动生成已停止'})
    else:
        return jsonify({'success': True, 'message': '自动生成已停止'})
