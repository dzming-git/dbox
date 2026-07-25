"""演示脚本：下载视频（离线可运行版，演示 Cookie 注入全链路）。

真实使用时把下面注释里的 yt-dlp 命令替换掉模拟逻辑即可。
关键演示点：
1. 通过 stdin 接收 {job_id, params, context}
2. context.cookies 是管理器按 required_cookies / cookie_select 物化到 working_dir 的
   cookie 文件路径，例如 {".bilibili.com": {"path": ".../cookies.txt", "format": "netscape"}}
3. 通过 stdout 逐行输出 JSON 上报进度 / 日志
4. 通过 context.notify 回调通知 DPlayer 新资源入库（最终移动与入库由管理器统一完成）
"""
import sys
import os
import json
import time
import urllib.request


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def main():
    raw = sys.stdin.read()
    data = json.loads(raw)
    params = data.get('params', {})
    ctx = data.get('context', {})

    url = params.get('url', '')
    quality = params.get('quality', 'best')
    working_dir = ctx.get('working_dir', '.')

    emit({'type': 'log', 'message': f'收到任务，url={url}, quality={quality}'})

    # ---- Cookie 注入演示 ----
    cookies = ctx.get('cookies') or {}
    cookie_args = []
    for domain, info in cookies.items():
        path = info.get('path')
        if path and os.path.isfile(path):
            cookie_args.append(f'--cookies "{path}"')
            emit({'type': 'log', 'message': f'使用 {domain} 的 cookie 文件: {path}'})

    # 真实下载命令示例（需 pip install yt-dlp）：
    # cmd = f'yt-dlp {" ".join(cookie_args)} -f {quality} -o "{os.path.join(working_dir, "%(title)s.%(ext)s)")}" {url}'
    emit({'type': 'log', 'message': '(演示) 真实命令将类似: yt-dlp '
         + ' '.join(cookie_args) + f' -f {quality} "{url}"'})

    emit({'type': 'progress', 'percent': 10, 'message': '准备下载'})
    time.sleep(0.3)
    emit({'type': 'progress', 'percent': 40, 'message': '下载中...'})
    time.sleep(0.3)

    # 生成占位产物（真实场景由下载器产出），放在 working_dir 下，由管理器移动到资源库
    safe = ''.join(c if c.isalnum() else '_' for c in (url or 'video'))[:40]
    out = os.path.join(working_dir, f'{safe}.mp4')
    with open(out, 'w', encoding='utf-8') as f:
        f.write('demo placeholder for ' + url + '\n')

    emit({'type': 'progress', 'percent': 80, 'message': '生成完成，通知入库'})
    time.sleep(0.2)

    # 回调通知（与契约一致）
    notify = ctx.get('notify', {})
    nurl = notify.get('url')
    token = notify.get('token')
    if nurl and token:
        try:
            req = urllib.request.Request(
                nurl,
                data=json.dumps({'token': token, 'files': [{'path': out, 'type': 'video'}]}).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            emit({'type': 'error', 'message': f'notify 失败: {e}'})

    emit({'type': 'progress', 'percent': 100, 'message': '完成'})
    emit({'type': 'result', 'files': [{'path': out, 'type': 'video'}]})


if __name__ == '__main__':
    main()
