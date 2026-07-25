#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X（原 Twitter）媒体下载脚本，适配 DPlayer 外部脚本引擎。

运行契约（详见 src/web/script_engine）：
  - 通过 stdin 读取 JSON：{job_id, params, context}
      context.working_dir : 任务临时目录（产物放在这里，结束前会被清理）
      context.notify      : {url, token} 入库通知回调
      context.cookies     : {domain: {path, format}} 保险库注入的 cookie（本脚本用 string 参数传入，不依赖它）
  - 通过 stdout 逐行上报：
      {"type":"progress","percent":0-100,"message":""}
      {"type":"log","level":"info|warn|error","message":""}
      {"type":"await_input","input":{prompt,options:[{value,label}],multi,min,max,allow_text,text_hint}}
      {"type":"result","files":[{"path":...,"type":"video|image"}]}
  - 分阶段交互：上报 await_input 后，长轮询 GET context.notify.url 的同级 /input 端点等待管理员选择。

依赖：yt-dlp（视频用其下载；图片用 urllib 直链下载）。
      pip install yt-dlp[default]   （default 含 ffmpeg 之外的依赖；合并视频仍需系统 ffmpeg）
"""
import sys
import os
import io
import re
import json
import time
import shutil
import subprocess
import urllib.parse
import urllib.request
import urllib.error

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')


# ---------------- stdout 上报 ----------------
def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def progress(pct, message=''):
    emit({'type': 'progress', 'percent': int(pct), 'message': message})


def log(message, level='info'):
    emit({'type': 'log', 'level': level, 'message': message})


def error(message):
    emit({'type': 'error', 'message': message})


def normalize_proxy(p):
    p = (p or '').strip()
    if not p:
        return None
    if '://' not in p:
        p = 'http://' + p
    return p


def result(files):
    emit({'type': 'result', 'files': files})


# ---------------- 交互：长轮询等待用户选择 ----------------
def fetch_input(input_ctx, timeout=25):
    """阻塞等待管理后台的用户答复。返回答复值（多选为数组），超时/取消返回 None。"""
    url = input_ctx.get('url')
    token = input_ctx.get('token')
    if not url:
        return None
    # GET /api/scripts/jobs/<id>/input
    input_url = url.rstrip('/').replace('/notify', '/input')
    while True:
        try:
            req = urllib.request.Request(input_url, headers={
                'Authorization': f'Bearer {token}',
                'User-Agent': UA,
            })
            resp = urllib.request.urlopen(req, timeout=timeout + 5)
            if resp.status == 204:
                continue
            data = resp.read().decode('utf-8', 'replace').strip()
            if not data:
                continue
            return json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code == 204:
                continue
            # 400/404：非法请求，放弃
            if e.code in (400, 404):
                return None
            time.sleep(2)
        except Exception:
            time.sleep(2)


# ---------------- 入库通知 ----------------
def notify_input(input_ctx, files):
    """把下载好的文件登记给管理器，由其移动到资源库并入库。失败则降级为 result 行。"""
    url = input_ctx.get('url')
    token = input_ctx.get('token')
    if url and token:
        try:
            req = urllib.request.Request(
                url, data=json.dumps({'files': files}, ensure_ascii=False).encode('utf-8'),
                headers={
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json',
                    'User-Agent': UA,
                }, method='POST')
            urllib.request.urlopen(req, timeout=15)
            log(f'已通知入库 {len(files)} 个文件')
            return
        except Exception as e:
            log(f'入库通知失败（将降级为 result）: {e}', level='warn')
    result(files)


# ---------------- 媒体解析（yt-dlp） ----------------
def extract_media(url, cookie_header, proxy):
    """用 yt-dlp 解析推文，返回媒体列表：[{type:'image'|'video', url, label}]。"""
    cmd = ['yt-dlp', '--no-warnings', '--skip-download', '-J', url]
    if cookie_header:
        cmd += ['--add-header', f'Cookie: {cookie_header}']
    if proxy:
        cmd += ['--proxy', proxy]
    log('正在解析推文（yt-dlp）…')
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        raise RuntimeError('yt-dlp 解析超时')
    if proc.returncode != 0:
        raise RuntimeError('yt-dlp 解析失败: ' + (proc.stderr or proc.stdout)[:600])

    info = json.loads(proc.stdout)
    media = []

    is_video = bool(
        info.get('requested_formats')
        or (info.get('url') and (info.get('ext') in ('mp4', 'm3u8')
                                 or 'video' in str(info.get('protocol', ''))))
    )
    if is_video:
        media.append({
            'type': 'video',
            'url': url,  # 视频用 yt-dlp 重新下载整条推文
            'label': '视频/动图',
        })
    else:
        images = info.get('images') or []
        for i, img in enumerate(images):
            media.append({
                'type': 'image',
                'url': img,
                'label': f'图片 {i + 1}',
            })
    return media


# ---------------- 下载 ----------------
def download_image(url, cookie_header, working_dir, index, proxy):
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1] or '.jpg'
    ext = ext if ext.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp') else '.jpg'
    dest = os.path.join(working_dir, f'x_media_{index}{ext}')
    headers = {'User-Agent': UA}
    if cookie_header:
        headers['Cookie'] = cookie_header
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({'http': proxy, 'https': proxy}))
    opener = urllib.request.build_opener(*handlers) if handlers else urllib.request.build_opener()
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=60) as r, open(dest, 'wb') as f:
        shutil.copyfileobj(r, f)
    return dest


def download_video(tweet_url, cookie_header, working_dir, tweet_id, proxy):
    out_tmpl = os.path.join(working_dir, f'{tweet_id}.%(ext)s')
    cmd = ['yt-dlp', '--no-warnings', '-o', out_tmpl, tweet_url]
    if cookie_header:
        cmd += ['--add-header', f'Cookie: {cookie_header}']
    if proxy:
        cmd += ['--proxy', proxy]
    log('正在下载视频（yt-dlp）…')
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=540)
    if proc.returncode != 0:
        raise RuntimeError('视频下载失败: ' + (proc.stderr or proc.stdout)[:400])
    # 找到本次产出的视频文件
    for fn in os.listdir(working_dir):
        if fn.startswith(tweet_id) and fn.lower().endswith(
                ('.mp4', '.mkv', '.webm', '.mov', '.m4v', '.avi', '.ts')):
            return os.path.join(working_dir, fn)
    raise RuntimeError('视频下载完成但未找到产出文件')


def simulate_media():
    """演示用：合成 3 个媒体（2 图 + 1 视频），用于体现“二次选择”交互。"""
    return [
        {'type': 'image', 'url': 'https://pbs.twimg.com/demo/1.jpg', 'label': '图片 1（演示）'},
        {'type': 'image', 'url': 'https://pbs.twimg.com/demo/2.jpg', 'label': '图片 2（演示）'},
        {'type': 'video', 'url': 'https://x.com/demo/status/0', 'label': '视频（演示）'},
    ]


def write_sim_placeholder(working_dir, index, mtype):
    ext = '.jpg' if mtype == 'image' else '.mp4'
    dest = os.path.join(working_dir, f'x_demo_{index}{ext}')
    with open(dest, 'w', encoding='utf-8') as f:
        f.write(f'demo placeholder for {mtype}\n')
    return dest


# ---------------- 主流程 ----------------
def main():
    raw = sys.stdin.read() if not sys.stdin.isatty() else '{}'
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    params = payload.get('params', {}) or {}
    context = payload.get('context', {}) or {}
    working_dir = context.get('working_dir') or os.getcwd()
    notify_ctx = context.get('notify', {}) or {}
    cookie_header = (params.get('cookie') or '').strip()
    url = (params.get('url') or '').strip()
    simulate = bool(params.get('simulate'))
    proxy = normalize_proxy(params.get('proxy'))
    if proxy:
        log(f'使用代理访问 X: {proxy}')

    if not url:
        error('缺少推文链接参数 url')
        sys.exit(1)

    m = re.search(r'/status/(\d+)', url)
    tweet_id = m.group(1) if m else 'x'

    progress(5, '开始解析推文')
    try:
        if simulate:
            log('演示模式：合成媒体列表（不联网）')
            media = simulate_media()
        else:
            media = extract_media(url, cookie_header, proxy)
    except Exception as e:
        error(str(e))
        sys.exit(1)

    if not media:
        error('未在该推文中找到任何图片或视频')
        sys.exit(1)

    log(f'解析到 {len(media)} 个媒体：' + '，'.join(x['label'] for x in media))

    selected = media
    # 多个资源 -> 二次触发用户选择
    if len(media) > 1:
        options = [{'value': str(i), 'label': x['label']} for i, x in enumerate(media)]
        progress(20, '等待用户选择要下载的媒体…')
        emit({
            'type': 'await_input',
            'input': {
                'prompt': f'该推文包含 {len(media)} 个媒体，请选择要下载的项（可多选）：',
                'options': options,
                'multi': True,
                'min': 1,
                'max': len(media),
                'allow_text': False,
                'text_hint': '',
            },
        })
        resp = fetch_input(notify_ctx)
        if resp is None:
            # 超时/取消：默认全选（避免任务卡死，也便于离线演示）
            log('未收到选择，默认下载全部', level='warn')
            indices = list(range(len(media)))
        else:
            try:
                vals = resp if isinstance(resp, list) else [resp]
                indices = [int(v) for v in vals if str(v).isdigit()]
            except Exception:
                indices = list(range(len(media)))
            if not indices:
                indices = list(range(len(media)))
        selected = [media[i] for i in indices]
        log('用户选择：' + '，'.join(x['label'] for x in selected))
    else:
        log('仅 1 个媒体，直接下载')

    progress(40, f'开始下载 {len(selected)} 个媒体')

    downloaded = []
    total = len(selected)
    for idx, item in enumerate(selected, start=1):
        pct = 40 + int(50 * idx / total)
        try:
            if item['type'] == 'image':
                if simulate:
                    path = write_sim_placeholder(working_dir, idx, 'image')
                else:
                    path = download_image(item['url'], cookie_header, working_dir, idx, proxy)
                downloaded.append({'path': path, 'type': 'image'})
                log(f'已下载图片: {os.path.basename(path)}')
            else:
                if simulate:
                    path = write_sim_placeholder(working_dir, idx, 'video')
                else:
                    path = download_video(url, cookie_header, working_dir, tweet_id, proxy)
                downloaded.append({'path': path, 'type': 'video'})
                log(f'已下载视频: {os.path.basename(path)}')
            progress(pct, f'下载进度 {idx}/{total}')
        except Exception as e:
            error(f'下载失败（{item["label"]}）: {e}')

    if not downloaded:
        error('没有任何文件下载成功')
        sys.exit(1)

    progress(95, '通知入库…')
    notify_input(notify_ctx, downloaded)
    progress(100, f'完成，共下载 {len(downloaded)} 个文件')
    sys.exit(0)


if __name__ == '__main__':
    # 兼容 stdout 缓冲问题
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)
    main()
