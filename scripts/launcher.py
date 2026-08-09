#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dbox - 免安装绿色启动器（开发/热重载模式）

特点：
  1. 不依赖 NSSM、不写注册表、不需要管理员权限。
  2. 所有路径基于本文件推导，移动整个目录后直接运行即可。
  3. 后端服务以子进程方式运行，启动时注入 DBOX_DEV_MODE=1（开发模式）。
  4. 看门狗监控源码 .py 改动，自动重启对应服务（绕开 zmq 与 Flask reloader 的冲突）。
  5. 前端（Vite）自带 HMR，无需重启。

用法：
  start.bat                在前台窗口启动所有服务（Ctrl+C 停止）
  stop.bat                 停止所有服务（后台启动时用）
  python scripts/launcher.py           启动
  python scripts/launcher.py --stop    停止
  python scripts/launcher.py --status  仅检查路径/端口，不启动
"""
import os
import sys
import time
import json
import signal
import subprocess
from pathlib import Path

# ============================================================
# 路径（全部基于本文件，可随目录搬迁）
# ============================================================
ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / 'data' / 'logs'
PID_FILE = ROOT / 'data' / '.green_pids.json'
LAUNCHER_LOG = LOG_DIR / 'launcher.log'
IS_WINDOWS = os.name == 'nt'


def _log(msg: str):
    """同时输出到控制台（立即刷新）和启动器日志文件。"""
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        with open(LAUNCHER_LOG, 'a', encoding='utf-8') as f:
            f.write(msg + '\n')
    except Exception:
        pass

try:
    import psutil
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False


def _venv_python() -> str:
    if IS_WINDOWS:
        cand = ROOT / 'venv' / 'Scripts' / 'python.exe'
    else:
        cand = ROOT / 'venv' / 'bin' / 'python'
    if cand.exists():
        return str(cand)
    return sys.executable


# ============================================================
# 服务定义
#   entry : 相对 ROOT 的入口脚本
#   port  : 监听端口（用于状态检查）
#   watch : 该服务自己的源码目录/文件；改动时只重启本服务
# ============================================================
SERVICES = [
    {'key': 'bus',        'entry': 'configs/services/busbroker.py',       'port': None, 'watch': ['src/servicebus', 'configs/services/busbroker.py']},
    {'key': 'web',        'entry': 'src/web/main.py',                     'port': 8080, 'watch': ['src/web']},
    {'key': 'downloader', 'entry': 'src/downloader/main.py',              'port': 8092, 'watch': ['src/downloader']},
    {'key': 'thumbnail',  'entry': 'configs/services/thumbnaild.py',      'port': None, 'watch': ['src/thumbnail', 'configs/services/thumbnaild.py']},
    {'key': 'webui',      'entry': 'configs/services/webui_service.py',   'port': 5173, 'watch': ['configs/services/webui_service.py']},
    {'key': 'resource',   'entry': 'src/resource/main.py',                'port': None, 'watch': ['src/resource']},
    {'key': 'user',       'entry': 'src/user/main.py',                    'port': None, 'watch': ['src/user']},
    {'key': 'system',     'entry': 'src/system/main.py',                  'port': None, 'watch': ['src/system']},
    {'key': 'history',    'entry': 'src/history/main.py',                 'port': None, 'watch': ['src/history']},
    {'key': 'collection', 'entry': 'src/collection/main.py',              'port': None, 'watch': ['src/collection']},
    {'key': 'search',     'entry': 'src/search/main.py',                  'port': None, 'watch': ['src/search']},
    {'key': 'servicemgr', 'entry': 'configs/services/servicemgrd.py',     'port': None, 'watch': ['configs/services/servicemgrd.py']},
    {'key': 'watchdog',   'entry': 'configs/services/watchdogd.py',        'port': None, 'watch': ['src/servicebus', 'configs/services/watchdogd.py']},
]

# 共享库：改动后需重启所有后端 Python 服务（前端 HMR 自理）
SHARED_WATCH = ['src/liblog', 'src/web/utils', 'src/web/core', 'src/web/backend', 'src/web/api', 'configs/web']

ALL_PYTHON_KEYS = [s['key'] for s in SERVICES if s['key'] != 'webui']


# ============================================================
# 进程管理
# ============================================================
def _open_log(key: str):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return open(LOG_DIR / f'{key}_stdout.log', 'a', encoding='utf-8', buffering=1)


def launch(key: str) -> subprocess.Popen:
    svc = next(s for s in SERVICES if s['key'] == key)
    entry = ROOT / svc['entry']
    if not entry.exists():
        _log(f'  [WARN] 入口脚本不存在，跳过 {key}: {entry}')
        return None
    env = os.environ.copy()
    env['DBOX_DEV_MODE'] = '1'          # 开发模式：绕过 NSSM 守卫 + 开启 debug
    logf = _open_log(key)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
    proc = subprocess.Popen(
        [_venv_python(), str(entry)],
        cwd=str(ROOT),
        env=env,
        stdout=logf,
        stderr=subprocess.STDOUT,
        creationflags=flags,
    )
    _log(f'  [OK] {key:12s} 已启动 PID={proc.pid}')
    return proc


def kill_tree(pid: int):
    if HAS_PSUTIL:
        try:
            p = psutil.Process(pid)
            for child in p.children(recursive=True):
                try:
                    child.kill()
                except Exception:
                    pass
            try:
                p.kill()
            except Exception:
                pass
            return
        except Exception:
            pass
    try:
        os.kill(pid, signal.SIGTERM if not IS_WINDOWS else 15)
    except Exception:
        pass


def save_pids(procs: dict):
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {k: (p.pid if p else None) for k, p in procs.items()}
    data['_supervisor'] = os.getpid()
    PID_FILE.write_text(json.dumps(data), encoding='utf-8')


def load_pids() -> dict:
    if PID_FILE.exists():
        try:
            return json.loads(PID_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}


# ============================================================
# 看门狗：源码改动 -> 重启服务
# ============================================================
WATCH_EXTS = {'.py'}
RESTART_COOLDOWN = 3.0


def _iter_py_files(dirs):
    for d in dirs:
        p = ROOT / d
        if not p.exists():
            continue
        for f in p.rglob('*'):
            if f.is_file() and f.suffix in WATCH_EXTS:
                yield f


def _services_for_change(rel_path: str) -> list:
    # Windows 下 Path.relative_to 返回反斜杠，统一为正斜杠再比较
    rel_path = rel_path.replace('\\', '/')
    # 1. 服务自有代码
    for svc in SERVICES:
        for w in svc['watch']:
            if rel_path == w or rel_path.startswith(w + '/'):
                return [svc['key']]
    # 2. 共享库 -> 所有后端服务
    for w in SHARED_WATCH:
        if rel_path.startswith(w + '/'):
            return ALL_PYTHON_KEYS
    return []


def _snapshot_mtimes() -> dict:
    snap = {}
    for f in _iter_py_files([w for s in SERVICES for w in s['watch']] + SHARED_WATCH):
        try:
            snap[str(f)] = f.stat().st_mtime
        except Exception:
            pass
    return snap


def _detect_changes(prev: dict) -> list:
    """返回需要重启的 service key 列表（去重）"""
    keys = set()
    current = {}
    all_dirs = [w for s in SERVICES for w in s['watch']] + SHARED_WATCH
    for f in _iter_py_files(all_dirs):
        try:
            m = f.stat().st_mtime
        except Exception:
            continue
        current[str(f)] = m
        if str(f) not in prev or prev[str(f)] != m:
            rel = str(f.relative_to(ROOT))
            for k in _services_for_change(rel):
                keys.add(k)
    # 更新 prev（仅保留仍在的文件，并记录新增文件）
    prev.clear()
    prev.update(current)
    return list(keys)


# ============================================================
# 主流程
# ============================================================
def cmd_status():
    print('=' * 60)
    print('  Dbox 绿色启动器 - 状态检查')
    print('=' * 60)
    print(f'  项目根目录 : {ROOT}')
    print(f'  Python     : {_venv_python()}')
    print(f'  venv 存在  : { (ROOT / "venv").exists() }')
    import socket
    for svc in SERVICES:
        entry = ROOT / svc['entry']
        ok = 'OK' if entry.exists() else '缺失'
        port_msg = ''
        if svc['port']:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            free = s.connect_ex(('127.0.0.1', svc['port'])) != 0
            s.close()
            port_msg = f"  端口 {svc['port']}: {'空闲' if free else '被占用'}"
        print(f'  {svc["key"]:12s} 入口[{ok}]{port_msg}')
    print('=' * 60)


def cmd_stop():
    pids = load_pids()
    if not pids:
        print('没有正在运行的绿色服务（未找到 PID 文件）。')
        return
    print('正在停止绿色服务...')
    sup = pids.pop('_supervisor', None)
    for pid in list(pids.values()) + ([sup] if sup else []):
        if pid:
            kill_tree(pid)
    try:
        PID_FILE.unlink()
    except Exception:
        pass
    print('已发送停止信号。')


def cmd_run():
    print('=' * 60)
    print('  Dbox 绿色启动器（开发/热重载模式）')
    print('=' * 60)
    print(f'  项目根目录 : {ROOT}')
    print(f'  Python     : {_venv_python()}')
    print(f'  日志目录   : {LOG_DIR}')
    print('-' * 60)

    # 若已有实例在跑，拒绝重复启动
    existing = load_pids()
    sup = existing.get('_supervisor')
    if sup and _pid_alive(sup):
        _log(f'  [WARN] 已有绿色启动器在运行 (PID={sup})，请先 stop.bat。')
        return

    procs = {}
    for svc in SERVICES:
        p = launch(svc['key'])
        if p:
            procs[svc['key']] = p
        time.sleep(1.0)  # 错开启动，bus 优先就绪
    save_pids(procs)
    print('-' * 60)
    print('  所有服务已启动。后端改 .py 自动重启；前端 Vite HMR。')
    print('  按 Ctrl+C 停止。')
    print('=' * 60)

    stopping = {'flag': False}

    def _handle_stop(signum, frame):
        stopping['flag'] = True
        print('\n收到停止信号，正在关闭所有服务...')
        for k, p in procs.items():
            if p and p.poll() is None:
                kill_tree(p.pid)
        try:
            PID_FILE.unlink()
        except Exception:
            pass
        print('已停止。')
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_stop)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, _handle_stop)

    # 看门狗 + 崩溃自愈
    mtimes = _snapshot_mtimes()
    last_restart = {}
    crash_backoff = {}

    while not stopping['flag']:
        time.sleep(1.5)

        # 1. 崩溃自愈（带退避，避免错误代码下死循环）
        now = time.time()
        for k, p in list(procs.items()):
            if p is None:
                continue
            if p.poll() is not None:
                # 最近 10 秒内已重启过且已崩溃 >=3 次 -> 放弃该服务，避免刷屏
                if now - crash_backoff.get(k, 0) < 10 and crash_backoff.get(k + '_count', 0) >= 3:
                    _log(f'  [WARN] {k} 持续崩溃，已暂停自动重启（请查看日志）。')
                    procs[k] = None
                    continue
                _log(f'  [INFO] {k} 已退出，尝试重启...')
                new_p = launch(k)
                procs[k] = new_p
                crash_backoff[k] = now
                crash_backoff[k + '_count'] = crash_backoff.get(k + '_count', 0) + 1
                if new_p:
                    save_pids(procs)

        # 2. 源码改动 -> 重启
        changed = _detect_changes(mtimes)
        now = time.time()
        for k in changed:
            if procs.get(k) is None:
                continue
            if now - last_restart.get(k, 0) < RESTART_COOLDOWN:
                continue
            _log(f'  [HOT] 检测到源码改动，重启 {k} ...')
            p = procs[k]
            if p and p.poll() is None:
                kill_tree(p.pid)
                try:
                    p.wait(timeout=5)
                except Exception:
                    pass
            new_p = launch(k)
            procs[k] = new_p
            last_restart[k] = now
            if new_p:
                save_pids(procs)


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    if HAS_PSUTIL:
        return psutil.pid_exists(pid)
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def main():
    args = sys.argv[1:]
    if '--status' in args:
        cmd_status()
    elif '--stop' in args:
        cmd_stop()
    else:
        cmd_run()


if __name__ == '__main__':
    main()
