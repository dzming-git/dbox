#!/usr/bin/env python3
"""演示外部脚本：模拟下载并把文件落到资源库，再调用 notify 上报。

真实场景下，把"下载"部分替换为实际下载逻辑（如 yt-dlp / requests），
其余契约（stdin 读参、stdout 输出 JSONL、移动到库路径、调用 notify）保持不变。
"""
import sys
import os
import json
import time


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def main():
    raw = sys.stdin.read()
    data = json.loads(raw)
    params = data.get('params', {})
    ctx = data.get('context', {})
    working_dir = ctx.get('working_dir', '.')
    libs = ctx.get('libraries', [])
    notify = ctx.get('notify', {})
    dest_dir = libs[0]['path'] if libs else working_dir

    url = params.get('url', 'http://example.com/video')
    quality = params.get('quality', '1080')
    emit({"type": "log", "level": "info", "message": f"开始处理: {url}  清晰度={quality}"})

    # 模拟下载进度
    for p in range(0, 101, 20):
        emit({"type": "progress", "percent": p, "message": f"下载中 {p}%"})
        time.sleep(0.3)

    # 在临时目录生成一个占位"视频"文件（真实场景应写入实际视频字节）
    fname = "demo_" + os.urandom(4).hex() + ".mp4"
    tmp = os.path.join(working_dir, fname)
    with open(tmp, 'wb') as f:
        f.write(b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom\x00\x00\x00\x08free')

    emit({"type": "log", "level": "info", "message": f"已生成文件: {tmp}（由管理器移动到资源库并入库）"})

    # 直接调用 notify 接口，把产出文件交给 DPlayer（管理器负责移动+入库）
    nurl = notify.get('url')
    token = notify.get('token')
    if nurl and token:
        try:
            import urllib.request
            req = urllib.request.Request(
                nurl + '?token=' + token,
                data=json.dumps({"files": [{"path": tmp, "type": "video"}]}).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                emit({"type": "log", "level": "info", "message": "上报结果: " + r.read().decode('utf-8')})
        except Exception as e:
            emit({"type": "error", "message": f"上报失败: {e}"})

    emit({"type": "result", "files": [tmp]})


if __name__ == '__main__':
    main()
