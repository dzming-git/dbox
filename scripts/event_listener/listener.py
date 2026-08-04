"""通用事件监听器框架（可提交到 git）。

框架职责：
- 轮询反馈独立数据库（feedback.db），将反馈状态变化识别为事件：
    * feedback.new      —— 新增的反馈（首次被监听器发现，status=open）
    * feedback.reopened —— 曾被处理、又被重新打开（status 从非 open 变回 open）
- 当事件发生时，调用 handlers/ 目录下用户自定义的 handler 脚本（外部进程）。
  handler 脚本本身不纳入 git（见 .gitignore 的 scripts/event_listener/handlers/ 规则），
  因此可以自由扩展、包含本地路径或个人逻辑，而不会污染仓库。

handler 调用约定：
- 以子进程方式执行：python <handler> --event <event_name> --payload <json>
- 框架通过环境变量注入：
    EVENT_NAME      事件名
    EVENT_PAYLOAD   JSON 字符串（含 issue 字典及事件元信息）
    DBOX_ROOT       项目根目录
- handler 的 stdout/stderr 会被框架记录到日志。
- handler 退出码非 0 视为处理失败，框架会标记该事件待重试（限次）。

用法：
    python scripts/event_listener/listener.py            # 循环监听
    python scripts/event_listener/listener.py --once     # 只扫描一次
    python scripts/event_listener/listener.py --interval 60
    python scripts/event_listener/listener.py --dry-run  # 只打印将触发的事件，不调用 handler
"""
import os
import sys
import json
import time
import argparse
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DBOX_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
HANDLERS_DIR = os.path.join(SCRIPT_DIR, 'handlers')
STATE_PATH = os.path.join(SCRIPT_DIR, '.listener_state.json')

# 让脚本能 import 到 src/web 下的 backend 模块
WEB_DIR = os.path.join(DBOX_ROOT, 'src', 'web')
if WEB_DIR not in sys.path:
    sys.path.insert(0, WEB_DIR)

from backend.feedback_db import init_feedback_db, get_session, FeedbackIssue  # noqa: E402

# 事件 -> 关注的 handler 文件名（一个事件可触发多个 handler，按顺序执行）
EVENT_HANDLERS = {
    'feedback.new': ['feedback_processor.py'],
    'feedback.reopened': ['feedback_processor.py'],
}

# 单条事件最大重试次数
MAX_RETRIES = 3
# 派发后超过该分钟数仍未处理则视为 stale（用于重启后兜底）
STALE_MINUTES = 60


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


def call_handler(event_name, payload, dry_run=False):
    handlers = EVENT_HANDLERS.get(event_name, [])
    if not handlers:
        print(f"[listener] 事件 {event_name} 无对应 handler，跳过")
        return True
    payload_str = json.dumps(payload, ensure_ascii=False)
    for h in handlers:
        hpath = os.path.join(HANDLERS_DIR, h)
        if not os.path.exists(hpath):
            print(f"[listener] handler 不存在: {hpath}，跳过")
            continue
        env = dict(os.environ)
        env['EVENT_NAME'] = event_name
        env['EVENT_PAYLOAD'] = payload_str
        env['DBOX_ROOT'] = DBOX_ROOT
        cmd = [sys.executable, hpath]
        print(f"[listener] 触发 handler: {h} (event={event_name}, issue={payload.get('issue', {}).get('id')})")
        if dry_run:
            print(f"[listener][dry-run] 命令: {' '.join(cmd)}")
            print(f"[listener][dry-run] 环境变量 EVENT_NAME={event_name}")
            continue
        try:
            proc = subprocess.run(cmd, cwd=DBOX_ROOT, env=env,
                                  capture_output=True, text=True, timeout=3600)
            if proc.stdout:
                print(f"[listener][{h}/stdout] {proc.stdout.strip()}")
            if proc.stderr:
                print(f"[listener][{h}/stderr] {proc.stderr.strip()}")
            if proc.returncode != 0:
                print(f"[listener] handler {h} 退出码 {proc.returncode}（失败）")
                return False
        except subprocess.TimeoutExpired:
            print(f"[listener] handler {h} 超时（>3600s）")
            return False
        except Exception as e:
            print(f"[listener] 调用 handler {h} 异常: {e}")
            return False
    return True


def sweep(dry_run=False):
    state = load_state()
    now = time.time()

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
        ok = call_handler(event_name, {'event': event_name, 'issue': issue}, dry_run=dry_run)
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
    parser.add_argument('--interval', type=int, default=30, help='轮询间隔秒数')
    parser.add_argument('--dry-run', action='store_true', help='只打印将触发的事件，不调用 handler')
    args = parser.parse_args()

    print(f"[listener] 启动，dbox={DBOX_ROOT}，handlers={HANDLERS_DIR}，interval={args.interval}s，dry_run={args.dry_run}")

    if args.once:
        sweep(dry_run=args.dry_run)
        return
    try:
        while True:
            sweep(dry_run=args.dry_run)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("[listener] 被中断，退出。")


if __name__ == '__main__':
    main()
