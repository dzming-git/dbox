"""纯计算类的媒体解析工具，不依赖 Flask app / request / session。

当前提供纯 Python 解析 MP4 容器头部提取视频时长，无需 ffmpeg/cv2。
"""
import os
import struct


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

    def _find_box(data, want, start=0):
        """在 data 内按 ISO BMFF 结构遍历，返回 (offset, box_size)；找不到返回 None。
        start 用于跳过外层 box 头（如进入 moov 后从子 box 起始处搜索）。"""
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
                header = 16
            elif box_size == 0:
                # box 延伸到文件结尾
                box_size = n - pos
                header = 8
            else:
                header = 8
            if box_type == want:
                return pos, box_size
            pos += box_size
        return None

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
            duration = struct.unpack('>I', moov[mvhd_off + 24:moov_off + 28])[0]
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
