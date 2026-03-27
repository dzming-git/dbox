#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
servicemgrd - 服务管理守护进程

定期扫描 Windows NSSM dplayer-* 服务，缓存状态，
通过服务总线对外提供查询接口。

使用方式：
    python configs/services/servicemgrd.py

总线端口（默认）：
    RPC:  15555
    PUB:  15556
"""
import os
import sys
import signal

# 路径设置
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_SRC_DIR)
sys.path.insert(0, _SRC_DIR)
sys.path.insert(0, os.path.join(_PROJECT_ROOT, 'src'))

from servicebus.service_mgr_adapter import BusServiceMgrAdapter

DEFAULT_RPC_PORT = 15555
DEFAULT_PUB_PORT = 15556
DEFAULT_SCAN_INTERVAL = 5  # 每 5 秒扫描一次


def main():
    import argparse
    parser = argparse.ArgumentParser(description='servicemgrd - 服务管理守护进程')
    parser.add_argument('--rpc-port', type=int, default=DEFAULT_RPC_PORT,
                        help=f'RPC 端口 (默认: {DEFAULT_RPC_PORT})')
    parser.add_argument('--pub-port', type=int, default=DEFAULT_PUB_PORT,
                        help=f'PUB 端口 (默认: {DEFAULT_PUB_PORT})')
    parser.add_argument('--scan-interval', type=int, default=DEFAULT_SCAN_INTERVAL,
                        help=f'扫描间隔秒数 (默认: {DEFAULT_SCAN_INTERVAL})')
    args = parser.parse_args()

    print(f"[servicemgrd] 启动服务管理守护进程...")
    print(f"[servicemgrd] RPC: {args.rpc_port}, PUB: {args.pub_port}, 扫描间隔: {args.scan_interval}秒")

    adapter = BusServiceMgrAdapter(
        rpc_port=args.rpc_port,
        pub_port=args.pub_port,
        scan_interval=args.scan_interval
    )

    def signal_handler(sig, frame):
        print("\n[servicemgrd] 收到退出信号，正在停止...")
        adapter.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    adapter.start()
    print(f"[servicemgrd] 服务管理已启动")
    adapter.wait()


if __name__ == '__main__':
    main()
