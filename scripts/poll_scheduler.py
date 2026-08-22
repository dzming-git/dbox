#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dbox 通用脚本轮询调度器

设计原则（简单、通用、架构清晰）：
  - 不是为某个具体任务定制的，而是扫描 extensions/scripts 下所有脚本包，
    凡是 manifest 中声明了 poll 触发器的，按各自声明的 interval 周期执行。
  - 每个脚本完全独立：调度器只负责"到点调起 run.py 并传入标准输入"，
    脚本内部自己决定做什么、怎么读状态、怎么写结果。
  - 防重叠：同一脚本上一次还没跑完，不会再次拉起。
  - 自愈：调度器本身是常驻进程，崩了由 NSSM/看门狗拉起；脚本异常不影响其它脚本。

manifest 约定（extensions/scripts/<id>/manifest.json）：
  {
    "id": "<script_id>",
    "name": "脚本显示名",
    "enabled": true,
    "runtime": "python",            # 可选，默认 python
    "command": "run.py",           # 相对脚本包目录的可执行文件
    "trigger": {
      "type": "poll",              # 当前仅支持 poll
      "interval": 30              # 轮询间隔（秒）
    }
  }

调用约定：调度器对到点脚本执行
  <runtime> <command>
stdin 传入 JSON：{"trigger":"poll","context":{...}}
脚本 stdout 逐行文本作为运行日志（可选）。

用法：
  python scripts/poll_scheduler.py            # 常驻运行（作为 NSSM 服务 dbox-scheduler）
  python scripts/poll_scheduler.py --once     # 只跑一轮（调试）
  python scripts/poll_scheduler.py --list     # 列出所有已注册的 poll 脚本
"""
import os
import sys
import json
import time
import subprocess
import argparse
import threading

# 项目根目录（脚本位于 scripts/ 下）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, 'extensions', 'scripts')

# 调度器自身的短轮询周期（检查哪些脚本到点了）
SCHEDULER_TICK = 5

# 运行中脚本的锁（脚本包 id -> 启动时间戳），防止重叠
_RUNNING = {}
_RUNNING_LOCK = threading.Lock()

# 上次触发时间（脚本包 id -> 时间戳）
_LAST_RUN = {}


def _log(msg: str):
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    print(f'[{ts}][scheduler] {msg}', flush=True)


def discover_poll_scripts():
    """扫描 extensions/scripts 下所有声明 poll 触发器的脚本包。

    返回 list[dict]，每项含：
      id, name, enabled, runtime, command(绝对路径), interval, pkg_dir
    """
    result = []
    if not os.path.isdir(SCRIPTS_DIR):
        return result
    for entry in sorted(os.listdir(SCRIPTS_DIR)):
        pkg_dir = os.path.join(SCRIPTS_DIR, entry)
        if not os.path.isdir(pkg_dir):
            continue
        manifest_path = os.path.join(pkg_dir, 'manifest.json')
        if not os.path.isfile(manifest_path):
            continue
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except Exception as e:
            _log(f'跳过 {entry}：manifest 解析失败 - {e}')
            continue
        trigger = manifest.get('trigger') or {}
        if trigger.get('type') != 'poll':
            continue
        enabled = manifest.get('enabled', True)
        if enabled is False:
            continue
        command = manifest.get('command', 'run.py')
        runtime = manifest.get('runtime', 'python')
        interval = int(trigger.get('interval', 60))
        result.append({
            'id': manifest.get('id', entry),
            'name': manifest.get('name', entry),
            'pkg_dir': pkg_dir,
            'command': os.path.join(pkg_dir, command),
            'runtime': runtime,
            'interval': max(interval, 1),
        })
    return result


def _runtime_executable(runtime: str) -> str:
    if runtime in ('python', 'python3'):
        return sys.executable
    return runtime  # 如 node / 其它可执行名


def run_script(script: dict):
    """拉起一个脚本包（不阻塞，后台线程）。"""
    sid = script['id']
    cmd = [_runtime_executable(script['runtime']), script['command']]
    payload = json.dumps({'trigger': 'poll', 'context': {}}, ensure_ascii=False)
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=script['pkg_dir'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        proc.stdin.write(payload)
        proc.stdin.close()
    except Exception as e:
        _log(f'拉起脚本失败 {sid}: {e}')
        with _RUNNING_LOCK:
            _RUNNING.pop(sid, None)
        return

    # 后台线程读取输出并记录，结束后释放锁
    def _pump():
        try:
            for line in proc.stdout:
                line = line.rstrip('\n')
                if line:
                    _log(f'[{sid}] {line}')
            proc.wait()
        except Exception:
            pass
        finally:
            with _RUNNING_LOCK:
                _RUNNING.pop(sid, None)

    t = threading.Thread(target=_pump, daemon=True)
    t.start()


def tick():
    """检查所有 poll 脚本，到点且空闲的拉起。"""
    now = time.time()
    scripts = discover_poll_scripts()
    with _RUNNING_LOCK:
        running = dict(_RUNNING)
    for s in scripts:
        sid = s['id']
        last = _LAST_RUN.get(sid, 0)
        is_running = running.get(sid) is not None
        if is_running:
            continue
        if now - last < s['interval']:
            continue
        # 到点且空闲 -> 拉起
        _LAST_RUN[sid] = now
        with _RUNNING_LOCK:
            _RUNNING[sid] = now
        _log(f'触发脚本 {sid}（间隔 {s["interval"]}s）')
        run_script(s)


def main():
    parser = argparse.ArgumentParser(description='Dbox 通用脚本轮询调度器')
    parser.add_argument('--once', action='store_true', help='只跑一轮即退出（调试）')
    parser.add_argument('--list', action='store_true', help='列出所有已注册的 poll 脚本')
    args = parser.parse_args()

    scripts = discover_poll_scripts()
    if args.list:
        if not scripts:
            print('未发现任何 poll 触发器脚本')
        for s in scripts:
            print(f'  - {s["id"]:20s} interval={s["interval"]}s  cmd={s["command"]}')
        return

    if args.once:
        _log('单轮模式')
        tick()
        return

    _log(f'常驻调度器启动，扫描目录: {SCRIPTS_DIR}')
    _log(f'已注册 {len(scripts)} 个 poll 脚本: ' +
         ', '.join(s['id'] for s in scripts) if scripts else '（无）')
    try:
        while True:
            try:
                tick()
            except Exception as e:
                _log(f'tick 异常: {e}')
            time.sleep(SCHEDULER_TICK)
    except KeyboardInterrupt:
        _log('收到中断，退出')


if __name__ == '__main__':
    main()
