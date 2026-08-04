"""通用事件监听器框架（可提交到 git）。

框架职责：
- 轮询反馈独立数据库（feedback.db），将反馈状态变化识别为事件：
    * feedback.new      —— 新增的反馈（首次被监听器发现，status=open）
    * feedback.reopened —— 曾被处理、又被重新打开（status 从非 open 变回 open）
- 当事件发生时，按用户配置文件调用 handler 脚本（外部进程）。
  handler 脚本本身与监听器配置都属于「用户本地数据」，不纳入 git
  （见 .gitignore 的 scripts/event_listener/ 相关规则），
  因此可以自由扩展、包含本地路径或个人逻辑，而不会污染仓库。

handler 调用约定（用户可自由配置）：
- 用户在 event_listener_config.json 中声明「事件 -> 一个或多个脚本」映射，
  并可为每个脚本指定命令行参数模板。
- 框架始终通过环境变量注入事件上下文（handler 可用任意一种方式读取）：
    EVENT_NAME      事件名
    EVENT_PAYLOAD   JSON 字符串（含 issue 字典及事件元信息）
    DBOX_ROOT       项目根目录
- 若脚本未显式指定参数，框架默认追加： --event <事件名> --payload <JSON>
  （与旧的硬编码约定保持一致，便于存量脚本平滑迁移）。
- handler 退出码非 0 视为处理失败，框架会标记该事件待重试（限次）。

事件监听器配置文件（event_listener_config.json）示例：
{
  "interval": 30,
  "events": {
    "feedback.new": [
      {"script": "handlers/feedback_processor.py", "args": []},
      {"script": "C:/Users/me/scripts/notify.ps1", "args": ["--event", "{EVENT}", "--id", "{ISSUE_ID}"]}
    ],
    "feedback.reopened": [
      {"script": "handlers/feedback_processor.py", "args": []}
    ]
  }
}

参数模板占位符（在 args 中可用，框架会替换后传入脚本）：
  {EVENT}      事件名
  {ISSUE_ID}   反馈 ID
  {ISSUE_JSON} 整个 issue 的 JSON 字符串（单行）

用法：
    python scripts/event_listener/listener.py            # 循环监听
    python scripts/event_listener/listener.py --once     # 只扫描一次
    python scripts/event_listener/listener.py --interval 60
    python scripts/event_listener/listener.py --dry-run  # 只打印将触发的事件与命令，不调用 handler
"""
import os
import sys
import io
import json
import time
import argparse
import subprocess
import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DBOX_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
HANDLERS_DIR = os.path.join(SCRIPT_DIR, 'handlers')
STATE_PATH = os.path.join(SCRIPT_DIR, '.listener_state.json')
LOG_PATH = os.path.join(SCRIPT_DIR, '.listener.log')
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'event_listener_config.json')

# 默认事件 -> handler 列表（当配置文件不存在时使用，保持旧行为可运行）
DEFAULT_CONFIG = {
    'interval': 30,
    'events': {
        'feedback.new': [
            {'script': 'handlers/feedback_processor.py', 'args': []},
        ],
        'feedback.reopened': [
            {'script': 'handlers/feedback_processor.py', 'args': []},
        ],
    },
}

# 单条事件最大重试次数
MAX_RETRIES = 3
# 派发后超过该分钟数仍未处理则视为 stale（用于重启后兜底）
STALE_MINUTES = 60


class _Tee(io.TextIOBase):
    """将输出同时写到原始流与日志文件，用于持久化监听器日志。"""

    def __init__(self, original, log_file):
        self._original = original
        self._log_file = log_file

    def write(self, s):
        try:
            self._original.write(s)
        except Exception:
            pass
        try:
            self._log_file.write(s)
            self._log_file.flush()
        except Exception:
            pass
        return len(s)

    def flush(self):
        try:
            self._original.flush()
        except Exception:
            pass
        try:
            self._log_file.flush()
        except Exception:
            pass


def setup_logging():
    """把 stdout/stderr 重定向到控制台 + .listener.log，行首带时间戳。"""
    logf = open(LOG_PATH, 'a', encoding='utf-8')
    orig_out, orig_err = sys.stdout, sys.stderr

    class _TSWriter:
        def __init__(self, raw, ts=True):
            self._raw = raw
            self._ts = ts
            self._buf = ''

        def write(self, s):
            # 仅在行首补时间戳
            text = self._buf + s
            out_lines = text.split('\n')
            self._buf = out_lines.pop()  # 末尾未换行部分暂存
            now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for ln in out_lines:
                if ln == '':
                    self._raw.write('\n')
                    continue
                prefix = f'[{now}] ' if self._ts else ''
                self._raw.write(prefix + ln + '\n')
            return len(s)

        def flush(self):
            self._raw.flush()

    sys.stdout = _Tee(_TSWriter(orig_out), logf)
    sys.stderr = _Tee(_TSWriter(orig_err), logf)


# 让脚本能 import 到 src/web 下的 backend 模块
WEB_DIR = os.path.join(DBOX_ROOT, 'src', 'web')
if WEB_DIR not in sys.path:
    sys.path.insert(0, WEB_DIR)

from backend.feedback_db import init_feedback_db, get_session, FeedbackIssue  # noqa: E402


def load_config():
    """读取用户配置文件；文件不存在时回退到默认配置。

    返回 (config, source)，source 为 'user' 或 'default'。
    """
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            print(f"[listener] 已加载用户配置: {CONFIG_PATH}")
            return cfg, 'user'
        except Exception as e:
            print(f"[listener] 配置文件解析失败，使用默认配置: {e}")
    else:
        print(f"[listener] 未找到配置文件 {CONFIG_PATH}，使用内置默认配置（仅反馈事件）")
    return DEFAULT_CONFIG, 'default'


def resolve_handlers(event_name, config):
    """返回事件对应的 handler 列表（含 script / args 模板）。"""
    events = config.get('events', {})
    handlers = events.get(event_name, [])
    # 兼容旧式：handler 可能是纯字符串（脚本名）
    normalized = []
    for h in handlers:
        if isinstance(h, str):
            normalized.append({'script': h, 'args': []})
        else:
            normalized.append({
                'script': h.get('script', ''),
                'args': h.get('args', []) or [],
            })
    return normalized


def render_args(args_template, event_name, issue):
    """把参数模板中的占位符替换为实际值。

    占位符：
      {EVENT}      事件名
      {ISSUE_ID}   反馈 ID
      {ISSUE_JSON} issue 的 JSON 字符串（单行）
    """
    issue_id = issue.get('id', '')
    issue_json = json.dumps(issue, ensure_ascii=False)
    repl = {
        '{EVENT}': event_name,
        '{ISSUE_ID}': str(issue_id),
        '{ISSUE_JSON}': issue_json,
    }
    out = []
    for a in args_template:
        if a in repl:
            out.append(repl[a])
        else:
            out.append(a)
    return out


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'seen': {}, 'pid': os.getpid()}


def save_state(state):
    state['pid'] = os.getpid()
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def issue_to_dict(issue):
    d = {}
    for col in ('id', 'title', 'content', 'status', 'category',
                'submitter', 'source', 'created_at', 'updated_at'):
        v = getattr(issue, col, None)
        if hasattr(v, 'isoformat'):
            v = v.isoformat()
        d[col] = v
    return d


def fetch_all_issues():
    init_feedback_db()
    out = []
    with get_session() as session:
        for issue in session.query(FeedbackIssue).all():
            out.append(issue_to_dict(issue))
    return out


def call_handler(event_name, issue, handler, dry_run=False):
    script = handler.get('script', '')
    if not script:
        print(f"[listener] handler 缺少 script 字段，跳过")
        return True

    # 解析脚本绝对路径：相对 handlers 目录或 handlers 下的相对路径；否则按原样（绝对/相对 cwd）
    if os.path.isabs(script):
        hpath = script
    else:
        candidate = os.path.join(HANDLERS_DIR, script)
        if os.path.exists(candidate):
            hpath = candidate
        else:
            # 允许直接写 handlers 子目录内的文件名
            alt = os.path.join(SCRIPT_DIR, script)
            hpath = alt if os.path.exists(alt) else candidate

    if not os.path.exists(hpath):
        print(f"[listener] handler 不存在: {hpath}，跳过")
        return True

    # 命令行参数：用户模板 + 若用户未指定任何参数则追加默认 --event/--payload
    args_template = handler.get('args', []) or []
    rendered = render_args(args_template, event_name, issue)
    if not rendered:
        rendered = ['--event', event_name, '--payload', json.dumps(issue, ensure_ascii=False)]

    payload = {'event': event_name, 'issue': issue}
    payload_str = json.dumps(payload, ensure_ascii=False)

    env = dict(os.environ)
    env['EVENT_NAME'] = event_name
    env['EVENT_PAYLOAD'] = payload_str
    env['DBOX_ROOT'] = DBOX_ROOT

    print(f"[listener] 触发 handler: {script} (event={event_name}, issue={issue.get('id')})")
    if dry_run:
        print(f"[listener][dry-run] 命令: {sys.executable} {hpath} {' '.join(rendered)}")
        print(f"[listener][dry-run] 环境变量 EVENT_NAME={event_name}")
        return True

    try:
        proc = subprocess.run(
            [sys.executable, hpath] + rendered,
            cwd=DBOX_ROOT, env=env,
            capture_output=True, text=True, timeout=3600,
        )
        if proc.stdout:
            print(f"[listener][{script}/stdout] {proc.stdout.strip()}")
        if proc.stderr:
            print(f"[listener][{script}/stderr] {proc.stderr.strip()}")
        if proc.returncode != 0:
            print(f"[listener] handler {script} 退出码 {proc.returncode}（失败）")
            return False
    except subprocess.TimeoutExpired:
        print(f"[listener] handler {script} 超时（>3600s）")
        return False
    except Exception as e:
        print(f"[listener] 调用 handler {script} 异常: {e}")
        return False
    return True


def sweep(dry_run=False):
    state = load_state()
    now = time.time()
    config, _ = load_config()

    issues = fetch_all_issues()
    # 建立 id -> issue 映射与当前 open 集合
    by_id = {i['id']: i for i in issues}
    open_ids = {i['id'] for i in issues if i['status'] == 'open'}

    # 1) 检测新增 / 重新打开
    triggered = []
    for iid, issue in by_id.items():
        prev = state['seen'].get(iid)
        is_open = iid in open_ids
        if prev is None:
            # 首次出现
            if is_open:
                triggered.append(('feedback.new', issue))
                state['seen'][iid] = {'status': issue['status'], 'ts': now, 'retries': 0}
            else:
                # 非 open 的历史反馈，仅登记不触发
                state['seen'][iid] = {'status': issue['status'], 'ts': now, 'retries': 0}
        else:
            prev_open = prev.get('status') == 'open'
            if not prev_open and is_open:
                # 从非 open 变回 open => 重新打开
                triggered.append(('feedback.reopened', issue))
                state['seen'][iid] = {'status': issue['status'], 'ts': now, 'retries': 0}
            else:
                # 状态未变回 open，仅更新记录
                state['seen'][iid] = {'status': issue['status'], 'ts': now,
                                      'retries': prev.get('retries', 0)}

    for event_name, issue in triggered:
        handlers = resolve_handlers(event_name, config)
        if not handlers:
            print(f"[listener] 事件 {event_name} 无 handler 配置，跳过")
            continue
        for handler in handlers:
            ok = call_handler(event_name, issue, handler, dry_run=dry_run)
            if not ok and not dry_run:
                rec = state['seen'].get(issue['id'], {})
                rec['retries'] = rec.get('retries', 0) + 1
                if rec['retries'] >= MAX_RETRIES:
                    print(f"[listener] {issue['id']} 重试 {MAX_RETRIES} 次仍失败，放弃")
                state['seen'][issue['id']] = rec

    # 2) 清理已删除的反馈记录
    for iid in list(state['seen'].keys()):
        if iid not in by_id:
            del state['seen'][iid]

    save_state(state)


def main():
    parser = argparse.ArgumentParser(description='通用事件监听器')
    parser.add_argument('--once', action='store_true', help='只扫描一次')
    parser.add_argument('--interval', type=int, default=None, help='轮询间隔秒数（覆盖配置）')
    parser.add_argument('--dry-run', action='store_true', help='只打印将触发的事件与命令，不调用 handler')
    args = parser.parse_args()

    setup_logging()
    # 立即把当前进程 pid 写入 state，确保管理后台能在启动瞬间判定为「运行中」
    save_state(load_state())
    config, source = load_config()
    interval = args.interval if args.interval else config.get('interval', 30)
    print(f"[listener] 启动，dbox={DBOX_ROOT}，handlers={HANDLERS_DIR}，interval={interval}s，dry_run={args.dry_run}，config={source}")
    print(f"[listener] 日志写入: {LOG_PATH}")

    if args.once:
        sweep(dry_run=args.dry_run)
        return
    try:
        while True:
            sweep(dry_run=args.dry_run)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("[listener] 被中断，退出。")


if __name__ == '__main__':
    main()
