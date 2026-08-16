# -*- coding: utf-8 -*-
"""
TaskManager - 封面生成任务管理器

负责管理封面生成任务队列、并发控制和状态跟踪。
被 thumbnail/main.py（旧）和 thumbnaild.py（新版）共用。
"""
import os
import sys
import time
import json
import math
import shutil
import ctypes
import subprocess
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
    _THUMB_CONFIG_FILE = getattr(_paths, 'THUMB_CONFIG_FILE', '')
except Exception:
    _DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
    _THUMB_CONFIG_FILE = ''
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
        self.format = config.get('output_format', 'sprite')
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


# ============ Sprite 雪碧图 + WebVTT 悬停预览 ============
# 彻底替代 GIF 动图预览：GIF 因 256 色调色板 + 逐帧硬切 + 固定间隔导致明显「闪烁」。
# 新方案用 ffmpeg 单次调用把全片均匀采样的帧拼成一张 JPG 雪碧图，并生成 WebVTT
# 坐标索引。前端默认显示静态 poster（首帧，无闪烁、零额外带宽），鼠标悬停时按
# VTT 坐标轮播雪碧图帧 / 按鼠标 X 位置 seek，平滑无闪、最省带宽。


def _load_preview_config():
    """读取悬停预览采样参数。优先读 thumb 配置文件里的 preview 区块，否则用默认值。"""
    default = {
        'enabled': True,
        'head_skip': 0.08,
        'tail_skip': 0.08,
        'sample_points': 12,
        'sprite_cols': 4,
        'sprite_long_edge': 180,
        # 片段式采样：在 segment_count 个关键时间点各密集抽 frames_per_segment 帧，
        # 每帧相隔 segment_frame_gap 秒，构成几秒的连续片段；前端片段内循环播放再跳转。
        'segment_count': 4,
        'frames_per_segment': 3,
        'segment_frame_gap': 0.4,
    }
    try:
        cfg_path = _THUMB_CONFIG_FILE
        if not cfg_path or not os.path.exists(cfg_path):
            cfg_path = os.path.join(_DATA_DIR, 'thumbnail_config.json')
        if os.path.exists(cfg_path):
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            pv = cfg.get('preview') or {}
            if isinstance(pv, dict):
                default.update({k: pv[k] for k in default if k in pv})
    except Exception:
        pass
    return default


def _ffmpeg_available():
    """检查 ffmpeg 是否在 PATH 中可用。"""
    return shutil.which('ffmpeg') is not None


def _probe_duration(video_path):
    """用 ffprobe 获取视频时长（秒）。失败返回 None。"""
    try:
        probe = shutil.which('ffprobe')
        if not probe:
            return None
        r = subprocess.run(
            [probe, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
            capture_output=True, text=True, errors='replace', timeout=15,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        )
        if r.returncode == 0 and r.stdout.strip():
            val = float(r.stdout.strip())
            return val if val > 0 else None
    except Exception:
        pass
    return None


def _ts(sec):
    """把秒数格式化为 WebVTT 时间戳 HH:MM:SS.mmm。"""
    if sec < 0:
        sec = 0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int(round((sec - int(sec)) * 1000))
    if ms >= 1000:
        ms = 0
        s += 1
    return f'{h:02d}:{m:02d}:{s:02d}.{ms:03d}'


def _build_vtt(pv, video_hash, fw, fh, cols, rows, start, window, times, seg_of):
    """构建 WebVTT：NOTE 携带几何与片段信息，每个 cue 携带单帧 xywh 坐标、时间区间与片段归属。

    times   —— 每帧的实际采样时间点（秒），用于精确时间戳（片段式采样不再均匀）。
    seg_of  —— 每帧所属片段编号（int），前端据此分组：片段内连续播放几秒再跳转。
    """
    frame_count = len(times)
    lines = ['WEBVTT', 'X-TIMESTAMP-MAP=MPEGTS:0,LOCAL:00:00:00.000', '']
    lines.append(
        f'NOTE sprite fw={fw} fh={fh} cols={cols} rows={rows} '
        f'n={frame_count} start={start:.3f} window={window:.3f}'
    )
    lines.append('')
    for i in range(frame_count):
        x = (i % cols) * fw
        y = (i // cols) * fh
        # 片段内相邻帧用中点切分；片段边界帧不跨片段，用片段内相邻帧间隔
        same_seg_prev = i > 0 and seg_of[i] == seg_of[i - 1]
        same_seg_next = i + 1 < frame_count and seg_of[i] == seg_of[i + 1]
        if same_seg_next and i + 1 < frame_count:
            t_end = (times[i] + times[i + 1]) / 2
        else:
            t_end = times[i] + 0.2  # 片段末帧：短暂停留区间
        if same_seg_prev:
            t_start = (times[i - 1] + times[i]) / 2
        else:
            t_start = times[i] - 0.2  # 片段首帧：从采样点前开始
        lines.append(f'{_ts(t_start)} --> {_ts(t_end)}')
        lines.append(f'xywh={x},{y},{fw},{fh}')
        lines.append(f'seg={seg_of[i]}')
        lines.append('')
    return '\n'.join(lines)


def _is_remote_path(path):
    """判断路径是否在远程/网络位置（UNC 或映射的网络盘）。

    网络盘上的视频若被多帧抽图并发读取，极易把网络 I/O 打满导致抽帧失败/超时，
    表现为「雪碧图生成失败，回退静态 JPG」。本地盘则无此问题。
    """
    if not path:
        return False
    if path.startswith('\\\\') or path.startswith('//'):
        return True
    if len(path) >= 2 and path[1] == ':':
        try:
            if os.name == 'nt':
                dt = ctypes.windll.kernel32.GetDriveTypeW(path[:2] + '\\')
                return dt == 4  # DRIVE_REMOTE
        except Exception:
            return False
    return False


def _extract_one_frame(ffmpeg, src_path, t, long_edge, fp):
    """用快速输入 seek 抽取单帧；成功返回 True。"""
    cmd = [
        ffmpeg, '-y', '-ss', f'{t:.3f}', '-i', src_path,
        '-frames:v', '1', '-vf', f'scale={long_edge}:-2', '-q:v', '5', fp,
    ]
    r = subprocess.run(
        cmd, capture_output=True, text=True, errors='replace', timeout=60,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    )
    return r.returncode == 0 and os.path.exists(fp)


def _png_size(probe, fp):
    """读取 png 宽高，失败返回 (0, 0)。"""
    if not probe:
        return (0, 0)
    try:
        r = subprocess.run(
            [probe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
             'stream=width,height', '-of', 'csv=p=0', fp],
            capture_output=True, text=True, errors='replace', timeout=10,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        )
        if r.returncode == 0 and ',' in r.stdout:
            parts = r.stdout.strip().split(',')
            return (int(parts[0]), int(parts[1]))
    except Exception:
        pass
    return (0, 0)


def _normalize_frame_size(ffmpeg, fp, w, h):
    """把单帧强制缩放/填充到一致的 w x h，避免 tile 因尺寸不一而失败。"""
    tmp = fp + '.norm.png'
    cmd = [
        ffmpeg, '-y', '-i', fp,
        '-vf', f'scale={w}:{h}:force_original_aspect_ratio=decrease,'
               f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2',
        '-frames:v', '1', tmp,
    ]
    r = subprocess.run(
        cmd, capture_output=True, text=True, errors='replace', timeout=20,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    )
    if r.returncode == 0 and os.path.exists(tmp):
        try:
            os.replace(tmp, fp)
        except Exception:
            pass


def _generate_sprite(task, pv):
    """生成 sprite 雪碧图 + VTT 索引 + poster 首帧（默认封面格式）。

    鲁棒性要点（修复「雪碧图生成失败、回退静态 JPG」）：
      1) 网络/UNC 路径先把整文件拷到本地临时目录，把「12 次并发网络 seek」降为
         「1 次顺序拷贝 + 12 次本地读取」，避免网络 I/O 打满导致抽帧失败/超时；
      2) 单帧抽图失败不再放弃整张雪碧图：相邻时间点重试 → 用上一帧替代 → 用首帧兜底；
      3) 抽好的帧统一缩放到一致尺寸后再 tile，避免个别帧尺寸异常导致拼接失败；
      4) 拷贝/抽帧的超时单独放宽（见 generate_thumbnail 的 sprite 超时）。

    Returns:
        (True, poster_path) 成功
        (False, error)      失败（调用方回退到静态 JPG）
    """
    video_path = task.video_path
    video_hash = task.video_hash

    duration = _probe_duration(video_path)
    if not duration or duration <= 0:
        return False, '无法获取视频时长'

    cols = int(pv.get('sprite_cols', 4))
    long_edge = int(pv.get('sprite_long_edge', 180))
    head_skip = float(pv.get('head_skip', 0.08))
    tail_skip = float(pv.get('tail_skip', 0.08))
    # 片段式采样：在 segment_count 个关键时间点各密集抽 frames_per_segment 帧
    n_seg = int(pv.get('segment_count', 4))
    fps = int(pv.get('frames_per_segment', 3))
    gap = float(pv.get('segment_frame_gap', 0.4))
    n_seg = max(1, min(12, n_seg))
    fps = max(1, min(8, fps))
    gap = max(0.1, min(2.0, gap))
    n = n_seg * fps
    n = max(1, min(48, n))
    cols = max(1, cols)

    # 去头去尾后的有效采样窗口
    head = min(max(0.0, head_skip), 0.5) * duration
    tail = min(max(0.0, tail_skip), 0.5) * duration
    if duration - head - tail < 0.5:  # 视频太短，退化为全片采样
        head, tail = 0, 0
    start = head
    window = max(0.5, duration - head - tail)
    # 片段中心均匀分布在有效区间，片段内围绕中心密集采样（几秒连续片段）
    times = []
    seg_of = []
    for s in range(n_seg):
        center = start + window * (s + 0.5) / n_seg
        for f in range(fps):
            t = center + (f - (fps - 1) / 2.0) * gap
            t = max(0.0, min(duration - 0.05, t))
            times.append(t)
            seg_of.append(s)

    # 行数 = ceil(n / cols)
    rows = math.ceil(n / cols)

    sprite_path = os.path.join(THUMBNAIL_DIR, f'{video_hash}.sprite.jpg')
    poster_path = os.path.join(THUMBNAIL_DIR, f'{video_hash}.jpg')
    vtt_path = os.path.join(THUMBNAIL_DIR, f'{video_hash}.vtt')

    ffmpeg = shutil.which('ffmpeg')
    probe = shutil.which('ffprobe')
    if not ffmpeg:
        return False, 'ffmpeg 不可用'

    # 网络/UNC 路径：整文件拷到本地临时目录，降低网络 I/O 竞争
    src_path = video_path
    tmp_copy = None
    try:
        if _is_remote_path(video_path):
            try:
                fsize = os.path.getsize(video_path)
            except Exception:
                fsize = 0
            # 仅对不超过 2GB 的文件做本地拷贝；超大文件直接抽取（配合更长超时与重试）
            if 0 < fsize <= 2 * 1024 ** 3:
                ext = os.path.splitext(video_path)[1] or '.mp4'
                tmp_copy = os.path.join(THUMBNAIL_DIR, f'.copy_{video_hash}{ext}')
                shutil.copyfile(video_path, tmp_copy)
                src_path = tmp_copy
    except Exception:
        src_path = video_path
        tmp_copy = None

    tmp_dir = os.path.join(THUMBNAIL_DIR, f'.sprite_tmp_{video_hash}')
    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        os.makedirs(tmp_dir, exist_ok=True)
        frame_files = []
        last_good = None
        for i, t in enumerate(times):
            fp = os.path.join(tmp_dir, f'f{i:02d}.png')
            ok = _extract_one_frame(ffmpeg, src_path, t, long_edge, fp)
            if not ok:
                retry_t = max(0.0, min(duration - 0.05, t + 0.3))
                ok = _extract_one_frame(ffmpeg, src_path, retry_t, long_edge, fp)
            if not ok and last_good and os.path.exists(last_good):
                try:
                    shutil.copyfile(last_good, fp)
                    ok = True
                except Exception:
                    ok = False
            if ok:
                last_good = fp
            else:
                # 仍失败：用首帧兜底，实在没有才真正放弃
                if frame_files and os.path.exists(frame_files[0]):
                    try:
                        shutil.copyfile(frame_files[0], fp)
                        ok = True
                    except Exception:
                        ok = False
            if not ok:
                return False, f'第 {i} 帧抽取失败（无可用替代帧）'
            frame_files.append(fp)

        # 统一帧尺寸，避免个别帧尺寸异常导致 tile 拼接失败
        fw0 = fh0 = 0
        for fp in frame_files:
            w, h = _png_size(probe, fp)
            if w and h:
                fw0, fh0 = w, h
                break
        if not fw0:
            return False, '无法读取抽取帧尺寸'
        for fp in frame_files:
            _normalize_frame_size(ffmpeg, fp, fw0, fh0)

        # tile 拼接：逐行水平拼接，再整体垂直拼接
        inputs = []
        for fp in frame_files:
            inputs.extend(['-i', fp])
        fc = ''
        for row in range(rows):
            start_i = row * cols
            end_i = min(start_i + cols, n)
            names = [f'[{i}:v]' for i in range(start_i, end_i)]
            if len(names) > 1:
                fc += ''.join(names) + f'hstack=inputs={len(names)}[r{row}];'
            else:
                # 单行单帧：copy 保证滤镜图合法
                fc += f'{names[0]}copy[r{row}];'
        row_inputs = ''.join(f'[r{r}]' for r in range(rows))
        fc += f'{row_inputs}vstack=inputs={rows}[out]'

        tile_cmd = [
            ffmpeg, '-y',
            *inputs,
            '-filter_complex', fc,
            '-map', '[out]',
            '-frames:v', '1', '-q:v', '5', sprite_path,
        ]
        tr = subprocess.run(
            tile_cmd, capture_output=True, text=True, errors='replace', timeout=90,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        )
        if tr.returncode != 0 or not os.path.exists(sprite_path):
            return False, '雪碧图拼图失败'
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if tmp_copy and os.path.exists(tmp_copy):
            try:
                os.remove(tmp_copy)
            except Exception:
                pass

    # 单帧几何：所有帧已统一缩放到 fw0 x fh0，雪碧图即 cols×rows 个等尺寸格，
    # 直接使用归一化尺寸即可得到正确的 VTT 坐标（避免单行少帧时 sw//cols 失真）。
    fw, fh = fw0, fh0

    # 写 VTT 索引
    vtt = _build_vtt(pv, video_hash, fw, fh, cols, rows, start, window, times, seg_of)
    try:
        with open(vtt_path, 'w', encoding='utf-8') as f:
            f.write(vtt)
    except Exception as e:
        return False, f'写入 VTT 失败: {e}'

    # 导出 poster：取雪碧图左上角第一帧（有效区间首个采样点）
    if os.path.exists(poster_path):
        try:
            os.remove(poster_path)
        except OSError:
            pass
    crop = f'crop={fw}:{fh}:0:0'
    pc = subprocess.run(
        [ffmpeg, '-y', '-i', sprite_path, '-vf', crop, '-frames:v', '1',
         '-q:v', '5', '-update', '1', poster_path],
        capture_output=True, text=True, errors='replace', timeout=15,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    )
    if pc.returncode != 0 or not os.path.exists(poster_path):
        return False, 'poster 导出失败'

    return True, poster_path


# ============ 封面生成核心逻辑 ============
# 单任务整体超时（秒）：cv2 在某些损坏/特殊编码视频上 cap.read() 可能永久阻塞，
# 若不加超时，卡死的任务会永久占用 worker 线程，导致整个队列停滞、控制面看到
# active 数永远不变却无文件产出。超时即放弃该任务并标记为失败，释放 worker。
TASK_TIMEOUT = 25


def _do_generate(task):
    """实际生成逻辑，在独立线程中运行以便超时控制。"""
    if not os.path.exists(task.video_path):
        return False, "视频文件不存在"

    output_format = task.format

    # ---- Sprite 雪碧图 + VTT 悬停预览（默认格式）----
    # 用 ffmpeg 单次调用生成，与 cv2 无关。失败时回退到静态 JPG（不产 sprite/vtt）。
    if output_format == 'sprite':
        pv = _load_preview_config()
        if pv.get('enabled') and _ffmpeg_available():
            ok, res = _generate_sprite(task, pv)
            if ok:
                return True, res
            # sprite 生成失败：静默回退静态 JPG
            log_warn = f'sprite 生成失败({res})，回退静态 JPG: {task.video_hash}'
            import logging
            logging.getLogger('thumbnail').warning(f'[thumbnail] {log_warn}')
        # 回退静态 JPG：走下方 cv2 单帧逻辑（output_format 临时改成静态）
        output_format = 'jpg'

    # cv2 / PIL 仅在 gif 与静态 JPG 分支用到（sprite 路径走 ffmpeg，无需它们）
    import cv2
    from PIL import Image

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

    # 雪碧图需要将视频整体拷贝到本地 + 逐帧抽取 + 拼图，耗时远高于静态封面，
    # 故按格式使用不同的整体超时阈值。
    per_format_timeout = {
        'sprite': 120,
        'gif': 60,
        'png': 30,
        'static': 30,
    }
    timeout = per_format_timeout.get(getattr(task, 'format', None), TASK_TIMEOUT)

    def _runner():
        try:
            result['val'] = _do_generate(task)
        except Exception as e:
            result['val'] = (False, str(e))

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        # 超时：cv2 卡死，放弃该任务（cap 在子线程中稍后会被 GC 释放）
        import logging
        logging.getLogger('thumbnail').warning(
            f'[thumbnail] 生成超时（>{timeout}s）跳过: {task.video_hash} path={task.video_path}'
        )
        return False, f"生成超时（>{timeout}s），跳过该视频"
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
