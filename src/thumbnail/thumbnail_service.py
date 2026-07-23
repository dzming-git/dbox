#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缩略图微服务 (Thumbnail Microservice)

这是一个独立的Flask应用，专门负责视频缩略图的生成和管理。
采用微服务架构，与主应用完全解耦。

端口配置：
- 默认端口：5001
- 环境变量：THUMBNAIL_SERVICE_PORT

作者：<工作目录> AI
创建时间：2025-03-13
"""

from flask import Flask, jsonify, request, send_file, abort
import os
import sys

# 注入共享模块路径（兼容直接运行和 nssm 服务两种方式）
# 使用 os.getcwd() 来确保在各种启动方式下都能正确获取路径
_script_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in dir() else os.getcwd()
# 如果当前工作目录是 msa-thumb，则向上两级；否则按正常逻辑计算
_cwd = os.getcwd()
if _cwd.endswith('msa-thumb'):
    _PROJECT_ROOT = os.path.dirname(_cwd)  # Dplayer2.0
elif _cwd.endswith('dplayer-src'):
    _PROJECT_ROOT = os.path.dirname(_cwd)  # Dplayer2.0
else:
    _PROJECT_ROOT = os.path.normpath(os.path.join(_script_dir, '..'))
_THIS_DIR = os.path.join(_PROJECT_ROOT, 'msa-thumb')
for _p in [
    _THIS_DIR,
    os.path.join(_PROJECT_ROOT, 'msa-web'),   # utils/, service_manager
    os.path.join(_PROJECT_ROOT, 'libs'),       # libweb
]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import json
import time
import threading
from datetime import datetime
from collections import deque
import traceback
import cv2
from PIL import Image
import io
import hashlib
import numpy as np
from utils.network_optimize import optimize_flask_app
from utils.system_optimizer import optimize_system

# ========== 配置 ==========

# 从环境变量获取配置
THUMBNAIL_SERVICE_PORT = int(os.getenv('THUMBNAIL_SERVICE_PORT', '5001'))
THUMBNAIL_SERVICE_HOST = os.getenv('THUMBNAIL_SERVICE_HOST', '0.0.0.0')
MAX_CONCURRENT_TASKS = int(os.getenv('MAX_CONCURRENT_TASKS', '5'))
QUEUE_SIZE = int(os.getenv('QUEUE_SIZE', '100'))
TASK_TIMEOUT = int(os.getenv('TASK_TIMEOUT', '30'))
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

# 缩略图存储目录 - 使用项目根目录下的 static/thumbnails
THUMBNAIL_DIR = os.path.join(_PROJECT_ROOT, 'static', 'thumbnails')
if not os.path.exists(THUMBNAIL_DIR):
    os.makedirs(THUMBNAIL_DIR)

# 创建Flask应用
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB

# 优化网络连接配置，解决局域网访问偶现失败问题
# try:
#     optimize_flask_app(app)
#     logger.info('网络连接优化已启用')
# except Exception as e:
#     logger.warning(f'网络优化失败: {e}')



# ========== 日志配置 ==========

# 配置日志（使用 liblog 统一日志）
from liblog import get_service_logger
log = get_service_logger('dplayer-thumbnail')
logger = log
error_log = log
debug_log = log


# ========== 任务管理 ==========

class Task:
    """缩略图生成任务"""
    
    def __init__(self, task_id, video_path, video_hash, config):
        self.task_id = task_id
        self.video_path = video_path
        self.video_hash = video_hash
        self.status = 'pending'  # pending, processing, completed, failed
        self.progress = 0
        self.result = None
        self.error = None
        self.created_at = datetime.now()
        self.started_at = None
        self.completed_at = None
        self.thumbnail_path = None
        self.format = config.get('output_format', 'gif')
        self.file_size = None
        self.processing_time = None
    
    def to_dict(self):
        """转换为字典"""
        return {
            'task_id': self.task_id,
            'video_path': self.video_path,
            'video_hash': self.video_hash,
            'status': self.status,
            'progress': self.progress,
            'error': self.error,
            'created_at': self.created_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'thumbnail_path': self.thumbnail_path,
            'format': self.format,
            'file_size': self.file_size,
            'processing_time': self.processing_time
        }


class TaskManager:
    """任务管理器"""
    
    def __init__(self, max_concurrent=MAX_CONCURRENT_TASKS, queue_size=QUEUE_SIZE):
        self.max_concurrent = max_concurrent
        self.queue_size = queue_size
        self.tasks = {}  # task_id -> Task
        self.video_hash_to_task_id = {}  # video_hash -> task_id
        self.queue = deque()
        self.active_count = 0
        self.lock = threading.Lock()
        self.stats = {
            'total': 0,
            'completed': 0,
            'failed': 0,
            'avg_processing_time': 0.0
        }
        self.start_time = datetime.now()
    
    def create_task(self, video_path, video_hash, config):
        """创建新任务"""
        with self.lock:
            # 检查是否已有相同视频的任务
            if video_hash in self.video_hash_to_task_id:
                existing_task_id = self.video_hash_to_task_id[video_hash]
                existing_task = self.tasks[existing_task_id]
                if existing_task.status in ['pending', 'processing']:
                    logger.info(f"任务已存在: {existing_task_id}")
                    return existing_task
            
            # 检查队列是否已满
            if len(self.queue) >= self.queue_size:
                logger.warning(f"任务队列已满: {len(self.queue)}/{self.queue_size}")
                return None
            
            # 生成任务ID
            task_id = f"thumb_task_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
            
            # 创建任务
            task = Task(task_id, video_path, video_hash, config)
            self.tasks[task_id] = task
            self.video_hash_to_task_id[video_hash] = task_id
            self.queue.append(task_id)
            self.stats['total'] += 1
            
            logger.info(f"创建任务: {task_id}, video_hash={video_hash}, 队列大小={len(self.queue)}")
            
            return task
    
    def get_task(self, task_id):
        """获取任务"""
        with self.lock:
            return self.tasks.get(task_id)
    
    def get_task_by_video_hash(self, video_hash):
        """根据视频hash获取任务"""
        with self.lock:
            task_id = self.video_hash_to_task_id.get(video_hash)
            return self.tasks.get(task_id) if task_id else None
    
    def start_next_task(self):
        """开始下一个任务"""
        with self.lock:
            if self.active_count >= self.max_concurrent:
                return None
            
            if not self.queue:
                return None
            
            task_id = self.queue.popleft()
            task = self.tasks[task_id]
            task.status = 'processing'
            task.started_at = datetime.now()
            self.active_count += 1
            
            logger.info(f"开始任务: {task_id}, 活跃任务数={self.active_count}")
            
            return task
    
    def complete_task(self, task_id, success, error=None, thumbnail_path=None, file_size=None):
        """完成任务"""
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                logger.warning(f"任务不存在: {task_id}")
                return
            
            task.status = 'completed' if success else 'failed'
            task.completed_at = datetime.now()
            task.error = error
            task.thumbnail_path = thumbnail_path
            task.file_size = file_size

            if task.started_at:
                task.processing_time = (task.completed_at - task.started_at).total_seconds()
                processing_time_str = f"{task.processing_time:.3f}s"
            else:
                task.processing_time = None
                processing_time_str = "N/A"

            self.active_count -= 1

            if success:
                self.stats['completed'] += 1
                logger.info(f"任务完成: {task_id}, 耗时={processing_time_str}, 文件大小={file_size}")
            else:
                self.stats['failed'] += 1
                logger.error(f"任务失败: {task_id}, 错误={error}")
    
    def get_stats(self):
        """获取统计信息"""
        uptime = (datetime.now() - self.start_time).total_seconds()
        success_rate = 0.0
        if self.stats['total'] > 0:
            success_rate = (self.stats['completed'] / self.stats['total']) * 100
        
        return {
            'uptime': uptime,
            'total_tasks': self.stats['total'],
            'completed_tasks': self.stats['completed'],
            'failed_tasks': self.stats['failed'],
            'success_rate': round(success_rate, 2),
            'active_tasks': self.active_count,
            'queue_size': len(self.queue),
            'total_capacity': self.queue_size
        }


# 全局任务管理器
task_manager = TaskManager()


# ========== 缩略图生成函数 ==========

def _resize_letterbox(frame, target_w, target_h):
    """保持原始宽高比缩放并居中填充黑边到目标尺寸，避免拉伸变形。

    竖屏视频会完整显示在中央（左右黑边），横屏视频保持 16:9，
    不会再被强行拉伸成横向画面。
    """
    h, w = frame.shape[:2]
    if w <= 0 or h <= 0:
        return cv2.resize(frame, (target_w, target_h))
    scale = min(target_w / w, target_h / h)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((target_h, target_w, 3), dtype=resized.dtype)
    x = (target_w - new_w) // 2
    y = (target_h - new_h) // 2
    canvas[y:y + new_h, x:x + new_w] = resized
    return canvas


def generate_thumbnail(task):
    """生成缩略图（在后台线程中执行）"""
    video_path = task.video_path
    video_hash = task.video_hash
    output_format = task.format
    
    logger.info(f"[缩略图生成] 开始: video_path={video_path}, video_hash={video_hash}, format={output_format}")
    
    try:
        # 验证视频文件
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        
        # 使用OpenCV提取帧并生成缩略图
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"无法打开视频: {video_path}")
        
        try:
            # 获取视频信息
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            logger.debug(f"[缩略图生成] 视频信息: fps={fps}, frames={total_frames}, resolution={width}x{height}")
            
            # 计算截取的帧（5秒处）
            if fps > 0:
                frame_num = min(int(5 * fps), total_frames - 1)
            else:
                frame_num = min(10, total_frames - 1)
            
            # 跳转到指定帧
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            
            # 读取帧
            ret, frame = cap.read()
            if not ret:
                raise RuntimeError(f"读取视频帧失败: {video_path}")
            
            # 调整大小（保持原比例 + 黑边，避免竖屏被拉伸成横屏）
            frame = _resize_letterbox(frame, 320, 180)
            
            # 确定输出路径
            if output_format == 'gif':
                output_path = os.path.join(THUMBNAIL_DIR, f'{video_hash}.gif')

                # 优化：只采样2个位置，每个位置少量帧，降低CPU消耗
                frames = []
                # 固定帧率8fps，减少GIF大小和CPU消耗
                frame_duration = 125  # 125ms/帧 = 8fps

                # 计算两个位置：30%、70%
                positions = [0.3, 0.7]
                # 每个位置最多取8帧（约0.3秒）
                frames_per_segment = min(8, int(fps * 0.3))

                for pos_ratio in positions:
                    start_frame = int(total_frames * pos_ratio)
                    # 确保不超出视频范围
                    if start_frame + frames_per_segment > total_frames:
                        start_frame = max(0, total_frames - frames_per_segment)

                    # 跳转到起始位置
                    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

                    for i in range(frames_per_segment):
                        ret, f = cap.read()
                        if not ret:
                            break
                        # 调整大小（保持原比例 + 黑边，降低分辨率减轻CPU负担）
                        f = _resize_letterbox(f, 240, 135)
                        f = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
                        frames.append(Image.fromarray(f))

                if frames:
                    # 保存为 GIF
                    frames[0].save(
                        output_path,
                        save_all=True,
                        append_images=frames[1:],
                        duration=frame_duration,
                        loop=0
                    )
                else:
                    # 降级为 PNG
                    cv2.imwrite(output_path.replace('.gif', '.png'), frame)
                    output_path = output_path.replace('.gif', '.png')
                    output_format = 'png'
            else:
                output_path = os.path.join(THUMBNAIL_DIR, f'{video_hash}.jpg')
                cv2.imwrite(output_path, frame)
            
            # 获取文件大小
            file_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
            
            logger.info(f"[缩略图生成] 成功: output={output_path}, size={file_size}B, format={output_format}")
            
            return True, output_path, output_format, file_size
            
        finally:
            cap.release()
            
    except Exception as e:
        logger.error(f"[缩略图生成] 失败: {str(e)}\n{traceback.format_exc()}")
        return False, None, None, None


def task_worker():
    """任务工作线程"""
    logger.info("任务工作线程启动")
    
    while True:
        # 获取下一个任务
        task = task_manager.start_next_task()
        
        if task is None:
            time.sleep(0.1)  # 短暂休眠
            continue
        
        try:
            # 执行缩略图生成
            success, thumbnail_path, output_format, file_size = generate_thumbnail(task)
            
            # 完成任务
            task_manager.complete_task(
                task.task_id,
                success=success,
                error=task.error if not success else None,
                thumbnail_path=thumbnail_path,
                file_size=file_size
            )
            
        except Exception as e:
            logger.error(f"任务执行异常: {task.task_id}, 错误={str(e)}\n{traceback.format_exc()}")
            task_manager.complete_task(
                task.task_id,
                success=False,
                error=str(e)
            )




# ========== Flask路由 ==========

@app.route('/health')
def health_check():
    """健康检查"""
    stats = task_manager.get_stats()
    return jsonify({
        'status': 'healthy',
        'version': '1.0.0',
        'uptime': stats['uptime'],
        'active_tasks': stats['active_tasks'],
        'queue_size': stats['queue_size'],
        'total_processed': stats['completed_tasks'],
        'success_rate': stats['success_rate']
    })


@app.route('/metrics')
def metrics():
    """服务指标"""
    stats = task_manager.get_stats()
    return jsonify({
        'tasks_total': stats['total_tasks'],
        'tasks_completed': stats['completed_tasks'],
        'tasks_failed': stats['failed_tasks'],
        'success_rate': stats['success_rate'],
        'active_tasks': stats['active_tasks'],
        'queue_size': stats['queue_size'],
        'total_capacity': stats['total_capacity'],
        'uptime': stats['uptime']
    })


@app.route('/api/thumbnail/generate', methods=['POST'])
def generate_thumbnail_endpoint():
    """生成缩略图API"""
    try:
        data = request.get_json()
        logger.info(f"收到缩略图生成请求: {data}")
        
        # 验证请求
        if not data:
            return jsonify({'success': False, 'message': '无效的请求数据'}), 400
        
        video_path = data.get('video_path')
        video_hash = data.get('video_hash')
        
        if not video_path or not video_hash:
            logger.warning(f"缺少必要参数: video_path={video_path}, video_hash={video_hash}")
            return jsonify({'success': False, 'message': '缺少必要参数'}), 400
        
        # 检查视频文件是否存在
        if not os.path.exists(video_path):
            logger.warning(f"视频文件不存在: {video_path}")
            return jsonify({'success': False, 'message': '视频文件不存在'}), 404
        
        # 配置参数
        config = {
            'output_format': data.get('output_format', 'gif'),
            'time_offset': data.get('time_offset', 5),
            'size': data.get('size', [320, 180])
        }
        
        # 创建任务
        logger.info(f"开始创建缩略图任务: video_hash={video_hash}, video_path={video_path}")
        task = task_manager.create_task(video_path, video_hash, config)
        
        if task is None:
            logger.warning("任务队列已满")
            return jsonify({
                'success': False,
                'message': '任务队列已满，请稍后重试'
            }), 503
        
        logger.info(f"缩略图任务创建成功: task_id={task.task_id}, status={task.status}")
        
        # 返回任务信息
        return jsonify({
            'success': True,
            'task_id': task.task_id,
            'status': task.status,
            'estimated_time': 3  # 估计时间（秒）
        }), 201
        
    except Exception as e:
        logger.error(f"生成缩略图API异常: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'message': f'服务器错误: {str(e)}'}), 500


@app.route('/api/thumbnail/status/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """查询任务状态API"""
    try:
        task = task_manager.get_task(task_id)
        
        if task is None:
            return jsonify({'success': False, 'message': '任务不存在'}), 404
        
        return jsonify({
            'success': True,
            **task.to_dict()
        })
        
    except Exception as e:
        logger.error(f"查询任务状态API异常: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'message': f'服务器错误: {str(e)}'}), 500


@app.route('/api/thumbnail/by_hash/<video_hash>/status', methods=['GET'])
def get_task_status_by_hash(video_hash):
    """根据视频hash查询任务状态API"""
    try:
        task = task_manager.get_task_by_video_hash(video_hash)
        
        if task is None:
            # 检查是否有已生成的缩略图文件
            gif_path = os.path.join(THUMBNAIL_DIR, f'{video_hash}.gif')
            jpg_path = os.path.join(THUMBNAIL_DIR, f'{video_hash}.jpg')
            png_path = os.path.join(THUMBNAIL_DIR, f'{video_hash}.png')
            
            if os.path.exists(gif_path):
                return jsonify({
                    'success': True,
                    'status': 'ready',
                    'format': 'gif',
                    'file_size': os.path.getsize(gif_path)
                })
            elif os.path.exists(jpg_path):
                return jsonify({
                    'success': True,
                    'status': 'ready',
                    'format': 'jpg',
                    'file_size': os.path.getsize(jpg_path)
                })
            elif os.path.exists(png_path):
                return jsonify({
                    'success': True,
                    'status': 'ready',
                    'format': 'png',
                    'file_size': os.path.getsize(png_path)
                })
            else:
                return jsonify({'success': False, 'message': '任务不存在，且无缩略图文件'}), 404
        
        return jsonify({
            'success': True,
            **task.to_dict()
        })
        
    except Exception as e:
        logger.error(f"查询任务状态API异常: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'message': f'服务器错误: {str(e)}'}), 500


@app.route('/api/thumbnail/file/<video_hash>', methods=['GET'])
def get_thumbnail_file(video_hash):
    """获取缩略图文件API"""
    try:
        # 查找缩略图文件
        gif_path = os.path.join(THUMBNAIL_DIR, f'{video_hash}.gif')
        jpg_path = os.path.join(THUMBNAIL_DIR, f'{video_hash}.jpg')
        png_path = os.path.join(THUMBNAIL_DIR, f'{video_hash}.png')
        
        if os.path.exists(gif_path):
            response = send_file(gif_path, mimetype='image/gif')
        elif os.path.exists(jpg_path):
            response = send_file(jpg_path, mimetype='image/jpeg')
        elif os.path.exists(png_path):
            response = send_file(png_path, mimetype='image/png')
        else:
            return jsonify({'success': False, 'message': '缩略图不存在'}), 404
        
        # 设置缓存头
        response.cache_control.max_age = 3600  # 缓存1小时
        
        return response
        
    except Exception as e:
        logger.error(f"获取缩略图文件API异常: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'message': f'服务器错误: {str(e)}'}), 500


@app.route('/api/thumbnail/regenerate', methods=['POST'])
def regenerate_thumbnail():
    """重新生成缩略图API"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'message': '无效的请求数据'}), 400
        
        video_hash = data.get('video_hash')
        video_path = data.get('video_path')
        
        if not video_hash or not video_path:
            return jsonify({'success': False, 'message': '缺少必要参数'}), 400
        
        # 删除旧缩略图
        for ext in ['gif', 'jpg', 'png']:
            old_path = os.path.join(THUMBNAIL_DIR, f'{video_hash}.{ext}')
            if os.path.exists(old_path):
                os.remove(old_path)
                logger.info(f"删除旧缩略图: {old_path}")
        
        # 创建新任务
        config = {
            'output_format': data.get('output_format', 'gif'),
            'time_offset': data.get('time_offset', 5),
            'size': data.get('size', [320, 180])
        }
        
        task = task_manager.create_task(video_path, video_hash, config)
        
        if task is None:
            return jsonify({
                'success': False,
                'message': '任务队列已满，请稍后重试'
            }), 503
        
        return jsonify({
            'success': True,
            'task_id': task.task_id,
            'status': task.status
        }), 201
        
    except Exception as e:
        logger.error(f"重新生成缩略图API异常: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'message': f'服务器错误: {str(e)}'}), 500


# ========== 启动应用 ==========

if __name__ == '__main__':
    # ========== Windows 服务模式支持 ==========
    # 确保在作为 Windows 服务运行时工作目录正确
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)  # 回到项目根目录
    if os.getcwd() != parent_dir:
        os.chdir(parent_dir)
        logger.info(f"工作目录已设置为: {os.getcwd()}")
    
    logger.info("=" * 60)
    logger.info("缩略图微服务启动")
    logger.info("=" * 60)
    logger.info(f"服务地址: http://{THUMBNAIL_SERVICE_HOST}:{THUMBNAIL_SERVICE_PORT}")
    logger.info(f"工作线程数: {MAX_CONCURRENT_TASKS}")
    logger.info(f"任务队列大小: {QUEUE_SIZE}")
    logger.info(f"任务超时时间: {TASK_TIMEOUT}秒")
    logger.info(f"日志级别: {LOG_LEVEL}")
    logger.info(f"缩略图目录: {os.path.abspath(THUMBNAIL_DIR)}")

    # 执行系统网络优化（防火墙、TCP、DNS等）
    # logger.info("执行系统网络优化...")
    # try:
    #     optimize_system(
    #         ports=[THUMBNAIL_SERVICE_PORT],
    #         service_names=['缩略图服务']
    #     )
    # except Exception as e:
    #     logger.warning(f"系统优化失败: {e}")


    # 检测是否作为 Windows 服务运行
    is_service = 'windows_service' in os.environ.get('RUN_MODE', '').lower()
    if is_service:
        logger.info("以 Windows 服务模式运行")

    logger.info("=" * 60)

    # 启动工作线程（移到这里，避免导入时启动）
    worker_threads = []
    for i in range(MAX_CONCURRENT_TASKS):
        t = threading.Thread(target=task_worker, daemon=True)
        t.start()
        worker_threads.append(t)
        logger.info(f"启动工作线程 {i+1}/{MAX_CONCURRENT_TASKS}")
    
    try:
        # 启动Flask应用
        app.run(
            host=THUMBNAIL_SERVICE_HOST,
            port=THUMBNAIL_SERVICE_PORT,
            debug=not is_service,
            threaded=True,
            use_reloader=False
        )
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭服务...")
    except Exception as e:
        logger.error(f"服务启动失败: {str(e)}\n{traceback.format_exc()}")
        sys.exit(1)
