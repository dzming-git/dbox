"""纯计算类的媒体解析工具，不依赖 Flask app / request / session。

提供视频时长探测：优先用 ffprobe（覆盖 mkv/webm/avi 等所有容器），
不可用时回退到纯 Python 的 MP4 容器解析（无需 ffmpeg/cv2）。
"""
import os
import struct


_FFPROBE_CACHE = {'path': None, 'checked': False}


def _find_ffprobe():
    """定位 ffprobe 可执行文件，找不到返回 None（结果缓存）。

    为什么不能直接 `shutil.which('ffprobe')`：Web 服务以 Windows 服务方式运行，
    其 PATH **不包含**安装者的用户目录，而 WinGet 装的 ffprobe 就在
    `%LOCALAPPDATA%\\Microsoft\\WinGet\\Links` 下。结果就是「命令行里能跑、
    服务里一律找不到」——时长探测在服务端静默失效，只能靠 MP4 兜底。
    因此按 环境变量 → PATH → 常见安装位置 逐级找，并允许用 FFPROBE 显式指定。
    """
    if _FFPROBE_CACHE['checked']:
        return _FFPROBE_CACHE['path']
    found = None
    try:
        import shutil
        env = os.environ.get('FFPROBE')
        if env and os.path.isfile(env):
            found = env
        if not found:
            found = shutil.which('ffprobe')
        if not found:
            import glob
            patterns = [
                os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft',
                             'WinGet', 'Links', 'ffprobe.exe'),
                r'C:\Users\*\AppData\Local\Microsoft\WinGet\Links\ffprobe.exe',
                r'C:\ProgramData\chocolatey\bin\ffprobe.exe',
                '/usr/bin/ffprobe',
            ]
            for pat in patterns:
                for cand in glob.glob(pat):
                    if os.path.isfile(cand):
                        found = cand
                        break
                if found:
                    break
    except Exception:
        found = None
    _FFPROBE_CACHE.update({'path': found, 'checked': True})
    return found


def extract_duration(file_path):
    """探测视频时长（秒）；失败返回 None。

    **必须走 ffprobe 优先**：库里既有 mp4 也有 webm/mkv，纯 MP4 解析对后者一律
    返回 None，若只用它，「长视频 / 短视频」这类视图会静默少掉一大半数据。
    ffprobe 缺失或超时时才回退到 MP4 解析。
    """
    try:
        import subprocess
        exe = _find_ffprobe()
        if exe:
            r = subprocess.run(
                [exe, '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'csv=p=0', file_path],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0 and r.stdout.strip():
                val = float(r.stdout.strip().splitlines()[0])
                if val > 0:
                    return val
    except Exception:
        pass
    return extract_mp4_duration(file_path)


def _find_box(data, want, start=0):
    """在 data 内按 ISO BMFF 结构遍历，返回 (offset, box_size)；找不到返回 None。

    start 用于跳过外层 box 头（如进入 moov 后从子 box 起始处搜索）。

    ⚠️ 必须是**模块级**函数：``_parse_mvhd`` / ``_parse_duration_from_chunk``
    都要用它。此前它被定义在 `extract_mp4_duration` 内部，这两个模块级函数一调用
    就抛 NameError——整个 MP4 兜底路径其实是坏的（ffprobe 不可用时必崩）。
    """
    pos = start
    n = len(data)
    while pos + 8 <= n:
        box_size = struct.unpack('>I', data[pos:pos + 4])[0]
        box_type = data[pos + 4:pos + 8]
        if box_size == 1:
            # 64 位 size
            if pos + 16 > n:
                break
            box_size = struct.unpack('>Q', data[pos + 8:pos + 16])[0]
        elif box_size == 0:
            # box 延伸到文件结尾
            box_size = n - pos
        if box_type == want:
            return pos, box_size
        pos += box_size
    return None


def extract_mp4_duration(file_path, max_probe_bytes=32 * 1024 * 1024):
    """纯 Python 解析 MP4 容器头部提取视频时长（秒），无需 ffmpeg/cv2。

    按 ISO BMFF 规范结构化遍历 box：在文件头/尾各 max_probe_bytes 范围内，
    根据 box 的 size 字段逐级定位 moov -> mvhd，读取 timescale 与 duration 计算时长。
    这种方式避免了按字符串盲搜 'moov' 误匹配到非 box 数据导致的解析错误。
    仅读取文件头/尾最多 max_probe_bytes，避免读取数十 GB 的完整文件。
    非 MP4 或解析失败返回 None。
    """
    try:
        size = os.path.getsize(file_path)
    except OSError:
        return None
    if size < 8:
        return None

    def _read_at(offset, length):
        with open(file_path, 'rb') as f:
            f.seek(offset)
            return f.read(length)

    head = _read_at(0, min(size, max_probe_bytes))
    tail_size = min(size, max_probe_bytes)
    tail = _read_at(size - tail_size, tail_size) if tail_size < size else b''

    for chunk in (head, tail):
        d = _parse_duration_from_chunk(chunk)
        if d is not None:
            return d
    return None


def _parse_mvhd(moov):
    """从 moov box 内容中解析时长（秒），失败返回 None。"""
    if len(moov) < 8:
        return None
    res = _find_box(moov, b'mvhd', start=8)
    if not res:
        return None
    mvhd_off = res[0]
    if mvhd_off + 12 > len(moov):
        return None
    version = moov[mvhd_off + 8]
    try:
        if version == 0:
            # v0: timescale@20(4B), duration@24(4B)  (相对 mvhd box 起点)
            timescale = struct.unpack('>I', moov[mvhd_off + 20:mvhd_off + 24])[0]
            duration = struct.unpack('>I', moov[mvhd_off + 24:mvhd_off + 28])[0]
        elif version == 1:
            # v1: timescale@28(4B), duration@32(8B)
            timescale = struct.unpack('>I', moov[mvhd_off + 28:mvhd_off + 32])[0]
            duration = struct.unpack('>Q', moov[mvhd_off + 32:mvhd_off + 40])[0]
        else:
            return None
    except Exception:
        return None
    if timescale:
        return int(round(duration / timescale))
    return None


def _parse_duration_from_chunk(chunk):
    """从一段字节（文件头/尾切片）中解析视频时长。

    方法1：按 ISO BMFF 结构遍历定位 moov。
    方法2（fallback）：当切片不以合法 box 边界开头（如文件尾部切片）导致结构遍历
    错位时，按 'moov' 字节串定位 moov box 起点再解析。
    """
    # 方法1：结构化遍历
    res = _find_box(chunk, b'moov')
    if res:
        moov_off, moov_size = res
        d = _parse_mvhd(chunk[moov_off:moov_off + moov_size])
        if d is not None:
            return d
    # 方法2：字符串定位 fallback
    pos = 0
    n = len(chunk)
    while True:
        i = chunk.find(b'moov', pos)
        if i == -1:
            break
        moov_start = i - 4
        if moov_start >= 0 and moov_start + 8 <= n:
            box_size = struct.unpack('>I', chunk[moov_start:moov_start + 4])[0]
            if 8 <= box_size <= n - moov_start:
                d = _parse_mvhd(chunk[moov_start:moov_start + box_size])
                if d is not None:
                    return d
        pos = i + 1
    return None
