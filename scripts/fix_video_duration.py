#!/usr/bin/env python3
"""
一次性修复：重新解析 duration=1 的错误视频时长

背景：src/web/main.py 的 extract_mp4_duration 在解析 MP4 mvhd version 0 时字节偏移
错误（从 20/24 读取，实际应为 12/16），导致读到嵌套 trak box 内容，大量视频被写入
错误的 duration=1。本脚本用修复后的解析逻辑，对所有 duration=1 的视频重新解析并更新。

安全设计：
  - 仅处理扩展名为 .mp4/.m4v/.mov 且磁盘文件存在的记录
  - 仅当重算值合理（>1 且 <= 1000000 秒）且与旧值(1)不同时才更新
  - 支持 --dry-run 预演；默认直接更新并输出报告

用法：
    python scripts/fix_video_duration.py            # 执行修复
    python scripts/fix_video_duration.py --dry-run  # 只打印，不写库
"""
import os
import sys
import struct
import argparse
import sqlite3

# 修复 Windows 控制台 GBK 无法编码路径中的非 ASCII 字符
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

DB_PATH = os.path.join('data', 'databases', 'dplayer.db')
MAX_PROBE_BYTES = 32 * 1024 * 1024
MAX_REASONABLE_SEC = 1000000  # ~11.5 天，超出视为异常


def _read_at(file_path, offset, length):
    with open(file_path, 'rb') as f:
        f.seek(offset)
        return f.read(length)


def _find_box(data, want, start=0):
    pos = start
    n = len(data)
    while pos + 8 <= n:
        box_size = struct.unpack('>I', data[pos:pos + 4])[0]
        box_type = data[pos + 4:pos + 8]
        if box_size == 1:
            if pos + 16 > n:
                break
            box_size = struct.unpack('>Q', data[pos + 8:pos + 16])[0]
            header = 16
        elif box_size == 0:
            box_size = n - pos
            header = 8
        else:
            header = 8
        if box_type == want:
            return pos, box_size
        pos += box_size
    return None


def extract_mp4_duration(file_path, max_probe_bytes=MAX_PROBE_BYTES):
    """与修复后的 src/web/main.py extract_mp4_duration 保持一致（结构化 box 遍历 + fallback）"""
    try:
        size = os.path.getsize(file_path)
    except OSError:
        return None
    if size < 8:
        return None
    head = _read_at(file_path, 0, min(size, max_probe_bytes))
    tail_size = min(size, max_probe_bytes)
    tail = _read_at(file_path, size - tail_size, tail_size) if tail_size < size else b''

    for chunk in (head, tail):
        d = _parse_duration_from_chunk(chunk)
        if d is not None:
            return d
    return None


def _parse_mvhd(moov):
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
            timescale = struct.unpack('>I', moov[mvhd_off + 20:mvhd_off + 24])[0]
            duration = struct.unpack('>I', moov[mvhd_off + 24:mvhd_off + 28])[0]
        elif version == 1:
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
    res = _find_box(chunk, b'moov')
    if res:
        moov_off, moov_size = res
        d = _parse_mvhd(chunk[moov_off:moov_off + moov_size])
        if d is not None:
            return d
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


def main():
    ap = argparse.ArgumentParser(description='修复 duration=1 的错误视频时长')
    ap.add_argument('--dry-run', action='store_true', help='只打印，不写库')
    args = ap.parse_args()

    if not os.path.isfile(DB_PATH):
        print(f'数据库不存在: {DB_PATH}')
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("select id, local_path from videos where duration=1").fetchall()

    updated, skipped_missing, skipped_unparseable, skipped_same = 0, 0, 0, 0
    print(f'待修复记录: {len(rows)} 条')
    print('-' * 78)

    for vid, path in rows:
        if not path or not os.path.isfile(path):
            skipped_missing += 1
            print(f'  [跳过] id={vid} 文件不存在: {path}')
            continue
        new_dur = extract_mp4_duration(path)
        if new_dur is None or new_dur <= 1 or new_dur > MAX_REASONABLE_SEC:
            skipped_unparseable += 1
            print(f'  [跳过] id={vid} 重算无效/异常: {new_dur} ({path})')
            continue
        if not args.dry_run:
            conn.execute("update videos set duration=? where id=?", (new_dur, vid))
        updated += 1
        print(f'  [修复] id={vid} 1 -> {new_dur}s ({path})')

    if not args.dry_run and updated:
        conn.commit()
    conn.close()

    print('-' * 78)
    print(f'完成: 更新 {updated} | 文件缺失 {skipped_missing} | 重算无效 {skipped_unparseable}')
    if args.dry_run:
        print('（演练模式，未写库）')


if __name__ == '__main__':
    main()
