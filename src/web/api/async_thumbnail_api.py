#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异步缩略图API端点
提供异步缩略图生成的API接口
"""

from flask import Blueprint, jsonify, request, abort
from core.models import db, Video
from config.tasks import generate_thumbnail, batch_generate_thumbnails, regenerate_thumbnail, check_thumbnail_status
from celery.result import AsyncResult
from datetime import datetime
from liblog import get_module_logger
log = get_module_logger()

async_thumbnail_bp = Blueprint('async_thumbnail', __name__, url_prefix='/api/thumbnail')


@async_thumbnail_bp.route('/generate', methods=['POST'])
def async_generate_thumbnail():
    """异步生成缩略图"""
    try:
        data = request.get_json()

        video_path = data.get('video_path')
        if not video_path:
            return jsonify({'success': False, 'error': '视频路径不能为空'}), 400

        video_hash = data.get('video_hash')
        output_format = data.get('format', 'webp')
        width = data.get('width', 320)
        height = data.get('height')
        quality = data.get('quality', 85)
        timestamp = data.get('timestamp', 5.0)

        # 提交异步任务
        task = generate_thumbnail.delay(
            video_path=video_path,
            video_hash=video_hash,
            output_format=output_format,
            width=width,
            height=height,
            quality=quality,
            timestamp=timestamp
        )

        log.runtime('INFO', f"提交缩略图生成任务: {task.id}, 视频路径: {video_path}")

        return jsonify({
            'success': True,
            'task_id': task.id,
            'status': 'pending',
            'message': '缩略图生成任务已提交'
        }), 202

    except Exception as e:
        log.debug('ERROR', f"提交缩略图生成任务失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@async_thumbnail_bp.route('/batch', methods=['POST'])
def async_batch_generate_thumbnails():
    """批量异步生成缩略图"""
    try:
        data = request.get_json()

        video_paths = data.get('video_paths', [])
        if not video_paths:
            return jsonify({'success': False, 'error': '视频路径列表不能为空'}), 400

        output_format = data.get('format', 'webp')
        width = data.get('width', 320)
        height = data.get('height')
        quality = data.get('quality', 85)
        concurrent = data.get('concurrent', 3)

        # 提交批量任务
        task = batch_generate_thumbnails.delay(
            video_paths=video_paths,
            output_format=output_format,
            width=width,
            height=height,
            quality=quality,
            concurrent=concurrent
        )

        log.runtime('INFO', f"提交批量缩略图生成任务: {task.id}, 视频数量: {len(video_paths)}")

        return jsonify({
            'success': True,
            'task_id': task.id,
            'status': 'pending',
            'total_videos': len(video_paths),
            'message': f'批量缩略图生成任务已提交，共{len(video_paths)}个视频'
        }), 202

    except Exception as e:
        log.debug('ERROR', f"提交批量缩略图生成任务失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@async_thumbnail_bp.route('/regenerate', methods=['POST'])
def async_regenerate_thumbnail():
    """异步重新生成缩略图"""
    try:
        data = request.get_json()

        video_path = data.get('video_path')
        if not video_path:
            return jsonify({'success': False, 'error': '视频路径不能为空'}), 400

        video_hash = data.get('video_hash')
        delete_existing = data.get('delete_existing', True)

        # 其他参数
        kwargs = {
            'output_format': data.get('format', 'webp'),
            'width': data.get('width', 320),
            'height': data.get('height'),
            'quality': data.get('quality', 85),
            'timestamp': data.get('timestamp', 5.0)
        }

        # 提交重新生成任务
        task = regenerate_thumbnail.delay(
            video_path=video_path,
            video_hash=video_hash,
            delete_existing=delete_existing,
            **kwargs
        )

        log.runtime('INFO', f"提交缩略图重新生成任务: {task.id}, 视频路径: {video_path}")

        return jsonify({
            'success': True,
            'task_id': task.id,
            'status': 'pending',
            'message': '缩略图重新生成任务已提交'
        }), 202

    except Exception as e:
        log.debug('ERROR', f"提交缩略图重新生成任务失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@async_thumbnail_bp.route('/status/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """获取任务状态"""
    try:
        task = AsyncResult(task_id)

        response = {
            'success': True,
            'task_id': task_id,
            'status': task.status,
        }

        if task.state == 'PENDING':
            response['message'] = '任务等待中...'
        elif task.state == 'STARTED':
            response['message'] = '任务进行中...'
        elif task.state == 'SUCCESS':
            response['result'] = task.result
            response['message'] = '任务完成'
        elif task.state == 'FAILURE':
            response['error'] = str(task.info)
            response['message'] = '任务失败'

        return jsonify(response)

    except Exception as e:
        log.debug('ERROR', f"获取任务状态失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@async_thumbnail_bp.route('/check', methods=['POST'])
def check_thumbnail():
    """检查缩略图状态"""
    try:
        data = request.get_json()

        video_hash = data.get('video_hash')
        if not video_hash:
            return jsonify({'success': False, 'error': '视频hash不能为空'}), 400

        output_format = data.get('format', 'webp')

        # 提交检查任务
        task = check_thumbnail_status.delay(video_hash=video_hash, output_format=output_format)

        return jsonify({
            'success': True,
            'task_id': task.id,
            'status': 'pending',
            'message': '检查任务已提交'
        }), 202

    except Exception as e:
        log.debug('ERROR', f"检查缩略图状态失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@async_thumbnail_bp.route('/video/<int:video_id>/generate', methods=['POST'])
def generate_video_thumbnail(video_id):
    """为指定视频生成缩略图"""
    try:
        video = Video.query.get_or_404(video_id)

        if not video.local_path:
            return jsonify({
                'success': False,
                'error': '视频没有本地路径'
            }), 400

        data = request.get_json() or {}
        output_format = data.get('format', 'webp')
        width = data.get('width', 320)
        height = data.get('height')
        quality = data.get('quality', 85)
        timestamp = data.get('timestamp', 5.0)

        # 提交异步任务
        task = generate_thumbnail.delay(
            video_path=video.local_path,
            video_hash=video.hash,
            output_format=output_format,
            width=width,
            height=height,
            quality=quality,
            timestamp=timestamp
        )

        log.runtime('INFO', f"为视频 {video_id} 提交缩略图生成任务: {task.id}")

        return jsonify({
            'success': True,
            'task_id': task.id,
            'video_id': video_id,
            'video_title': video.title,
            'status': 'pending',
            'message': f'视频《{video.title}》的缩略图生成任务已提交'
        }), 202

    except Exception as e:
        log.debug('ERROR', f"为视频生成缩略图失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@async_thumbnail_bp.route('/batch/videos', methods=['POST'])
def batch_generate_video_thumbnails():
    """为多个视频批量生成缩略图"""
    try:
        data = request.get_json()

        video_ids = data.get('video_ids', [])
        if not video_ids:
            return jsonify({'success': False, 'error': '视频ID列表不能为空'}), 400

        # 查询视频
        videos = Video.query.filter(Video.id.in_(video_ids)).all()

        if not videos:
            return jsonify({'success': False, 'error': '没有找到有效的视频'}), 400

        # 筛选有本地路径的视频
        video_paths = []
        for video in videos:
            if video.local_path:
                video_paths.append(video.local_path)
            else:
                log.debug('WARN', f"视频 {video.id} ({video.title}) 没有本地路径，跳过")

        if not video_paths:
            return jsonify({
                'success': False,
                'error': '没有可生成缩略图的视频（需要本地路径）'
            }), 400

        # 获取参数
        output_format = data.get('format', 'webp')
        width = data.get('width', 320)
        height = data.get('height')
        quality = data.get('quality', 85)
        concurrent = data.get('concurrent', 3)

        # 提交批量任务
        task = batch_generate_thumbnails.delay(
            video_paths=video_paths,
            output_format=output_format,
            width=width,
            height=height,
            quality=quality,
            concurrent=concurrent
        )

        log.runtime('INFO', 
            f"为{len(video_paths)}个视频提交批量缩略图生成任务: {task.id}, "
            f"原始请求数: {len(video_ids)}"
        )

        return jsonify({
            'success': True,
            'task_id': task.id,
            'total_requested': len(video_ids),
            'total_processing': len(video_paths),
            'skipped': len(video_ids) - len(video_paths),
            'status': 'pending',
            'message': f'为{len(video_paths)}个视频提交批量缩略图生成任务'
        }), 202

    except Exception as e:
        log.debug('ERROR', f"批量生成视频缩略图失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@async_thumbnail_bp.route('/resource/limit', methods=['GET'])
def get_resource_limit():
    """获取资源限制配置"""
    try:
        from celery_config import RESOURCE_LIMITS

        return jsonify({
            'success': True,
            'limits': RESOURCE_LIMITS
        })

    except Exception as e:
        log.debug('ERROR', f"获取资源限制配置失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@async_thumbnail_bp.route('/resource/limit', methods=['PUT'])
def update_resource_limit():
    """更新资源限制配置"""
    try:
        data = request.get_json()

        from celery_config import RESOURCE_LIMITS

        # 更新限制（注意：这只更新当前进程的配置，不会影响worker）
        if 'max_memory_mb' in data:
            RESOURCE_LIMITS['max_memory_mb'] = data['max_memory_mb']
        if 'max_cpu_percent' in data:
            RESOURCE_LIMITS['max_cpu_percent'] = data['max_cpu_percent']
        if 'check_interval' in data:
            RESOURCE_LIMITS['check_interval'] = data['check_interval']

        log.runtime('INFO', f"更新资源限制配置: {RESOURCE_LIMITS}")

        return jsonify({
            'success': True,
            'limits': RESOURCE_LIMITS,
            'message': '资源限制配置已更新（需要重启worker生效）'
        })

    except Exception as e:
        log.debug('ERROR', f"更新资源限制配置失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
