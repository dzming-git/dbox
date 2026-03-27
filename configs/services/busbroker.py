#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BusBroker - 服务总线代理进程

独立运行的消息路由守护进程，类似 D-Bus 的 dbus-daemon。
所有服务通过它进行方法调用和信号收发。

使用方式：
    python configs/services/busbroker.py

端口：
    RPC:  15555 (ROUTER/DEALER，方法调用)
    PUB:  15556 (PUB/SUB，信号广播)
"""
import os
import sys
import signal

# 路径设置
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, 'src'))

from servicebus import BusRouter

# 默认端口
DEFAULT_RPC_PORT = 15555
DEFAULT_PUB_PORT = 15556


def main():
    import argparse
    parser = argparse.ArgumentParser(description='BusBroker - 服务总线代理')
    parser.add_argument('--rpc-port', type=int, default=DEFAULT_RPC_PORT,
                        help=f'RPC 端口 (默认: {DEFAULT_RPC_PORT})')
    parser.add_argument('--pub-port', type=int, default=DEFAULT_PUB_PORT,
                        help=f'PUB 端口 (默认: {DEFAULT_PUB_PORT})')
    args = parser.parse_args()

    print(f"[BusBroker] 启动服务总线...")
    print(f"[BusBroker] RPC 端口: {args.rpc_port}, PUB 端口: {args.pub_port}")

    router = BusRouter(rpc_port=args.rpc_port, pub_port=args.pub_port)

    def signal_handler(sig, frame):
        print("\n[BusBroker] 收到退出信号，正在停止...")
        router.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    router.start()
    print("[BusBroker] 服务总线已启动 (Ctrl+C 退出)")
    router.wait()


if __name__ == '__main__':
    main()
