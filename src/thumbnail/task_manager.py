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


# ============ 输出尺寸：保持源视频宽高比 ============
# 缩略图的长边像素数。短边按源视频真实宽高比推导，因此竖屏视频产出竖版
# 缩略图（如 135x240），横屏视频产出横版（240x135）。
#
# 为什么不再用固定 240x135 画布 + 黑边：
# 固定 16:9 画布虽然不会几何变形，但竖屏 1080x1920 缩进去只剩中间 76x135
# 一条，两侧大片黑边——在前端 16:9 卡片里看起来仍是「横的」，主体又被缩得
# 极小。让文件本身携带正确宽高比，配合前端 object-fit 才是根治方案。
THUMB_LONG_EDGE = 240
STATIC_LONG_EDGE = 320

# ============ 动图预览播放节奏 ============
# GIF 预览是「跨越全片均匀取样的快照轮播」，不是原速回放。
# 帧数与帧间隔固定，使所有视频的预览节奏一致：
# 12 帧 x 400ms = 4.8 秒循环一轮，人眼可以看清每一帧内容。
# 早期版本用 step*1000/fps 让间隔跟随源帧率，结果在不同视频上从
# 十几毫秒到数百毫秒剧烈波动，表现为「有的快到看不清」。
GIF_FRAMES = 12
GIF_FRAME_DURATION_MS = 400


def _fit_size(src_w, src_h, long_edge):
    """按源宽高比推导输出尺寸，长边固定为 long_edge，短边等比取偶数。"""
    if src_w <= 0 or src_h <= 0:
        return long_edge, max(2, int(round(long_edge * 9 / 16)))
    if src_w >= src_h:
        out_w = long_edge
        out_h = max(2, int(round(long_edge * src_h / src_w)))
    else:
        out_h = long_edge
        out_w = max(2, int(round(long_edge * src_w / src_h)))
    # 取偶数，避免部分解码器/编码器对奇数边的兼容问题
    return out_w - (out_w % 2), out_h - (out_h % 2)


def _resize_keep_ratio(frame, out_w, out_h):
    """等比缩放到已按源宽高比算好的目标尺寸（无黑边、无拉伸）。"""
    import cv2
    return cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA)


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

        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        if output_format == 'gif':
            out_w, out_h = _fit_size(src_w, src_h, THUMB_LONG_EDGE)
            frames = []

            # ---- 采样策略：跨越全片均匀取样，而不是只读开头 ----
            # 旧实现把采样窗口锁死在「前 120 帧」（约 4 秒），导致预览永远是
            # 片头（常为黑屏/logo），既不能代表内容，也让人误以为「播放速度不对」。
            # 现在改为在 [10%, 90%] 区间内均匀取 GIF_FRAMES 个时间点，用 seek
            # 跳转读取；seek 失败（moov atom 在文件尾等）时回退到顺序读取。
            target_total = GIF_FRAMES
            frames_read_ok = False

            if total_frames and total_frames > 0:
                start_f = int(total_frames * 0.1)
                end_f = int(total_frames * 0.9)
                if end_f <= start_f:
                    start_f, end_f = 0, max(0, total_frames - 1)
                span = max(1, end_f - start_f)
                positions = [start_f + int(span * i / target_total)
                             for i in range(target_total)]
                for pos in positions:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
                    ret, f = cap.read()
                    if not ret:
                        frames = []
                        break
                    f = _resize_keep_ratio(f, out_w, out_h)
                    f = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
                    frames.append(Image.fromarray(f))
                frames_read_ok = len(frames) >= 2

            if not frames_read_ok:
                # 回退：顺序读取（兼容无法 seek 的文件）
                cap.release()
                cap = cv2.VideoCapture(task.video_path)
                frames = []
                max_read_frames = 600
                effective = min(total_frames, max_read_frames) if total_frames and total_frames > 0 else max_read_frames
                step = max(1, int(effective / target_total))
                idx = 0
                while len(frames) < target_total and idx < max_read_frames:
                    ret, f = cap.read()
                    if not ret:
                        break
                    if idx % step == 0:
                        f = _resize_keep_ratio(f, out_w, out_h)
                        f = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
                        frames.append(Image.fromarray(f))
                    idx += 1

            if frames:
                output_path = os.path.join(THUMBNAIL_DIR, f'{task.video_hash}.gif')
                # 播放速度：预览是「跨越全片的快照轮播」，不是原速回放，
                # 因此帧间隔应是一个固定的、适合观看的展示节奏，而不能用
                # step/fps 去还原源视频时间轴（那会得到 330ms+ 的迟滞感，
                # 或在高帧率视频上快到看不清）。固定 GIF_FRAME_DURATION_MS
                # 保证任何视频的预览节奏完全一致、可预期。
                frames[0].save(
                    output_path,
                    save_all=True,
                    append_images=frames[1:],
                    duration=GIF_FRAME_DURATION_MS,
                    loop=0
                )
            else:
                return False, "无法读取视频帧"
        else:
            frame_num = min(int(5 * fps) if fps > 0 else 10, max(0, total_frames - 1))
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            if not ret:
                return False, "读取帧失败"
            sw, sh = _fit_size(src_w, src_h, STATIC_LONG_EDGE)
            frame = _resize_keep_ratio(frame, sw, sh)
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
