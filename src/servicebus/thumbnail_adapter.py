# -*- coding: utf-8 -*-
"""
BusThumbnailAdapter - 封面生成器（thumbnaild）的总线适配器

将封面生成服务封装为总线风格的服务。

总线服务定义：

  Service:        com.dbox.thumbnaild
  Interface:      com.dbox.Thumbnaild
  Object Path:    /com/dbox/thumbnaild

  Methods:
    Generate(video_path, video_hash, output_format)
      → {success: bool, task_id: str, status: str}

    GetStatus(video_hash)
      → {success: bool, status: str, task_id: str, format: str}

    GetFile(video_hash)
      → {success: bool, path: str, format: str}

    Regenerate(video_path, video_hash, output_format)
      → {success: bool, task_id: str}

    GetMetrics()
      → {total: int, completed: int, failed: int, active: int, queue: int}

    HealthCheck()
      → {status: str, stats: dict}

  Signals:
    TaskCreated(video_hash, task_id, status)
    ThumbnailReady(video_hash, path, format)
    ThumbnailFailed(video_hash, error)

使用方式：

    adapter = BusThumbnailAdapter(task_manager, host='127.0.0.1', rpc_port=15555, pub_port=15556)
    adapter.start()
"""

import os
import time
from typing import Dict, Any, Optional

from .service_base import BaseDBusService


class BusThumbnailAdapter(BaseDBusService):
    """
    封面生成器总线适配器

    将 TaskManager 的任务队列能力暴露到服务总线上。
    """

    BUS_NAME = 'com.dbox.thumbnaild'
    INTERFACES = ['com.dbox.Thumbnaild']
    OBJECT_PATH = '/com/dbox/thumbnaild'

    def __init__(self, task_manager,
                 host: str = '127.0.0.1',
                 rpc_port: int = 15555,
                 pub_port: int = 15556):
        """
        Args:
            task_manager: TaskManager 实例
            host: 总线地址
            rpc_port: 总线 RPC 端口
            pub_port: 总线 PUB 端口
        """
        super().__init__(host, rpc_port, pub_port)
        self._task_manager = task_manager

    # ============ 总线方法 ============

    def on_method_generate(self, params: Dict[str, Any]) -> Dict:
        """
        请求生成封面。

        Args (params):
            video_path: str     - 视频文件路径
            video_hash: str     - 视频 hash
            output_format: str  - 输出格式（gif/jpg），默认 gif

        Returns:
            {success: bool, task_id: str, status: str}
        """
        video_path = params.get('video_path', '')
        video_hash = params.get('video_hash', '')
        output_format = params.get('output_format', 'gif')

        if not video_path or not video_hash:
            return {'success': False, 'error': '缺少 video_path 或 video_hash'}

        if not os.path.exists(video_path):
            return {'success': False, 'error': '视频文件不存在'}

        task = self._task_manager.create_task(
            video_path, video_hash, {'output_format': output_format}
        )
        if not task:
            return {'success': False, 'error': '队列已满'}

        # 发信号：任务已创建
        self.emit_signal(
            'com.dbox.Thumbnaild',
            'TaskCreated',
            {
                'video_hash': video_hash,
                'task_id': task.task_id,
                'status': task.status,
            }
        )
        return {'success': True, 'task_id': task.task_id, 'status': task.status}

    def on_method_get_status(self, params: Dict[str, Any]) -> Dict:
        """
        查询封面生成状态。

        Args (params):
            video_hash: str - 视频 hash

        Returns:
            {success: bool, status: str, task_id: str, format: str}
        """
        video_hash = params.get('video_hash', '')
        task_id = self._task_manager.video_hash_to_task.get(video_hash)
        task = self._task_manager.tasks.get(task_id) if task_id else None

        if task is None:
            return {'success': False, 'error': '任务不存在'}

        return {
            'success': True,
            'task_id': task.task_id,
            'status': task.status,
            'error': task.error,
        }

    def on_method_get_file(self, params: Dict[str, Any]) -> Dict:
        """
        获取封面文件路径。

        Args (params):
            video_hash: str - 视频 hash

        Returns:
            {success: bool, path: str, format: str}
        """
        video_hash = params.get('video_hash', '')
        # 检查是否有已完成的任务
        task_id = self._task_manager.video_hash_to_task.get(video_hash)
        task = self._task_manager.tasks.get(task_id) if task_id else None

        if task and task.status == 'completed' and task.thumbnail_path:
            for ext in ['gif', 'jpg', 'png']:
                if task.thumbnail_path.endswith(f'.{ext}'):
                    return {
                        'success': True,
                        'path': task.thumbnail_path,
                        'format': ext,
                    }

        # 检查文件是否已存在（无需任务）
        from thumbnail.task_manager import THUMBNAIL_DIR
        for ext in ['gif', 'jpg', 'png']:
            path = os.path.join(THUMBNAIL_DIR, f'{video_hash}.{ext}')
            if os.path.exists(path):
                return {
                    'success': True,
                    'path': path,
                    'format': ext,
                }

        return {'success': False, 'error': '封面文件不存在'}

    def on_method_regenerate(self, params: Dict[str, Any]) -> Dict:
        """
        重新生成封面。

        Args (params):
            video_path: str     - 视频文件路径
            video_hash: str     - 视频 hash
            output_format: str  - 输出格式

        Returns:
            {success: bool, task_id: str}
        """
        return self.on_method_generate(params)

    def on_method_get_metrics(self, params: Dict[str, Any]) -> Dict:
        """
        获取服务指标。

        Returns:
            {total, completed, failed, active, queue}
        """
        return self._task_manager.get_stats()

    def on_method_health_check(self, params: Dict[str, Any]) -> Dict:
        """
        健康检查。

        Returns:
            {status: str, stats: dict}
        """
        return {
            'status': 'healthy',
            'stats': self._task_manager.get_stats(),
        }

    def on_method_wait_complete(self, params: Dict[str, Any]) -> Dict:
        """
        同步等待封面生成完成（最长等待时间）。

        Args (params):
            video_hash: str       - 视频 hash
            timeout: int          - 超时秒数，默认 30

        Returns:
            {success: bool, status: str, path: str, format: str}
        """
        video_hash = params.get('video_hash', '')
        timeout = params.get('timeout', 30)
        deadline = time.time() + timeout

        while time.time() < deadline:
            task_id = self._task_manager.video_hash_to_task.get(video_hash)
            task = self._task_manager.tasks.get(task_id) if task_id else None

            if task is None:
                # 检查文件是否已存在
                result = self.on_method_get_file({'video_hash': video_hash})
                if result.get('success'):
                    return {**result, 'status': 'ready'}
                return {'success': False, 'status': 'not_found', 'error': '任务不存在'}

            if task.status == 'completed':
                result = self.on_method_get_file({'video_hash': video_hash})
                return {**result, 'status': 'completed'}

            if task.status == 'failed':
                return {
                    'success': False,
                    'status': 'failed',
                    'error': task.error or '生成失败',
                }

            time.sleep(0.5)

        return {'success': False, 'status': 'timeout', 'error': '等待超时'}
