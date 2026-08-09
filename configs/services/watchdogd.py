#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
watchdogd - 服务看门狗守护进程

周期性 ping 各服务总线，对长时间不可达的服务自动重启，
多次失败则升级告警，并通过总线对外暴露总体健康数据。

使用方式：
    python configs/services/watchdogd.py

总线端口（默认）：
    RPC:  15555
    PUB:  15556
"""
import os
import sys
import signal
import time

# 路径设置
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# configs/services/ → configs/ → 项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, 'src'))  # src/ → 可 import servicebus

from servicebus.watchdog_adapter import WatchdogService

DEFAULT_RPC_PORT = 15555
DEFAULT_PUB_PORT = 15556
DEFAULT_CHECK_INTERVAL = 15    # 巡检间隔（秒）
DEFAULT_PING_TIMEOUT = 2000    # 总线 Ping 超时（毫秒）
DEFAULT_FAIL_THRESHOLD = 3     # 连续几次不健康才重启
DEFAULT_RESTART_GRACE = 45     # 重启后宽限（秒）
DEFAULT_MAX_RESTARTS = 3       # 连续重启上限，超过则告警


def main():
    import argparse
    parser = argparse.ArgumentParser(description='watchdogd - 服务看门狗守护进程')
    parser.add_argument('--rpc-port', type=int, default=DEFAULT_RPC_PORT,
                        help=f'RPC 端口 (默认: {DEFAULT_RPC_PORT})')
    parser.add_argument('--pub-port', type=int, default=DEFAULT_PUB_PORT,
                        help=f'PUB 端口 (默认: {DEFAULT_PUB_PORT})')
    parser.add_argument('--check-interval', type=int, default=DEFAULT_CHECK_INTERVAL,
                        help=f'巡检间隔秒数 (默认: {DEFAULT_CHECK_INTERVAL})')
    parser.add_argument('--ping-timeout', type=int, default=DEFAULT_PING_TIMEOUT,
                        help=f'Ping 超时毫秒 (默认: {DEFAULT_PING_TIMEOUT})')
    parser.add_argument('--fail-threshold', type=int, default=DEFAULT_FAIL_THRESHOLD,
                        help=f'连续失败几次后重启 (默认: {DEFAULT_FAIL_THRESHOLD})')
    parser.add_argument('--restart-grace', type=int, default=DEFAULT_RESTART_GRACE,
                        help=f'重启后宽限秒数 (默认: {DEFAULT_RESTART_GRACE})')
    parser.add_argument('--max-restarts', type=int, default=DEFAULT_MAX_RESTARTS,
                        help=f'连续重启上限 (默认: {DEFAULT_MAX_RESTARTS})')
    args = parser.parse_args()

    print(f"[watchdogd] 启动服务看门狗...")
    print(f"[watchdogd] RPC: {args.rpc_port}, PUB: {args.pub_port}, "
          f"巡检间隔: {args.check_interval}s, 失败阈值: {args.fail_threshold}, "
          f"最大重启: {args.max_restarts}")

    adapter = WatchdogService(
        rpc_port=args.rpc_port,
        pub_port=args.pub_port,
        check_interval=args.check_interval,
        ping_timeout=args.ping_timeout,
        fail_threshold=args.fail_threshold,
        restart_grace=args.restart_grace,
        max_restarts=args.max_restarts,
    )

    def signal_handler(sig, frame):
        print("\n[watchdogd] 收到退出信号，正在停止...")
        adapter.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    adapter.start()
    print(f"[watchdogd] 看门狗已启动 (Ctrl+C 退出)")

    # 使用 time.sleep 等待信号，Windows 兼容
    while True:
        time.sleep(86400)


if __name__ == '__main__':
    main()
