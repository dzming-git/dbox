"""通用事件监听器框架（可提交到 git）。

设计要点（高自由度）：
- 事件由各个服务模块自行在「事件注册中心」注册（见 src/web/core/event_registry.py），
  监听器不硬编码任何具体事件。
- 每个事件声明一个「状态探针 probe」，监听器周期性调用探针拉取实体状态快照，
  与上次快照做 diff，当状态变化时触发事件。
- 事件触发后调用哪个脚本、传什么参数，由用户配置文件
  （event_listener_config.json）独立指定（与事件定义解耦），
  脚本与配置均属用户本地数据，不纳入 git。

事件参数（触发时传入 handler）：
- 环境变量：EVENT_NAME / EVENT_PAYLOAD(JSON) / DBOX_ROOT
- 命令行（用户未指定参数时默认追加）：--event <事件名> --payload <JSON>
- payload 详情含 event 定义中的 params 字段，外加：
    id / entity_id   实体 ID
    old_status       变化前状态（新增实体为 null）
    new_status       变化后状态

参数模板占位符（event_listener_config.json 的 args 中可用）：
  {EVENT}      事件名
  {ISSUE_ID}   实体 ID
  {ISSUE_JSON} payload 详情的 JSON 字符串

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
import importlib.util

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DBOX_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
PROBES_DIR = os.path.join(SCRIPT_DIR, 'probes')
HANDLERS_DIR = os.path.join(SCRIPT_DIR, 'handlers')
STATE_PATH = os.path.join(SCRIPT_DIR, '.listener_state.json')
LOG_PATH = os.path.join(SCRIPT_DIR, '.listener.log')
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'event_listener_config.json')
REGISTRY_PATH = os.path.join(DBOX_ROOT, 'data', 'event_registry.json')

DEFAULT_CONFIG = {
    'interval': 30,
    'events': {},
}

# 单条事件最大重试次数
MAX_RETRIES = 3


class _Tee(io.TextIOBase):
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
    logf = open(LOG_PATH, 'a', encoding='utf-8')
    orig_out, orig_err = sys.stdout, sys.stderr

    class _TSWriter:
        def __init__(self, raw):
            self._raw = raw
            self._buf = ''

        def write(self, s):
            text = self._buf + s
            out_lines = text.split('\n')
            self._buf = out_lines.pop()
            now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for ln in out_lines:
                if ln == '':
                    self._raw.write('\n')
                    continue
                self._raw.write(f'[{now}] ' + ln + '\n')
            return len(s)

        def flush(self):
            self._raw.flush()

    sys.stdout = _Tee(_TSWriter(orig_out), logf)
    sys.stderr = _Tee(_TSWriter(orig_err), logf)


# probe 模块缓存
_PROBE_CACHE = {}


def load_probe(probe_name):
    """动态加载探针模块（带缓存）。

    兼容两种命名：probes/<probe_name>.py 或 probes/<probe_name>_probe.py，
    便于用户自定义探针时直接用事件语义命名（如 feedback.py）。
    """
    if probe_name in _PROBE_CACHE:
        return _PROBE_CACHE[probe_name]
    candidates = [
        os.path.join(PROBES_DIR, f'{probe_name}.py'),
        os.path.join(PROBES_DIR, f'{probe_name}_probe.py'),
    ]
    path = next((p for p in candidates if os.path.exists(p)), None)
    if not path:
        print(f"[listener] 探针不存在: {candidates[0]} 或 {candidates[1]}")
        return None
    try:
        spec = importlib.util.spec_from_file_location(f'_probe_{probe_name}', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _PROBE_CACHE[probe_name] = mod
        return mod
    except Exception as e:
        print(f"[listener] 加载探针 {probe_name} 失败: {e}")
        return None


def load_registry():
    """读取事件注册中心。返回 list[dict]。"""
    if not os.path.exists(REGISTRY_PATH):
        print(f"[listener] 事件注册中心不存在: {REGISTRY_PATH}（尚未有服务注册事件）")
        return []
    try:
        with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return list(data.values())
    except Exception as e:
        print(f"[listener] 读取事件注册中心失败: {e}")
        return []


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            print(f"[listener] 已加载用户配置: {CONFIG_PATH}")
            return cfg, 'user'
        except Exception as e:
            print(f"[listener] 配置文件解析失败，使用默认配置: {e}")
    return DEFAULT_CONFIG, 'default'


def resolve_handlers(event_name, config):
    events = config.get('events', {})
    handlers = events.get(event_name, [])
    normalized = []
    for h in handlers:
        if isinstance(h, str):
            normalized.append({'script': h, 'args': []})
        else:
            normalized.append({'script': h.get('script', ''), 'args': h.get('args', []) or []})
    return normalized


def render_args(args_template, event_name, detail):
    issue_id = detail.get('id', detail.get('entity_id', ''))
    issue_json = json.dumps(detail, ensure_ascii=False)
    repl = {'{EVENT}': event_name, '{ISSUE_ID}': str(issue_id), '{ISSUE_JSON}': issue_json}
    return [repl.get(a, a) for a in args_template]


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'pid': os.getpid(), 'probes_snapshot': {}}


def save_state(state):
    state['pid'] = os.getpid()
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def call_handler(event_name, detail, handler, dry_run=False):
    script = handler.get('script', '')
    if not script:
        return True
    if os.path.isabs(script):
        hpath = script
    else:
        candidate = os.path.join(HANDLERS_DIR, script)
        hpath = candidate if os.path.exists(candidate) else os.path.join(SCRIPT_DIR, script)
    if not os.path.exists(hpath):
        print(f"[listener] handler 不存在: {hpath}，跳过")
        return True

    args_template = handler.get('args', []) or []
    rendered = render_args(args_template, event_name, detail)
    if not rendered:
        rendered = ['--event', event_name, '--payload', json.dumps(detail, ensure_ascii=False)]

    payload = {'event': event_name, 'issue': detail}
    payload_str = json.dumps(payload, ensure_ascii=False)
    env = dict(os.environ)
    env['EVENT_NAME'] = event_name
    env['EVENT_PAYLOAD'] = payload_str
    env['DBOX_ROOT'] = DBOX_ROOT

    print(f"[listener] 触发 handler: {script} (event={event_name}, entity={detail.get('id')})")
    if dry_run:
        print(f"[listener][dry-run] 命令: {sys.executable} {hpath} {' '.join(rendered)}")
        return True
    try:
        proc = subprocess.run([sys.executable, hpath] + rendered, cwd=DBOX_ROOT, env=env,
                              capture_output=True, text=True, timeout=3600)
        if proc.stdout:
            print(f"[listener][{script}/stdout] {proc.stdout.strip()}")
        if proc.stderr:
            print(f"[listener][{script}/stderr] {proc.stderr.strip()}")
        return proc.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"[listener] handler {script} 超时（>3600s）")
        return False
    except Exception as e:
        print(f"[listener] 调用 handler {script} 异常: {e}")
        return False


def run_cycle(dry_run=False):
    state = load_state()
    config, _ = load_config()
    events = load_registry()
    if not events:
        print("[listener] 当前没有已注册的事件，跳过本轮")
        save_state(state)
        return

    snapshots = state.setdefault('probes_snapshot', {})
    for ev in events:
        name = ev['name']
        probe_name = ev.get('probe')
        params = ev.get('params', [])
        retry_key = f'__retries__{name}'
        retries = state.get(retry_key, {})
        probe = load_probe(probe_name)
        if probe is None or not hasattr(probe, 'snapshot'):
            print(f"[listener] 事件 {name} 的探针 {probe_name} 不可用，跳过")
            continue
        try:
            snap = probe.snapshot()
        except Exception as e:
            print(f"[listener] 探针 {probe_name} 执行失败: {e}")
            continue

        prev = snapshots.get(name, {})
        for eid, new_attr in snap.items():
            new_status = new_attr.get('status')
            old_attr = prev.get(eid)
            old_status = old_attr.get('status') if old_attr else None
            if old_status == new_status:
                continue  # 无变化
            # 构造触发详情。事件声明的 params 若探针未提供，且形如实体 ID
            # （xxx_id / id），则用实体 ID 兜底，避免出现 issue_id=null。
            detail = {}
            for k in params:
                if k in new_attr:
                    detail[k] = new_attr.get(k)
                elif k == 'id' or k.endswith('_id'):
                    detail[k] = eid
                else:
                    detail[k] = None
            detail['id'] = eid
            detail['entity_id'] = eid
            detail['old_status'] = old_status
            detail['new_status'] = new_status
            detail['event'] = name
            print(f"[listener] 事件触发: {name} entity={eid} {old_status} -> {new_status}")
            handlers = resolve_handlers(name, config)
            if not handlers:
                print(f"[listener] 事件 {name} 无 handler 配置，跳过")
                continue
            for handler in handlers:
                ok = call_handler(name, detail, handler, dry_run=dry_run)
                if not ok and not dry_run:
                    retries[eid] = retries.get(eid, 0) + 1
                    if retries[eid] >= MAX_RETRIES:
                        print(f"[listener] {name}/{eid} 重试 {MAX_RETRIES} 次仍失败，放弃")
        # 合并而非覆盖：探针本轮未返回的实体（例如状态查询失败被主动跳过、
        # 或临时不可见）保留上一次的基线，避免下轮出现假的状态变化。
        merged = dict(prev)
        merged.update(snap)
        snapshots[name] = merged
        if not dry_run:
            state[retry_key] = retries

    save_state(state)


def _running_listener_pid():
    """返回另一个正在运行的常驻监听器 pid，没有则返回 None。

    判定依据：状态文件里记录的 pid 仍存活，且其命令行确实是本脚本
    （避免 pid 被系统复用后误判）。
    """
    try:
        pid = (load_state() or {}).get('pid')
    except Exception:
        return None
    if not pid or pid == os.getpid():
        return None
    try:
        import psutil
        proc = psutil.Process(int(pid))
        if not proc.is_running():
            return None
        cmdline = ' '.join(proc.cmdline())
        return int(pid) if 'listener.py' in cmdline else None
    except Exception:
        # psutil 不可用或进程已不存在，视为无冲突，不阻塞启动
        return None


def main():
    parser = argparse.ArgumentParser(description='通用事件监听器')
    parser.add_argument('--once', action='store_true', help='只扫描一次')
    parser.add_argument('--interval', type=int, default=None, help='轮询间隔秒数（覆盖配置）')
    parser.add_argument('--dry-run', action='store_true', help='只打印将触发的事件与命令，不调用 handler')
    args = parser.parse_args()

    setup_logging()
    config, source = load_config()
    interval = args.interval if args.interval else config.get('interval', 30)
    events_count = len(load_registry())
    print(f"[listener] 启动，dbox={DBOX_ROOT}，interval={interval}s，dry_run={args.dry_run}，config={source}，已注册事件={events_count}")
    print(f"[listener] 日志写入: {LOG_PATH}")

    if args.once:
        # 单次扫描不做单实例检查，方便调试；dry-run 不落盘
        run_cycle(dry_run=args.dry_run)
        return

    # 常驻模式做单实例校验：历史上出现过 NSSM 服务进程与手工启动的进程并存，
    # 两者轮流覆盖同一份状态文件，导致快照错乱、事件重复或丢失。
    other = _running_listener_pid()
    if other:
        print(f"[listener] 已有监听器在运行(pid={other})，本进程退出，避免状态文件互相覆盖")
        return 1

    # 立即写入 pid，确保管理后台启动瞬间即判定为运行中
    save_state(load_state())
    try:
        while True:
            run_cycle(dry_run=args.dry_run)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("[listener] 被中断，退出。")


if __name__ == '__main__':
    main()
