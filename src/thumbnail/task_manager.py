# -*- coding: utf-8 -*-
"""
TaskManager - 封面生成任务管理器

负责管理封面生成任务队列、并发控制和状态跟踪。
被 thumbnail/main.py（旧）和 thumbnaild.py（新版）共用。
"""
import os
import time
import threading
from datetime import datetime
from collections import deque


# ============ 目录配置 ============
def _get_project_root():
    _THIS_DIR = os.path.dirname(os.path.abspath(__file__))
    _SRC_DIR = os.path.dirname(_THIS_DIR)
    return os.path.dirname(_SRC_DIR)


PROJECT_ROOT = _get_project_root()
_DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
THUMBNAIL_DIR = os.path.join(_DATA_DIR, 'thumbnails')
os.makedirs(THUMBNAIL_DIR, exist_ok=True)


# ============ 任务模型 ============
class Task:
    def __init__(self, task_id, video_path, video_hash, config):
        self.task_id = task_id
        self.video_path = video_path
        self.video_hash = video_hash
        self.status = 'pending'
        self.error = None
        self.thumbnail_path = None
        self.format = config.get('output_format', 'gif')
        self.created_at = datetime.now()


class TaskManager:
    def __init__(self, max_concurrent=2, queue_size=100):
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
                existing_id = self.video_hash_to_task[video_hash]
                existing = self.tasks.get(existing_id)
                # 如果已完成或失败，允许重新生成
                if existing and existing.status in ('completed', 'failed'):
                    pass
                else:
                    return existing  # 返回现有任务

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
            'queue': len(self.queue),
        }


# ============ 封面生成核心逻辑 ============
def generate_thumbnail(task):
    """执行封面生成（同步），被 task_worker 调用"""
    try:
        import cv2
        from PIL import Image

        if not os.path.exists(task.video_path):
            return False, "视频文件不存在"

        output_format = task.format
        cap = cv2.VideoCapture(task.video_path)
        if not cap.isOpened():
            return False, "无法打开视频"

        try:
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            if output_format == 'gif':
                frames = []
                head_skip = int(total_frames * 0.10)
                tail_skip = int(total_frames * 0.10)
                valid_start = head_skip
                valid_end = total_frames - tail_skip
                valid_frames = valid_end - valid_start

                if valid_frames <= 0:
                    valid_start = 0
                    valid_end = total_frames
                    valid_frames = total_frames

                num_sample_points = 2
                frames_per_point = min(8, int(fps * 0.3))
                sample_interval = valid_frames // (num_sample_points + 1)

                for sp in range(1, num_sample_points + 1):
                    sample_pos = valid_start + (sp * sample_interval)
                    for fp in range(frames_per_point):
                        frame_pos = sample_pos + fp
                        if frame_pos >= total_frames:
                            break
                        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)
                        ret, f = cap.read()
                        if not ret:
                            break
                        f = cv2.resize(f, (240, 135))
                        f = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
                        frames.append(Image.fromarray(f))

                if frames:
                    output_path = os.path.join(THUMBNAIL_DIR, f'{task.video_hash}.gif')
                    frames[0].save(
                        output_path,
                        save_all=True,
                        append_images=frames[1:],
                        duration=125,
                        loop=0
                    )
                else:
                    return False, "无法读取视频帧"
            else:
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


def task_worker(task_manager):
    """工作线程：不断从队列取任务并执行"""
    while True:
        task = task_manager.start_next_task()
        if task is None:
            time.sleep(0.1)
            continue
        try:
            success, result = generate_thumbnail(task)
            task_manager.complete_task(
                task.task_id, success,
                error=result if not success else None,
                thumbnail_path=result if success else None
            )
        except Exception as e:
            task_manager.complete_task(task.task_id, False, error=str(e))
