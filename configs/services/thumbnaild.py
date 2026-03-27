#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
thumbnaild - 封面生成器守护进程

通过服务总线提供封面生成能力，不再暴露 HTTP 接口。

使用方式：
    python configs/services/thumbnaild.py

总线端口（默认）：
    RPC:  15555
    PUB:  15556
"""
import os
import sys
import signal
import threading
import time

# 路径设置
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# configs/services/ → configs/ → Dplayer2.0/（项目根目录）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, 'src'))  # src/ → 可 import servicebus

from servicebus.thumbnail_adapter import BusThumbnailAdapter
from thumbnail.task_manager import TaskManager, task_worker

# 默认配置
DEFAULT_RPC_PORT = 15555
DEFAULT_PUB_PORT = 15556
DEFAULT_MAX_CONCURRENT = 2
DEFAULT_QUEUE_SIZE = 100


def main():
    import argparse
    parser = argparse.ArgumentParser(description='thumbnaild - 封面生成器守护进程')
    parser.add_argument('--rpc-port', type=int, default=DEFAULT_RPC_PORT,
                        help=f'RPC 端口 (默认: {DEFAULT_RPC_PORT})')
    parser.add_argument('--pub-port', type=int, default=DEFAULT_PUB_PORT,
                        help=f'PUB 端口 (默认: {DEFAULT_PUB_PORT})')
    parser.add_argument('--max-concurrent', type=int, default=DEFAULT_MAX_CONCURRENT,
                        help=f'最大并发任务数 (默认: {DEFAULT_MAX_CONCURRENT})')
    args = parser.parse_args()

    print(f"[thumbnaild] 启动封面生成器守护进程...")
    print(f"[thumbnaild] RPC: {args.rpc_port}, PUB: {args.pub_port}")

    # 初始化任务管理器
    task_manager = TaskManager(
        max_concurrent=args.max_concurrent,
        queue_size=DEFAULT_QUEUE_SIZE
    )

    # 启动工作线程
    for i in range(args.max_concurrent):
        t = threading.Thread(target=task_worker, args=(task_manager,), daemon=True)
        t.start()
        print(f"[thumbnaild] 启动工作线程 #{i+1}")

    # 初始化总线适配器
    adapter = BusThumbnailAdapter(
        task_manager=task_manager,
        rpc_port=args.rpc_port,
        pub_port=args.pub_port
    )

    def signal_handler(sig, frame):
        print("\n[thumbnaild] 收到退出信号，正在停止...")
        adapter.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    adapter.start()
    print(f"[thumbnaild] 封面生成器已启动 (工作线程: {args.max_concurrent}, Ctrl+C 退出)")

    # 使用 time.sleep 等待信号，Windows 兼容
    while True:
        time.sleep(86400)


if __name__ == '__main__':
    main()
