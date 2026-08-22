"""演示脚本：下载视频（离线可运行版，演示 Cookie 注入全链路）。

真实使用时把下面注释里的 yt-dlp 命令替换掉模拟逻辑即可。
关键演示点：
1. 通过 stdin 接收 {job_id, params, context}
2. context.cookies 是管理器按 required_cookies / cookie_select 物化到 working_dir 的
   cookie 文件路径，例如 {".bilibili.com": {"path": ".../cookies.txt", "format": "netscape"}}
3. 通过 stdout 逐行输出 JSON 上报进度 / 日志
4. 通过 context.notify 回调通知 Dbox 新资源入库（最终移动与入库由管理器统一完成）
"""
import sys
import os
import json
import time
import urllib.request


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def parse_videos(url):
    """演示：根据 url 模拟解析出多个视频。"""
    names = ['开场动画', '正片 Part 1', '正片 Part 2', '幕后花絮', '彩蛋']
    return [{'value': str(i + 1), 'label': f'第{i + 1}个：{n}.mp4'} for i, n in enumerate(names)]


def fetch_input(input_ctx, timeout=30):
    """长轮询拉取用户对脚本提问的答复。input_ctx 含 {url, token}。"""
    base = input_ctx.get('url')
    token = input_ctx.get('token')
    if not base:
        return []
    url = base + ('&' if '?' in base else '?') + 'token=' + token
    while True:
        try:
            req = urllib.request.Request(url, headers={'Content-Type': 'application/json'}, method='GET')
            with urllib.request.urlopen(req, timeout=timeout + 1) as resp:
                if resp.status == 204:
                    time.sleep(1)
                    continue
                data = json.loads(resp.read().decode('utf-8'))
                if data.get('success') and data.get('value') is not None:
                    return data['value']
                return []  # 403/404 等：停止重试
        except Exception:
            time.sleep(2)


def main():
    raw = sys.stdin.read()
    data = json.loads(raw)
    params = data.get('params', {})
    ctx = data.get('context', {})

    url = params.get('url', '')
    quality = params.get('quality', 'best')
    working_dir = ctx.get('working_dir', '.')

    # 演示两类自定义参数：多选(multi_enum) + 预设/自定义(enum_editable)
    tags = params.get('tags', [])
    mode = params.get('mode', '')
    emit({'type': 'log', 'message': f'收到任务，url={url}, quality={quality}'})
    emit({'type': 'log', 'message': f'tags(多选)={tags}, mode(预设/自定义)={mode}'})

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

    # ---- 阶段一：解析出多个视频，请求用户选择（分阶段交互演示）----
    emit({'type': 'progress', 'percent': 10, 'message': '解析视频列表'})
    time.sleep(0.3)
    videos = parse_videos(url)
    emit({'type': 'log', 'message': f'解析到 {len(videos)} 个视频'})

    input_ctx = ctx.get('input') or {}
    chosen = []
    if input_ctx.get('url'):
        emit({'type': 'await_input', 'input': {
            'prompt': f'该链接包含 {len(videos)} 个视频，选择要下载的（可多选）：',
            'options': videos,
            'multi': True,
            'min': 1,
            'max': len(videos),
        }})
        chosen = fetch_input(input_ctx)
        emit({'type': 'log', 'message': f'用户选择: {chosen}'})
    else:
        # 没有交互通道（如脱离 web 单独运行）时，默认全选
        chosen = [v['value'] for v in videos]

    selected = [v for v in videos if v['value'] in chosen]
    if not selected:
        emit({'type': 'error', 'message': '未选择任何视频'})
        emit({'type': 'result', 'files': []})
        return

    # ---- 阶段二：按用户选择逐个"下载" ----
    files = []
    for i, v in enumerate(selected):
        emit({'type': 'progress', 'percent': 20 + int(60 * (i + 1) / len(selected)),
              'message': f'下载 {v["label"]}'})
        time.sleep(0.3)
        safe = ''.join(c if c.isalnum() else '_' for c in v['label'])[:40]
        out = os.path.join(working_dir, f'{safe}.mp4')
        with open(out, 'w', encoding='utf-8') as f:
            f.write('demo placeholder for ' + v['label'] + '\n')
        files.append({'path': out, 'type': 'video'})

    emit({'type': 'progress', 'percent': 90, 'message': '生成完成，通知入库'})
    time.sleep(0.2)

    # 回调通知（与契约一致）
    notify = ctx.get('notify', {})
    nurl = notify.get('url')
    token = notify.get('token')
    if nurl and token and files:
        try:
            req = urllib.request.Request(
                nurl,
                data=json.dumps({'token': token, 'files': files}).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            emit({'type': 'error', 'message': f'notify 失败: {e}'})

    emit({'type': 'progress', 'percent': 100, 'message': '完成'})
    emit({'type': 'result', 'files': files})


if __name__ == '__main__':
    main()
