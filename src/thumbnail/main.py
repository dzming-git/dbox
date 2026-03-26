"""
DPlayer - 缩略图服务
独立的微服务，负责视频缩略图的生成

目录结构：
  src/thumbnail/main.py  - 本文件（缩略图服务入口）
  src/thumbnail/         - 缩略图服务代码
  data/thumbnails/       - 缩略图存储
  configs/services/      - 服务管理
"""
import os
import sys

# 目录定义
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_THIS_DIR)
PROJECT_ROOT = os.path.dirname(_SRC_DIR)
_DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
_CONFIGS_DIR = os.path.join(PROJECT_ROOT, 'configs')

# 添加模块路径
for _p in [_THIS_DIR, _SRC_DIR, os.path.join(_CONFIGS_DIR, 'services')]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from launcher_guard import check_service_launch
check_service_launch('DPlayer Thumbnail Service', 'src/thumbnail/main.py')

import json
import time
import threading
from datetime import datetime
from collections import deque
import traceback

from flask import Flask, jsonify, request, send_file

# 添加更多模块路径（liblog 等）
for p in [_THIS_DIR, _SRC_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ============ 配置 ============
THUMBNAIL_PORT = int(os.getenv('THUMBNAIL_SERVICE_PORT', '5001'))
THUMBNAIL_HOST = os.getenv('THUMBNAIL_SERVICE_HOST', '0.0.0.0')
MAX_CONCURRENT = int(os.getenv('MAX_CONCURRENT_TASKS', '2'))  # 降低并发数，避免CPU被占满
QUEUE_SIZE = int(os.getenv('QUEUE_SIZE', '100'))

THUMBNAIL_DIR = os.path.join(_DATA_DIR, 'thumbnails')
os.makedirs(THUMBNAIL_DIR, exist_ok=True)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

# ============ 日志（使用 liblog 统一日志） ============
from liblog import get_module_logger
log = get_module_logger()
log.maintenance('INFO', '缩略图服务日志系统初始化完成')

# ============ 任务管理 ============
class Task:
    def __init__(self, task_id, video_path, video_hash, config):
        self.task_id = task_id
        self.video_path = video_path
        self.video_hash = video_hash
        self.status = 'pending'
        self.error = None
        self.thumbnail_path = None
        self.format = config.get('output_format', 'jpg')
        self.created_at = datetime.now()

class TaskManager:
    def __init__(self, max_concurrent=MAX_CONCURRENT, queue_size=QUEUE_SIZE):
        self.max_concurrent = max_concurrent
        self.queue_size = queue_size
        self.tasks = {}
        self.video_hash_to_task = {}
        self.queue = deque()
        self.active_count = 0
        self.lock = threading.Lock()
        self.stats = {'total': 0, 'completed': 0, 'failed': 0}

    def create_task(self, video_path, video_hash, config):
        with self.lock:
            if video_hash in self.video_hash_to_task:
                return self.tasks.get(self.video_hash_to_task[video_hash])
            
            if len(self.queue) >= self.queue_size:
                return None
            
            task_id = f"thumb_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
            task = Task(task_id, video_path, video_hash, config)
            self.tasks[task_id] = task
            self.video_hash_to_task[video_hash] = task_id
            self.queue.append(task_id)
            self.stats['total'] += 1
            return task

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def start_next_task(self):
        with self.lock:
            if self.active_count >= self.max_concurrent or not self.queue:
                return None
            task_id = self.queue.popleft()
            task = self.tasks[task_id]
            task.status = 'processing'
            self.active_count += 1
            return task

    def complete_task(self, task_id, success, error=None, thumbnail_path=None):
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return
            task.status = 'completed' if success else 'failed'
            task.error = error
            task.thumbnail_path = thumbnail_path
            self.active_count -= 1
            self.stats['completed' if success else 'failed'] += 1

    def get_stats(self):
        return {
            'total': self.stats['total'],
            'completed': self.stats['completed'],
            'failed': self.stats['failed'],
            'active': self.active_count,
            'queue': len(self.queue)
        }

task_manager = TaskManager()

# ============ 缩略图生成 ============
def generate_thumbnail(task):
    try:
        import cv2
        from PIL import Image
        import io
        
        if not os.path.exists(task.video_path):
            return False, "视频文件不存在"

        output_format = task.format if hasattr(task, 'format') else 'jpg'

        cap = cv2.VideoCapture(task.video_path)
        if not cap.isOpened():
            return False, "无法打开视频"

        try:
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            if output_format == 'gif':
                # 生成GIF动图：跳过头尾，中间均匀采样，每点取连续几帧
                frames = []

                # 跳过头部10%和尾部10%，保留中间80%
                head_skip = int(total_frames * 0.10)
                tail_skip = int(total_frames * 0.10)
                valid_start = head_skip
                valid_end = total_frames - tail_skip
                valid_frames = valid_end - valid_start

                if valid_frames <= 0:
                    valid_start = 0
                    valid_end = total_frames
                    valid_frames = total_frames

                # 优化：只采样2个时间点，每个点取少量帧（降低CPU消耗）
                num_sample_points = 2
                frames_per_point = min(8, int(fps * 0.3))  # 每个点最多8帧，约0.3秒
                sample_interval = valid_frames // (num_sample_points + 1)

                for sp in range(1, num_sample_points + 1):
                    # 计算采样位置（中间部分均匀分布）
                    sample_pos = valid_start + (sp * sample_interval)

                    # 每个采样点截取少量帧
                    for fp in range(frames_per_point):
                        frame_pos = sample_pos + fp
                        if frame_pos >= total_frames:
                            break
                        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
                        ret, f = cap.read()
                        if not ret:
                            break
                        f = cv2.resize(f, (240, 135))  # 降低分辨率减轻CPU负担
                        f = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
                        frames.append(Image.fromarray(f))

                if frames:
                    output_path = os.path.join(THUMBNAIL_DIR, f'{task.video_hash}.gif')
                    # 降低帧率到8fps，减少GIF文件大小和CPU消耗
                    frame_duration = 125  # 固定125ms/帧（8fps），保证流畅度
                    frames[0].save(
                        output_path,
                        save_all=True,
                        append_images=frames[1:],
                        duration=frame_duration,
                        loop=0
                    )
                else:
                    return False, "无法读取视频帧"
            else:
                # 生成静态图片 (jpg/png)
                frame_num = min(int(5 * fps) if fps > 0 else 10, total_frames - 1)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = cap.read()
                if not ret:
                    return False, "读取帧失败"

                frame = cv2.resize(frame, (320, 180))
                ext = 'jpg' if output_format != 'png' else 'png'
                output_path = os.path.join(THUMBNAIL_DIR, f'{task.video_hash}.{ext}')
                cv2.imwrite(output_path, frame)

            return True, output_path
        finally:
            cap.release()
    except Exception as e:
        return False, str(e)

def task_worker():
    while True:
        task = task_manager.start_next_task()
        if task is None:
            time.sleep(0.1)
            continue
        
        try:
            success, result = generate_thumbnail(task)
            task_manager.complete_task(task.task_id, success, 
                                       error=result if not success else None,
                                       thumbnail_path=result if success else None)
        except Exception as e:
            task_manager.complete_task(task.task_id, False, error=str(e))

# ============ API 路由 ============
@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'stats': task_manager.get_stats()})

@app.route('/api/thumbnail/generate', methods=['POST'])
def generate_thumbnail_api():
    try:
        data = request.get_json()
        video_path = data.get('video_path')
        video_hash = data.get('video_hash')
        
        if not video_path or not video_hash:
            return jsonify({'success': False, 'message': '缺少参数'}), 400
        
        if not os.path.exists(video_path):
            return jsonify({'success': False, 'message': '视频文件不存在'}), 404
        
        output_format = data.get('output_format', 'jpg')
        task = task_manager.create_task(video_path, video_hash, {'output_format': output_format})
        if not task:
            return jsonify({'success': False, 'message': '队列已满'}), 503
        
        return jsonify({'success': True, 'task_id': task.task_id, 'status': task.status}), 201
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/thumbnail/status/<task_id>')
def get_status(task_id):
    task = task_manager.get_task(task_id)
    if not task:
        return jsonify({'success': False, 'message': '任务不存在'}), 404
    return jsonify({'success': True, 'status': task.status, 'error': task.error})

@app.route('/api/thumbnail/by_hash/<video_hash>/status', methods=['GET'])
def get_task_status_by_hash(video_hash):
    """根据视频hash查询任务状态API"""
    try:
        task_id = task_manager.video_hash_to_task.get(video_hash)
        task = task_manager.tasks.get(task_id) if task_id else None
        
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
            'task_id': task.task_id,
            'status': task.status,
            'error': task.error
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'服务器错误: {str(e)}'}), 500

@app.route('/metrics')
def metrics():
    """服务指标"""
    stats = task_manager.get_stats()
    return jsonify({
        'tasks_total': stats['total'],
        'tasks_completed': stats['completed'],
        'tasks_failed': stats['failed'],
        'active_tasks': stats['active'],
        'queue_size': stats['queue'],
        'uptime': 0
    })

@app.route('/api/thumbnail/file/<video_hash>')
def get_thumbnail_file(video_hash):
    for ext in ['gif', 'jpg', 'png']:
        path = os.path.join(THUMBNAIL_DIR, f'{video_hash}.{ext}')
        if os.path.exists(path):
            resp = send_file(path, mimetype=f'image/{ext}')
            resp.cache_control.max_age = 3600
            return resp
    return jsonify({'success': False, 'message': '缩略图不存在'}), 404

# ============ 主入口 ============
if __name__ == '__main__':
    log.runtime('INFO', f'缩略图服务启动于端口 {THUMBNAIL_PORT}')
    
    # 启动工作线程
    for _ in range(MAX_CONCURRENT):
        t = threading.Thread(target=task_worker, daemon=True)
        t.start()
    
    app.run(host=THUMBNAIL_HOST, port=THUMBNAIL_PORT, debug=False, threaded=True)
