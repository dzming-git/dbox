# -*- coding: utf-8 -*-
"""IPlatformAPI 契约的 HTTP 客户端实现（扩展宿主侧调用主 Web 服务）。

扩展宿主（extensions_host）不直接 import 主模块的任何业务逻辑，
仅通过本客户端以 HTTP 调用主服务暴露的 IPlatformAPI 内部接口
（/internal/*，仅本机 127.0.0.1 可达）。

这是扩展宿主与主模块之间唯一的「反向调用」通道，方向单向、契约稳定。
"""
import os
import json
import time
import uuid
import logging
import urllib.request
from datetime import datetime
from urllib.parse import urlencode

logger = logging.getLogger('dbox-ext-platform')

# 建单重试 / 本地 spool 兜底参数
_FB_MAX_RETRIES = 3          # 主服务瞬时不可达时的重试次数
_FB_RETRY_BASE = 0.5         # 重试退避基线（秒），第 n 次等待 n*base

# 主服务内部契约接口地址（默认本机 8080）
_PLATFORM_HOST = os.environ.get('DBOX_WEB_HOST', '127.0.0.1')
_PLATFORM_PORT = int(os.environ.get('DBOX_WEB_PORT', '8080'))


def _runtime_data_dirs():
    """主服务实际写入数据的运行时目录候选（与 web 端 get_runtime_dir 同口径）。

    生产部署里主服务常通过 DBOX_DATA_DIR 把数据落到独立于代码树的目录
    （如 Windows 的 %ProgramData%\\Dbox\\data），而拓展宿主进程的启动环境未必带
    DBOX_DATA_DIR，若仍按“本包向上两级=项目根”去读内部密钥，就会读空导致 401。
    这里显式补上生产运行时目录候选，使两端总能找到同一份内部密钥。
    """
    dirs = []
    prog = os.environ.get('ProgramData')      # Windows: C:\ProgramData
    if prog:
        dirs.append(os.path.join(prog, 'Dbox', 'data'))
    dirs.append(os.path.join('/var', 'lib', 'dbox', 'data'))   # Linux 生产
    dirs.append(os.path.join('/opt', 'dbox', 'data'))
    return dirs


def _internal_key_path():
    """定位主服务写入的进程间共享内部密钥（与 internal_api 同文件）。

    两端必须能找到同一份密钥文件，否则 /internal/* 调用会被 401 拒绝，进而使
    「AI 处理完成却无法在反馈中心落单」这类静默失败。解析优先级：
      1. 显式环境变量 DBOX_DATA_DIR（两端应一致设置）；
      2. 生产运行时数据目录（见 _runtime_data_dirs，首个存在的即采用）；
      3. 开发态兜底：本包向上两级为项目根 data/。
    """
    env = os.environ.get('DBOX_DATA_DIR')
    if env:
        return os.path.join(env, '.dbox_internal_key')
    for cand in _runtime_data_dirs():
        p = os.path.join(cand, '.dbox_internal_key')
        if os.path.exists(p):
            return p
    # 开发态兜底：本包在 src/extensions_host，向上两级为项目根 (dbox)
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    return os.path.join(root, 'data', '.dbox_internal_key')


def _internal_secret() -> str:
    """读取主服务写入的进程间共享内部密钥（与 internal_api 同文件）。"""
    try:
        with open(_internal_key_path(), 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        # 兜底：若密钥文件尚未生成（主服务未启动），用空串，请求会被 401 拒绝
        return ''


def _post(path: str, payload: dict) -> dict:
    url = f'http://{_PLATFORM_HOST}:{_PLATFORM_PORT}/internal{path}'
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        url, data=data, method='POST',
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'X-Dbox-Internal': _internal_secret(),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode('utf-8')
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        # 服务端已返回响应（401/403/4xx/5xx）：属于鉴权/业务错误，非网络层故障，
        # 重试无意义、也不应落 spool 无限重试，交由调用方按“硬失败”处理。
        return {'success': False,
                'message': f'平台调用失败: HTTP Error {e.code}: {e.reason}',
                'network_error': False}
    except Exception as e:
        # 连接被拒 / 超时 / 解析失败等网络层错误：瞬时可达性问题，可重试或落 spool。
        logger.error('调用主服务 IPlatformAPI 失败 %s: %s', path, e)
        return {'success': False, 'message': f'平台调用失败: {e}',
                'network_error': True}


def _get(path: str, params: dict = None) -> dict:
    url = f'http://{_PLATFORM_HOST}:{_PLATFORM_PORT}/internal{path}'
    if params:
        url += '?' + urlencode(params)
    req = urllib.request.Request(
        url, method='GET',
        headers={'X-Dbox-Internal': _internal_secret()},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode('utf-8')
            return json.loads(body) if body else {}
    except Exception as e:
        logger.error('调用主服务 IPlatformAPI 失败 %s: %s', path, e)
        return {'success': False, 'message': f'平台调用失败: {e}'}


def ingest_file(library_id, path, kind=None, modes=('video',),
                collection_id=None, meta=None, user_id=None, hidden=False) -> dict:
    """请求主服务把文件/目录登记入库，并按 modes 归属模式。"""
    return _post('/ingest', {
        'library_id': library_id,
        'path': path,
        'kind': kind,
        'modes': list(modes),
        'collection_id': collection_id,
        'meta': meta,
        'user_id': user_id,
        'hidden': bool(hidden),
    })


def get_allowed_library_ids(user_id: int) -> list:
    """获取指定用户被允许写入的资源库 ID 列表。"""
    r = _get('/allowed-libraries', {'user_id': user_id})
    return r.get('library_ids', []) if isinstance(r, dict) else []


def notify_job_done(job_id, result: dict) -> dict:
    """通知主服务某个脚本任务已完成（用于联动业务逻辑，如清理临时态）。"""
    return _post('/job-done', {'job_id': job_id, 'result': result or {}})


def library_disk_targets(library_id: int) -> list:
    """获取某资源库在磁盘上的监控根目录列表（供脚本 run 时确定落盘位置）。"""
    r = _get('/library-targets', {'library_id': library_id})
    return r.get('targets', []) if isinstance(r, dict) else []


def upsert_post_by_group(group_key, title=None, content='', resource_index_ids=None,
                         user_id=None, display_modes=None, author_name=None,
                         author_url=None, source_url=None) -> dict:
    """按 group_key 创建/更新帖子（供 X 下载脚本在入库后生成帖子）。"""
    return _post('/upsert-post', {
        'group_key': group_key,
        'title': title,
        'content': content,
        'resource_index_ids': resource_index_ids or [],
        'user_id': user_id,
        'display_modes': display_modes,
        'author_name': author_name,
        'author_url': author_url,
        'source_url': source_url,
    })


def resource_resolve(type_: str, ref: str) -> dict:
    """解析 AI 回复中的资源引用（type, ref）为可跳转详情页路径与封面。"""
    return _post('/resource-resolve', {'type': type_, 'ref': ref})


def _feedback_spool_dir() -> str:
    """本地反馈建单的持久化兜底目录（主服务不可达时暂存，待恢复后重放）。

    与主服务共用同一数据区（DBOX_DATA_DIR 或项目 data/），确保宿主进程即便在主服务
    暂时离线时也能把建单意图落盘，避免「AI 处理完成却没单可跟踪」的静默丢单。
    """
    env = os.environ.get('DBOX_DATA_DIR')
    if env:
        base = env
    else:
        # 本包在 src/extensions_host，向上两级为项目根 (dbox)
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.dirname(os.path.dirname(here))
        base = os.path.join(root, 'data')
    d = os.path.join(base, 'feedback_spool')
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def _write_spool(payload: dict) -> str:
    """把一条建单请求持久化到本地 spool，返回文件名；失败返回空串。"""
    d = _feedback_spool_dir()
    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    name = 'fb_%s_%s.json' % (ts, uuid.uuid4().hex[:8])
    path = os.path.join(d, name)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        return name
    except Exception as e:
        logger.error('写入反馈 spool 失败: %s', e)
        return ''


def flush_feedback_spool() -> list:
    """重放本地 spool 中暂存的建单请求，成功即删除对应文件。

    应在宿主进程启动、以及主服务恢复后的周期任务中调用，从而把离线期间积压的
    「AI 处理跟踪单 / 用户反馈单」最终落到反馈中心。返回本次成功创建的 issue_id 列表。
    """
    d = _feedback_spool_dir()
    created = []
    try:
        names = sorted(os.listdir(d))
    except Exception:
        return created
    for name in names:
        if not (name.startswith('fb_') and name.endswith('.json')):
            continue
        path = os.path.join(d, name)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        except Exception:
            # 损坏的 spool 文件直接丢弃，避免永久卡住重放
            try:
                os.remove(path)
            except Exception:
                pass
            continue
        r = _post('/feedback', payload)
        if isinstance(r, dict) and r.get('success') and r.get('issue_id'):
            try:
                os.remove(path)
            except Exception:
                pass
            created.append(r['issue_id'])
        # 失败（含主服务仍不可达）则保留文件，下次重试
    return created


def file_feedback(ftype: str, title: str, content: str, extra: dict = None,
                  status: str = 'open'):
    """在反馈中心建一条反馈单，返回新单号；失败返回 None。

    extra / status 用于 AI 助手处理完成后的「跟踪单」：传入提交哈希与
    pending_verification 状态，便于反馈中心展示「待验证」并关联处理动作。

    结构上保证不丢单：主服务瞬时不可达时自动重试若干次；若仍失败（连接类错误），
    则把建单意图落本地 spool（flush_feedback_spool 会在主服务恢复后重放），
    不再静默丢失——这正是「AI 处理必有反馈中心单跟踪」的兜底保障。
    """
    payload = {'type': ftype, 'title': title, 'content': content,
               'extra': extra, 'status': status}
    network_err = None
    for attempt in range(_FB_MAX_RETRIES):
        try:
            r = _post('/feedback', payload)
        except Exception as e:   # 极端情况下 _post 未吞掉的异常，同样视为网络错误
            r = None
            network_err = str(e)
        if isinstance(r, dict) and r.get('success') and r.get('issue_id'):
            return r['issue_id']
        net = bool(r.get('network_error')) if isinstance(r, dict) else True
        msg = (r.get('message') if isinstance(r, dict) else '') or ''
        if net:
            # 真正的网络/连接层错误：退避重试，最终落 spool 待主服务恢复后重放
            network_err = msg or network_err or '网络层错误'
            if attempt < _FB_MAX_RETRIES - 1:
                time.sleep(_FB_RETRY_BASE * (attempt + 1))
                continue
        else:
            # 鉴权/校验/业务错误（如 401 密钥不匹配、内容为空）：不会因重试恢复，
            # 明确失败并告警，避免静默丢单或无限重试。
            logger.error('反馈中心建单被拒（非网络错误，不重试）：%s', msg)
            return None
    # 仅连接类失败才落 spool：保证 AI 处理跟踪单在离线期间不丢，恢复后自动建单
    if network_err:
        sp = _write_spool(payload)
        if sp:
            logger.warning('反馈中心建单失败（主服务暂不可达），已落本地 spool 待重放：'
                           '%s（%s）', sp, network_err)
        else:
            logger.error('反馈中心建单失败且无法写入 spool：%s', network_err)
    return None


def allowed_libraries(user_id: int = None) -> list:
    """返回某用户可写入的资源库 ID 列表。"""
    r = _get('/allowed-libraries', {'user_id': user_id})
    return r.get('library_ids', []) if isinstance(r, dict) else []
