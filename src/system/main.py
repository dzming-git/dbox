#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dbox System Monitor Service - 系统监控服务

独立的微服务，负责监控系统资源（CPU、内存、磁盘等）。

目录结构：
  src/system/main.py  - 本文件（服务入口）
  src/system/        - 系统监控模块
  configs/services/  - 服务管理

总线端口（默认）：
  RPC:  15555
  PUB:  15556
"""
import os
import sys
import signal
import argparse

# 路径设置
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_THIS_DIR)
PROJECT_ROOT = os.path.dirname(_SRC_DIR)
sys.path.insert(0, _SRC_DIR)

# 服务配置
SERVICE_NAME = 'systemd'
DEFAULT_RPC_PORT = 15555
DEFAULT_PUB_PORT = 15556


def main():
    parser = argparse.ArgumentParser(description='Dbox System Monitor Service')
    parser.add_argument('--host', default='127.0.0.1', help='总线地址')
    parser.add_argument('--rpc-port', type=int, default=DEFAULT_RPC_PORT, help=f'RPC 端口 (默认: {DEFAULT_RPC_PORT})')
    parser.add_argument('--pub-port', type=int, default=DEFAULT_PUB_PORT, help=f'PUB 端口 (默认: {DEFAULT_PUB_PORT})')
    parser.add_argument('--interval', type=float, default=2.0, help='监控轮询间隔（秒，默认 2.0）')
    args = parser.parse_args()

    print(f"[systemd] 启动系统监控服务...")
    print(f"[systemd] 总线地址: {args.host}:{args.rpc_port}/{args.pub_port}")
    print(f"[systemd] 轮询间隔: {args.interval}秒")

    # 导入并初始化监控器
    from system.monitor import SystemMonitor
    monitor = SystemMonitor(interval=args.interval)
    monitor.start()
    print(f"[systemd] 系统监控已启动 (CPU: {monitor.get_current_metrics().cpu.count} 核)")

    # 导入并初始化总线适配器
    from system.bus_adapter import BusSystemAdapter
    adapter = BusSystemAdapter(
        system_monitor=monitor,
        host=args.host,
        rpc_port=args.rpc_port,
        pub_port=args.pub_port
    )

    def signal_handler(sig, frame):
        print(f"\n[systemd] 收到退出信号，正在停止...")
        monitor.stop()
        adapter.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    adapter.start()
    print(f"[systemd] 系统监控服务已启动 (PID: {os.getpid()})")
    print(f"[systemd] 总线: {args.host}:{args.rpc_port} (RPC), {args.host}:{args.pub_port} (PUB)")
    print(f"[systemd] 按 Ctrl+C 退出")

    # 使用 time.sleep 等待信号
    import time
    while True:
        time.sleep(1)


if __name__ == '__main__':
    main()