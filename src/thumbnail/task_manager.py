# -*- coding: utf-8 -*-
"""
TaskManager - 封面生成任务管理器

负责管理封面生成任务队列、并发控制和状态跟踪。
被 thumbnail/main.py（旧）和 thumbnaild.py（新版）共用。
"""
import os
import sys
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
# 缩略图存储从项目目录分离到系统数据区（与 web 主服务一致）。
# thumbnaild 运行时 sys.path 只含 src/，需手动把 src/web 加入以便导入 backend.paths，
# 否则会回退到项目目录 data/，导致生成的缩略图写入错误位置。
try:
    _WEB_DIR = os.path.join(PROJECT_ROOT, 'src', 'web')
    if _WEB_DIR not in sys.path:
        sys.path.insert(0, _WEB_DIR)
    import backend.paths as _paths
    _DATA_DIR = _paths.get_user_data_dir()
except Exception:
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
# 单任务整体超时（秒）：cv2 在某些损坏/特殊编码视频上 cap.read() 可能永久阻塞，
# 若不加超时，卡死的任务会永久占用 worker 线程，导致整个队列停滞、控制面看到
# active 数永远不变却无文件产出。超时即放弃该任务并标记为失败，释放 worker。
TASK_TIMEOUT = 25


def _do_generate(task):
    """实际生成逻辑，在独立线程中运行以便超时控制。"""
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
            # 顺序读取采样，不使用 cap.set(POS_FRAMES) 跳转：
            # 部分 mp4 的 moov atom 位于文件末尾，随机 seek 会触发
            # "moov atom not found" 导致读取失败，顺序读取则不受影响。
            # 为避免长视频顺序读完整个文件（极慢），只在「前 MAX_READ_FRAMES 帧」
            # 内均匀采样 12 帧——长视频的封面取开头片段即可，无需读完全片。
            target_total = 12
            max_read_frames = 120  # 封顶读取范围，控制单任务耗时（M 盘慢视频顺序读取需快速收敛）
            effective_total = min(total_frames, max_read_frames) if total_frames and total_frames > 0 else max_read_frames
            step = max(1, int(effective_total / target_total))
            collected = 0
            idx = 0
            while collected < target_total and idx < max_read_frames:
                ret, f = cap.read()
                if not ret:
                    break
                if idx % step == 0 or collected < 2:
                    f = cv2.resize(f, (240, 135))
                    f = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
                    frames.append(Image.fromarray(f))
                    collected += 1
                idx += 1

            if frames:
                output_path = os.path.join(THUMBNAIL_DIR, f'{task.video_hash}.gif')
                # 动图帧间隔跟随源视频帧率，使预览播放速度与真实视频一致。
                # 采样帧之间相隔 step 帧，故每帧真实时长为 step * (1000/fps) ms；
                # fps 异常时回退到 125ms（8fps）。
                if fps and fps > 0:
                    frame_duration = max(10, round(step * 1000.0 / fps))
                else:
                    frame_duration = 125
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


def generate_thumbnail(task):
    """执行封面生成（同步），被 task_worker 调用。带整体超时保护。"""
    result = {}

    def _runner():
        try:
            result['val'] = _do_generate(task)
        except Exception as e:
            result['val'] = (False, str(e))

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=TASK_TIMEOUT)
    if t.is_alive():
        # 超时：cv2 卡死，放弃该任务（cap 在子线程中稍后会被 GC 释放）
        import logging
        logging.getLogger('thumbnail').warning(
            f'[thumbnail] 生成超时（>{TASK_TIMEOUT}s）跳过: {task.video_hash} path={task.video_path}'
        )
        return False, f"生成超时（>{TASK_TIMEOUT}s），跳过该视频"
    return result.get('val', (False, "未知错误"))


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
