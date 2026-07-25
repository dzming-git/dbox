#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X（原 Twitter）媒体下载脚本，适配 DPlayer 外部脚本引擎。

纯爬虫实现，不依赖 yt-dlp：
  - 图片：从推文页面 / 接口解析 pbs.twimg.com 原图直链，urllib 直连下载。
  - 视频：解析出 video.twimg.com 的 m3u8（HLS）播放列表，
          自行下载全部 .ts 分片，再用系统 ffmpeg 合并为 mp4。

运行契约（详见 src/web/script_engine）：
  - 通过 stdin 读取 JSON：{job_id, params, context}
      context.working_dir : 任务临时目录（产物放在这里，结束前会被清理）
      context.notify      : {url, token} 入库通知回调
      context.cookies     : {domain: {path, format}} 保险库注入的 cookie
  - 通过 stdout 逐行上报：
      {"type":"progress","percent":0-100,"message":""}
      {"type":"log","level":"info|warn|error","message":""}
      {"type":"await_input","input":{prompt,options:[{value,label}],multi,min,max,allow_text,text_hint}}
      {"type":"result","files":[{"path":...,"type":"video|image"}]}
  - 分阶段交互：上报 await_input 后，长轮询 GET /api/scripts/jobs/<id>/input 等待管理员选择。

依赖：标准库 + 系统 ffmpeg（合并视频分片）。若使用 SOCKS 代理，需 pip install pysocks。
"""
import sys
import os
import io
import re
import json
import time
import shutil
import socket
import subprocess
import urllib.parse
import urllib.request
import urllib.error

try:
    import socks as _socks_mod
    HAS_SOCKS = True
except Exception:
    _socks_mod = None
    HAS_SOCKS = False

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')

# 当前代理配置（dict 或 None），由 main() 写入，供 fetch 时挂载 SOCKS。
_PROXY_CFG = None
_ORIG_SOCKET = socket.socket

# X 网页端公开的 Bearer Token（长期不变，用于访客/接口鉴权）
WEB_BEARER = ('AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAt4gJZwTZw9F9IgoIMvdI4kZ1Ric'
              'X0H6k8H1Z4Z8e7f3Y')

IMG_RE = re.compile(
    r'https://pbs\.twimg\.com/media/[A-Za-z0-9_-]+\.(?:jpg|jpeg|png|gif|webp)',
    re.IGNORECASE)
M3U8_RE = re.compile(
    r'https://video\.twimg\.com/[^\s"\'<>]+\.m3u8(?:\?[^\s"\'<>]*)?',
    re.IGNORECASE)
RENDITION_RE = re.compile(r'/vid/\d+x\d+/', re.IGNORECASE)


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


def parse_proxy(p):
    """解析代理参数，返回 dict：
       - None：直连
       - {'type':'http','addr':'http://host:port'}：HTTP/HTTPS 代理
       - {'type':'socks','scheme':'socks5'|'socks5h'|'socks4','host':..,'port':..}
       无 scheme 前缀时默认按 HTTP 处理（兼容旧值）。
    """
    p = (p or '').strip()
    if not p:
        return None
    if '://' in p:
        scheme, rest = p.split('://', 1)
        scheme = scheme.lower()
    else:
        scheme, rest = 'http', p
    if scheme in ('http', 'https'):
        prefix = 'http://' if scheme == 'http' else 'https://'
        return {'type': 'http', 'scheme': scheme, 'addr': prefix + rest}
    if scheme in ('socks5', 'socks5h', 'socks4', 'socks'):
        socks_scheme = 'socks5' if scheme == 'socks' else scheme
        host, _, port = rest.rpartition(':')
        host = host or '127.0.0.1'
        try:
            port = int(port)
        except ValueError:
            raise ValueError(f'代理端口无法解析: {rest}')
        return {'type': 'socks', 'scheme': socks_scheme,
                'host': host, 'port': port}
    # 未知 scheme 当作 HTTP
    return {'type': 'http', 'scheme': 'http', 'addr': 'http://' + p}


def make_opener(proxy_cfg):
    """返回一个带代理（可选）的 urllib opener，用于访问 X 域名。
       SOCKS 代理由 socket 层挂载，这里只用裸 opener。
    """
    if proxy_cfg and proxy_cfg['type'] == 'http':
        return urllib.request.build_opener(
            urllib.request.ProxyHandler(
                {'http': proxy_cfg['addr'], 'https': proxy_cfg['addr']}))
    return urllib.request.build_opener()


def _apply_socks():
    """若当前代理为 SOCKS，则把 socket 替换为 socks 隧道（仅作用于 X 请求）。"""
    global _PROXY_CFG
    if not _PROXY_CFG or _PROXY_CFG['type'] != 'socks':
        return
    if not HAS_SOCKS:
        raise RuntimeError('未安装 PySocks，无法使用 SOCKS 代理，请先 pip install pysocks')
    stype = {'socks5': _socks_mod.SOCKS5,
             'socks5h': _socks_mod.SOCKS5,
             'socks4': _socks_mod.SOCKS4}[_PROXY_CFG['scheme']]
    _socks_mod.set_default_proxy(
        stype, _PROXY_CFG['host'], _PROXY_CFG['port'],
        rdns=(_PROXY_CFG['scheme'] == 'socks5h'))
    socket.socket = _socks_mod.socksocket


def _restore_socks():
    global _PROXY_CFG
    if _PROXY_CFG and _PROXY_CFG['type'] == 'socks':
        socket.socket = _ORIG_SOCKET


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
            if e.code in (400, 404):
                return None
            time.sleep(2)
        except Exception:
            time.sleep(2)


# ---------------- 入库通知 ----------------
def notify_input(input_ctx, files):
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


# ---------------- 网络请求封装 ----------------
def fetch_text(url, opener, headers, timeout=60):
    _apply_socks()
    try:
        req = urllib.request.Request(url, headers=headers)
        with opener.open(req, timeout=timeout) as r:
            return r.read().decode('utf-8', 'replace')
    finally:
        _restore_socks()


def fetch_bytes(url, opener, headers, timeout=60):
    _apply_socks()
    try:
        req = urllib.request.Request(url, headers=headers)
        with opener.open(req, timeout=timeout) as r:
            return r.read()
    finally:
        _restore_socks()


# ---------------- 媒体解析 ----------------
def build_headers(cookie_header):
    h = {'User-Agent': UA, 'Accept': '*/*'}
    if cookie_header:
        h['Cookie'] = cookie_header
    return h


def extract_from_html(html, cookie_header):
    """从推文页面 HTML 中正则抓取图片原图与视频 m3u8。"""
    media = []
    seen_img = set()
    for m in IMG_RE.finditer(html):
        base = m.group(0)
        if base in seen_img:
            continue
        seen_img.add(base)
        orig = base + '?name=orig'
        media.append({'type': 'image', 'url': orig, 'label': '图片'})
    m3u8_urls = [m.group(0) for m in M3U8_RE.finditer(html)]
    if m3u8_urls:
        best = pick_m3u8(m3u8_urls)
        media.append({'type': 'video', 'url': best, 'label': '视频/动图'})
    return media


def pick_m3u8(urls):
    """优先选具体分辨率的分片列表（含 /vid/WxH/），否则取第一个。"""
    for u in urls:
        if RENDITION_RE.search(u):
            return u
    return urls[0]


def get_guest_token(opener, cookie_header):
    """通过 api.x.com 访客接口换取 guest_token（仅用于接口鉴权降级）。"""
    url = 'https://api.x.com/1.1/guest/activate.json'
    headers = {
        'User-Agent': UA,
        'Authorization': f'Bearer {WEB_BEARER}',
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    if cookie_header:
        headers['Cookie'] = cookie_header
    try:
        req = urllib.request.Request(url, data=b'', headers=headers, method='POST')
        with opener.open(req, timeout=30) as r:
            data = json.loads(r.read().decode('utf-8', 'replace'))
        return data.get('guest_token')
    except Exception as e:
        log(f'获取 guest_token 失败（将仅用页面解析）: {e}', level='warn')
        return None


def extract_from_api(tweet_id, cookie_header, opener):
    """调用 statuses/show.json 接口（结构化数据，最可靠），失败返回 []。"""
    gt = get_guest_token(opener, cookie_header)
    if not gt:
        return []
    url = (f'https://api.x.com/1.1/statuses/show.json'
           f'?id={tweet_id}&tweet_mode=extended')
    headers = {
        'User-Agent': UA,
        'Authorization': f'Bearer {WEB_BEARER}',
        'x-guest-token': gt,
        'Cookie': cookie_header or '',
    }
    try:
        data = json.loads(fetch_text(url, opener, headers, timeout=40))
    except Exception as e:
        log(f'接口解析失败（将仅用页面解析）: {e}', level='warn')
        return []
    media = []
    entities = data.get('extended_entities') or data.get('entities') or {}
    for ent in entities.get('media', []):
        mtype = ent.get('type')
        if mtype == 'photo':
            base = ent.get('media_url_https') or ent.get('media_url') or ''
            if base:
                media.append({'type': 'image',
                              'url': base + ':orig',
                              'label': '图片'})
        elif mtype in ('video', 'animated_gif'):
            variants = ent.get('video_info', {}).get('variants', [])
            m3u8 = [v['url'] for v in variants
                    if v.get('content_type') == 'application/x-mpegURL']
            if m3u8:
                media.append({'type': 'video',
                              'url': pick_m3u8(m3u8),
                              'label': '视频/动图'})
    return media


def extract_media(url, cookie_header, proxy_cfg):
    """解析推文，返回媒体列表：[{type:'image'|'video', url, label}]。

    策略：优先页面 HTML 解析（无需 Bearer，直接用用户 Cookie）；
          若页面未解析到，则用 statuses/show.json 接口降级补全。
    """
    opener = make_opener(proxy_cfg)
    headers = build_headers(cookie_header)
    tweet_id = (re.search(r'/status/(\d+)', url) or [None, 'x'])[1]

    log('正在抓取推文页面…')
    html = None
    try:
        html = fetch_text(url, opener, headers, timeout=45)
    except Exception as e:
        log(f'页面抓取失败: {e}', level='warn')

    media = extract_from_html(html, cookie_header) if html else []
    if not media and tweet_id != 'x':
        log('页面未解析到媒体，尝试接口方式…')
        media = extract_from_api(tweet_id, cookie_header, opener)
    return media


# ---------------- 下载 ----------------
def download_image(url, cookie_header, working_dir, index, proxy_cfg):
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1] or '.jpg'
    ext = ext if ext.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp') else '.jpg'
    dest = os.path.join(working_dir, f'x_media_{index}{ext}')
    headers = {'User-Agent': UA}
    if cookie_header:
        headers['Cookie'] = cookie_header
    opener = make_opener(proxy_cfg)
    data = fetch_bytes(url, opener, headers, timeout=90)
    with open(dest, 'wb') as f:
        f.write(data)
    return dest


def parse_m3u8_segments(m3u8_text, base_url):
    """从 m3u8 文本中提取分片 URL 列表（解析相对地址）。"""
    segments = []
    for line in m3u8_text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('http://') or line.startswith('https://'):
            segments.append(line)
        else:
            segments.append(urllib.parse.urljoin(base_url, line))
    return segments


def resolve_rendition(m3u8_url, opener, headers):
    """若是 master  playlist（含 STREAM-INF），选最高分辨率 rendition。"""
    text = fetch_text(m3u8_url, opener, headers, timeout=45)
    if '#EXT-X-STREAM-INF' not in text:
        return m3u8_url, text
    best = None
    best_w = -1
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith('#EXT-X-STREAM-INF'):
            m = re.search(r'RESOLUTION=(\d+)x(\d+)', line)
            w = int(m.group(1)) if m else 0
            # 下一行是对应 URL
            uri = lines[i + 1].strip() if i + 1 < len(lines) else ''
            if uri and w >= best_w:
                best_w = w
                best = uri
    if best:
        best = urllib.parse.urljoin(m3u8_url, best)
        return best, fetch_text(best, opener, headers, timeout=45)
    return m3u8_url, text


def download_video(m3u8_url, cookie_header, working_dir, tweet_id, proxy_cfg):
    opener = make_opener(proxy_cfg)
    headers = build_headers(cookie_header)
    log('解析视频播放列表（m3u8）…')
    rendition_url, text = resolve_rendition(m3u8_url, opener, headers)
    segments = parse_m3u8_segments(text, rendition_url)
    if not segments:
        raise RuntimeError('未从 m3u8 中解析到任何视频分片')
    # 检测加密（暂不处理 EXT-X-KEY，仅告警）
    if '#EXT-X-KEY' in text:
        log('检测到加密分片（EXT-X-KEY），合并可能失败', level='warn')

    n = len(segments)
    log(f'共 {n} 个分片，开始下载…')
    seg_files = []
    for i, seg_url in enumerate(segments, start=1):
        seg_path = os.path.join(working_dir, f'seg_{i:04d}.ts')
        data = fetch_bytes(seg_url, opener, headers, timeout=90)
        with open(seg_path, 'wb') as f:
            f.write(data)
        seg_files.append(seg_path)
        if i % 5 == 0 or i == n:
            log(f'分片 {i}/{n}')

    # 用 ffmpeg 合并
    out_path = os.path.join(working_dir, f'{tweet_id}.mp4')
    list_path = os.path.join(working_dir, 'segments.txt')
    with open(list_path, 'w', encoding='utf-8') as f:
        for s in seg_files:
            f.write(f"file '{os.path.abspath(s)}'\n")
    cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0',
           '-i', list_path, '-c', 'copy', out_path]
    log('用 ffmpeg 合并分片…')
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError('ffmpeg 合并失败: ' + (proc.stderr or '')[:500])
    return out_path


def simulate_media():
    """演示用：合成 3 个媒体（2 图 + 1 视频），用于体现“二次选择”交互。"""
    return [
        {'type': 'image', 'url': 'https://pbs.twimg.com/demo/1.jpg', 'label': '图片 1（演示）'},
        {'type': 'image', 'url': 'https://pbs.twimg.com/demo/2.jpg', 'label': '图片 2（演示）'},
        {'type': 'video', 'url': 'https://video.twimg.com/demo/playlist.m3u8', 'label': '视频（演示）'},
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
    proxy_cfg = parse_proxy(params.get('proxy'))
    global _PROXY_CFG
    _PROXY_CFG = proxy_cfg
    if proxy_cfg:
        kind = proxy_cfg['type']
        if kind == 'http':
            log(f'使用 HTTP 代理访问 X: {proxy_cfg["addr"]}')
        else:
            log(f'使用 SOCKS 代理访问 X: {proxy_cfg["scheme"]}://{proxy_cfg["host"]}:{proxy_cfg["port"]}')

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
            media = extract_media(url, cookie_header, proxy_cfg)
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
                    path = download_image(item['url'], cookie_header, working_dir, idx, proxy_cfg)
                downloaded.append({'path': path, 'type': 'image'})
                log(f'已下载图片: {os.path.basename(path)}')
            else:
                if simulate:
                    path = write_sim_placeholder(working_dir, idx, 'video')
                else:
                    path = download_video(item['url'], cookie_header, working_dir, tweet_id, proxy_cfg)
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
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)
    main()
