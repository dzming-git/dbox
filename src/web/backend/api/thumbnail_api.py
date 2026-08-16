"""Auto-split blueprint: thumbnail_api (moved from main.py)."""
from core.models import LibraryPermission
from core.models import LibraryUserGroupMember
from core.models import Video
from core.models import UserRole
from core.models import db
from backend.thumbnail_helpers import _save_thumb_config
import threading
from backend.access import resolve_identity, is_video_visible
from backend.thumbnail_helpers import _generate_missing_thumbnails
from backend.thumbnail_helpers import _get_visible_library_ids
from backend.thumbnail_helpers import resolve_thumbnail_path_for_video
from backend.thumbnail_helpers import _thumb_auto_stop_event
from backend.thumbnail_helpers import _start_auto_generate
from backend.thumbnail_helpers import _thumb_auto_thread
from backend.thumbnail_helpers import get_auto_generate_progress
from backend.thumbnail_helpers import _load_thumb_config
import os
import json
from backend.access import admin_required
from backend.paths import DATA_DIR
from backend.runtime import runtime
from flask import Blueprint, request, jsonify, send_file, send_from_directory, session, g, abort, Response, current_app
from liblog import get_service_logger
log = get_service_logger('dbox-web')

bp = Blueprint('thumbnail_api', __name__)


def compute_thumb_stats():
    """实时计算缩略图统计：视频总数、缩略图文件数、缺失数量。

    抽成独立函数，供配置接口与自动生成状态轮询接口复用，确保进度推进时
    缺失数量能实时下降（卡片数字之前只在页面加载时计算一次，从不刷新）。

    设计原则：资源库管理服务（ResourceLibrary.is_active）掌控着资源的对外出口，
    缩略图统计只应计入「已激活」资源库下的资源，而非磁盘上全部缩略图文件。
    因此「已有缩略图」也按视频 hash 归属过滤，仅统计属于已激活库视频的缩略图。
    """
    from core.models import Video
    from backend.thumbnail_helpers import resolve_thumbnail_path_for_video

    # 先确定「已激活」资源库
    visible_ids = _get_visible_library_ids()
    if visible_ids:
        db_videos = Video.query.filter(Video.library_id.in_(visible_ids)).all()
    else:
        db_videos = []

    total_thumbnails = 0
    no_thumbnail_count = 0
    for v in db_videos:
        if not v.hash:
            # 没有 hash 的资源无法生成缩略图，归入缺失
            no_thumbnail_count += 1
            continue
        # 逐资源解析索引规定的缩略图路径，并验证文件真实存在；
        # 不以文件夹内文件数代替——索引才是缩略图位置的权威来源。
        path = resolve_thumbnail_path_for_video(v)
        if path and os.path.exists(path):
            total_thumbnails += 1
        else:
            no_thumbnail_count += 1

    return {
        'total_videos': len(db_videos),
        'total_thumbnails': total_thumbnails,
        'no_thumbnail_count': no_thumbnail_count,
    }

@bp.route('/thumbnail/<video_hash>')
def get_thumbnail(video_hash):
    """获取缩略图，支持懒加载生成 - 需要检查资源库权限"""
    # 权限必须先于文件读取：缩略图缓存文件以 hash 命名且长期驻留磁盘，
    # 若先返回文件再校验，未激活资源库的封面仍可被直接取走。
    video = Video.query.filter_by(hash=video_hash).first()
    if not is_video_visible(video):
        abort(404)

    # 以资源索引规定的路径为准取图（可指向默认文件夹之外）；
    # 索引未规定时回退到默认文件夹下的 {hash}.{jpg|png|gif}。
    resolved = resolve_thumbnail_path_for_video(video) if video else None
    if resolved and os.path.exists(resolved):
        ext = os.path.splitext(resolved)[1].lstrip('.').lower() or 'jpg'
        mime = 'image/jpeg' if ext == 'jpg' else f'image/{ext}'
        resp = send_file(resolved, mimetype=mime)
        # 缩略图文件会在重新生成时改变内容（同 hash），固定 1h 缓存会导致用户
        # 即便在服务端重建后仍长时间看到旧图。缩到 60s 并强制协商，兼顾性能
        # 与修复后的即时可见性。
        resp.cache_control.max_age = 60
        resp.cache_control.must_revalidate = True
        return resp

    # 默认文件夹回退（兼容索引未记录路径的老数据）
    thumb_dir = os.path.join(DATA_DIR, 'thumbnails')
    for ext in ['jpg', 'png', 'gif']:
        path = os.path.join(thumb_dir, f'{video_hash}.{ext}')
        if os.path.exists(path):
            mime = 'image/jpeg' if ext == 'jpg' else f'image/{ext}'
            resp = send_file(path, mimetype=mime)
            resp.cache_control.max_age = 60
            resp.cache_control.must_revalidate = True
            return resp

    # 文件不存在，尝试懒加载生成（output_format=sprite 会同时产出 poster/sprite/vtt）
    try:
        if not video.local_path:
            abort(404)

        # 调用缩略图服务异步生成（后台线程，不阻塞当前请求）
        if runtime.thumbnail_bus:
            video_path = video.local_path
            _hash = video_hash

            def _async_generate(vp, vh):
                try:
                    output_format = runtime.app_config.get('thumbnails', {}).get('output_format', 'sprite')
                    runtime.thumbnail_bus.call_method(
                        service='com.dbox.thumbnaild',
                        interface='com.dbox.Thumbnaild',
                        method='Generate',
                        params={'video_path': vp, 'video_hash': vh, 'output_format': output_format}
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

@bp.route('/thumbnail/<video_hash>/sprite')
def get_thumbnail_sprite(video_hash):
    """获取雪碧图（悬停预览用）。权限校验同 /thumbnail/。"""
    video = Video.query.filter_by(hash=video_hash).first()
    if not is_video_visible(video):
        abort(404)
    thumb_dir = os.path.join(DATA_DIR, 'thumbnails')
    path = os.path.join(thumb_dir, f'{video_hash}.sprite.jpg')
    if not os.path.exists(path):
        abort(404)
    resp = send_file(path, mimetype='image/jpeg')
    resp.cache_control.max_age = 3600
    resp.cache_control.must_revalidate = True
    return resp

@bp.route('/thumbnail/<video_hash>/preview.vtt')
def get_thumbnail_vtt(video_hash):
    """获取 WebVTT 预览索引（雪碧图帧坐标与时间区间）。"""
    video = Video.query.filter_by(hash=video_hash).first()
    if not is_video_visible(video):
        abort(404)
    thumb_dir = os.path.join(DATA_DIR, 'thumbnails')
    path = os.path.join(thumb_dir, f'{video_hash}.vtt')
    if not os.path.exists(path):
        abort(404)
    resp = send_file(path, mimetype='text/vtt')
    resp.cache_control.max_age = 3600
    resp.cache_control.must_revalidate = True
    return resp

@bp.route('/api/thumbnail/status/<video_hash>', methods=['GET'])
def get_thumbnail_status(video_hash):
    """检查缩略图是否存在（已简化，不触发生成，由后端自动生成）"""
    thumb_dir = os.path.join(DATA_DIR, 'thumbnails')

    # 优先按资源索引规定的路径判断 poster 是否存在（可指向默认文件夹之外）
    video = Video.query.filter_by(hash=video_hash).first()
    resolved = resolve_thumbnail_path_for_video(video) if video else None
    if resolved and os.path.exists(resolved):
        ext = os.path.splitext(resolved)[1].lstrip('.').lower() or 'jpg'
        return jsonify({
            'success': True,
            'status': 'ready',
            'url': f'/thumbnail/{video_hash}',
            'format': ext,
            'has_sprite': os.path.exists(os.path.join(thumb_dir, f'{video_hash}.sprite.jpg')),
            'has_vtt': os.path.exists(os.path.join(thumb_dir, f'{video_hash}.vtt')),
        })

    # 兼容：回退到默认文件夹按 hash 判断
    for ext in ['jpg', 'png', 'gif']:
        path = os.path.join(thumb_dir, f'{video_hash}.{ext}')
        if os.path.exists(path):
            return jsonify({
                'success': True,
                'status': 'ready',
                'url': f'/thumbnail/{video_hash}',
                'format': ext,
                'has_sprite': os.path.exists(os.path.join(thumb_dir, f'{video_hash}.sprite.jpg')),
                'has_vtt': os.path.exists(os.path.join(thumb_dir, f'{video_hash}.vtt')),
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
    # 删除所有默认命名格式的缩略图文件（含 poster/sprite/vtt 全集）
    for fname in [f'{video_hash}.gif', f'{video_hash}.jpg', f'{video_hash}.png',
                  f'{video_hash}.sprite.jpg', f'{video_hash}.vtt']:
        path = os.path.join(thumb_dir, fname)
        if os.path.exists(path):
            try:
                os.remove(path)
                deleted = True
            except Exception as e:
                log.debug('ERROR', f"删除缩略图文件失败: {e}")

    # 同时删除索引规定的自定义路径缩略图（指向默认文件夹之外的情况）
    video = Video.query.filter_by(hash=video_hash).first()
    resolved = resolve_thumbnail_path_for_video(video) if video else None
    if resolved and os.path.exists(resolved):
        default_files = {os.path.join(thumb_dir, f'{video_hash}.{ext}') for ext in ('gif', 'jpg', 'png')}
        if resolved not in default_files:
            try:
                os.remove(resolved)
                deleted = True
            except Exception as e:
                log.debug('ERROR', f"删除索引规定的缩略图文件失败: {e}")

    # 清除索引中记录的缩略图路径，保持索引权威且不残留失效路径
    if video and video.resource_index is not None:
        try:
            m = video.resource_index.get_meta()
            if m.pop('thumbnail', None) is not None:
                video.resource_index.meta = json.dumps(m, ensure_ascii=False)
                db.session.add(video.resource_index)
                db.session.commit()
        except Exception as e:
            log.debug('ERROR', f"清除索引缩略图路径失败: {e}")

    if deleted:
        return jsonify({'success': True, 'message': '缩略图已删除'})
    else:
        return jsonify({'success': False, 'message': '缩略图文件不存在'})

@bp.route('/api/thumbnail/regenerate/<video_hash>', methods=['POST'])
def regenerate_thumbnail(video_hash):
    """重新生成指定视频的缩略图"""
    thumb_dir = os.path.join(DATA_DIR, 'thumbnails')

    # 查找视频
    video = Video.query.filter_by(hash=video_hash).first()
    if not video or not video.local_path:
        return jsonify({'success': False, 'message': '视频不存在或无本地路径'}), 404

    # 先删除旧缩略图（含默认命名 poster/sprite/vtt 全集）
    for fname in [f'{video_hash}.gif', f'{video_hash}.jpg', f'{video_hash}.png',
                  f'{video_hash}.sprite.jpg', f'{video_hash}.vtt']:
        path = os.path.join(thumb_dir, fname)
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                log.debug('ERROR', f"删除旧缩略图失败: {e}")

    # 同时删除索引规定的自定义路径缩略图（指向默认文件夹之外的情况）
    resolved = resolve_thumbnail_path_for_video(video)
    if resolved and os.path.exists(resolved):
        default_files = {os.path.join(thumb_dir, f'{video_hash}.{ext}') for ext in ('gif', 'jpg', 'png')}
        if resolved not in default_files:
            try:
                os.remove(resolved)
            except Exception as e:
                log.debug('ERROR', f"删除索引规定的旧缩略图失败: {e}")

    # 清除索引中记录的旧缩略图路径，待重新生成后再由索引重新规定
    if video.resource_index is not None:
        try:
            m = video.resource_index.get_meta()
            if m.pop('thumbnail', None) is not None:
                video.resource_index.meta = json.dumps(m, ensure_ascii=False)
                db.session.add(video.resource_index)
                db.session.commit()
        except Exception as e:
            log.debug('ERROR', f"清除索引旧缩略图路径失败: {e}")

    # 调用缩略图服务重新生成
    if runtime.thumbnail_bus:
        try:
            output_format = runtime.app_config.get('thumbnails', {}).get('output_format', 'sprite')
            result = runtime.thumbnail_bus.call_method(
                service='com.dbox.thumbnaild',
                interface='com.dbox.Thumbnaild',
                method='Generate',
                params={'video_path': video.local_path, 'video_hash': video_hash, 'output_format': output_format}
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

        # 获取缩略图统计信息（实时计算，确保前后端一致）
        thumb_stats = compute_thumb_stats()

        # 获取缩略图服务状态
        thumb_service_status = 'unknown'
        thumb_service_stats = None
        if runtime.thumbnail_bus:
            try:
                raw_stats = runtime.thumbnail_bus.call_method(
                    service='com.dbox.thumbnaild',
                    interface='com.dbox.Thumbnaild',
                    method='GetMetrics',
                    params={}
                )
                if raw_stats:
                    thumb_service_status = 'running'
                    # 字段兼容：thumbnaild 返回 {total,completed,failed,active,queue}，
                    # 前端 Admin.vue 读取 tasks_completed/tasks_failed/active_tasks/queue_size
                    thumb_service_stats = {
                        'tasks_total': raw_stats.get('total', 0),
                        'tasks_completed': raw_stats.get('completed', 0),
                        'tasks_failed': raw_stats.get('failed', 0),
                        'active_tasks': raw_stats.get('active', 0),
                        'queue_size': raw_stats.get('queue', 0),
                    }
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
                'total_videos': thumb_stats['total_videos'],
                'total_thumbnails': thumb_stats['total_thumbnails'],
                'no_thumbnail_count': thumb_stats['no_thumbnail_count'],
                'thumb_service_status': thumb_service_status,
                'thumb_service_stats': thumb_service_stats,
                'is_auto_generating': is_auto_running,
                'auto_generate_progress': get_auto_generate_progress()
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
        allowed_fields = ['auto_generate', 'max_workers', 'task_interval', 'auto_generate_interval', 'preview', 'output_format']
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
                elif field == 'output_format':
                    # 生成格式：sprite（雪碧图，默认）/ gif / jpg / png
                    fmt = str(data[field]).lower()
                    if fmt in ('sprite', 'gif', 'jpg', 'png'):
                        config[field] = fmt
                elif field == 'preview' and isinstance(data[field], dict):
                    # 悬停预览采样参数（sprite 雪碧图）：逐字段合并 + 白名单校验
                    pv = config.setdefault('preview', {})
                    allowed_pv = ('enabled', 'head_skip', 'tail_skip', 'sample_points', 'sprite_cols', 'sprite_long_edge')
                    for k, v in data[field].items():
                        if k not in allowed_pv:
                            continue
                        if k == 'enabled':
                            pv[k] = bool(v)
                        elif k in ('head_skip', 'tail_skip'):
                            pv[k] = max(0.0, min(0.5, float(v)))
                        elif k == 'sample_points':
                            pv[k] = max(4, min(48, int(v)))
                        elif k == 'sprite_cols':
                            pv[k] = max(1, min(12, int(v)))
                        elif k == 'sprite_long_edge':
                            pv[k] = max(80, min(480, int(v)))

        if _save_thumb_config(config):
            log.maintenance('INFO', f'缩略图配置已更新: {config}')

            # 如果开启了自动生成，启动后台线程（必须传入 app 以保持应用上下文）
            if config['auto_generate'] and (_thumb_auto_thread is None or not _thumb_auto_thread.is_alive()):
                _start_auto_generate(config, app=current_app._get_current_object())
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
    """获取自动生成线程状态与实时进度"""
    is_running = _thumb_auto_thread is not None and _thumb_auto_thread.is_alive()
    progress = get_auto_generate_progress()
    progress['is_running'] = is_running
    if not is_running and not progress['running']:
        progress['running'] = False
    return jsonify({
        'success': True,
        'is_running': is_running,
        'progress': progress,
        'no_thumbnail_count': compute_thumb_stats()['no_thumbnail_count']
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
