# -*- coding: utf-8 -*-
"""
资源管理服务 (resourced) 入口

独立的服务进程，负责：
1. 资源库管理（添加/删除/配置）
2. 文件扫描（手动/定时）
3. 文件监控（实时监听文件系统变化）
4. 索引管理（hash 计算、元数据提取）

服务总线：
- RPC: 15555
- PUB: 15556

使用方法：
    python src/resource/main.py
"""

import os
import sys
import time
import signal
import argparse

# 添加 src 目录到 path
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SRC_DIR)

from liblog import get_module_logger

# 服务配置
SERVICE_NAME = 'resourced'
RPC_PORT = 15555
PUB_PORT = 15556

# 日志目录
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'data')
_LOG_DIR = os.path.join(_DATA_DIR, 'logs')
os.makedirs(_LOG_DIR, exist_ok=True)

logger = get_module_logger(SERVICE_NAME, log_dir=_LOG_DIR)


def main():
    parser = argparse.ArgumentParser(description='DPlayer 资源管理服务')
    parser.add_argument('--host', default='127.0.0.1', help='总线地址')
    parser.add_argument('--rpc-port', type=int, default=RPC_PORT, help='RPC 端口')
    parser.add_argument('--pub-port', type=int, default=PUB_PORT, help='PUB 端口')
    parser.add_argument('--dev', action='store_true', help='开发模式')
    args = parser.parse_args()

    logger.info(f'启动资源管理服务...')
    logger.info(f'  总线地址: {args.host}:{args.rpc_port}/{args.pub_port}')

    # 初始化数据库
    from models import Database
    Database.init_db()
    logger.info('数据库初始化完成')

    # 创建总线适配器
    from scanner_adapter import BusResourceAdapter
    adapter = BusResourceAdapter(
        host=args.host,
        rpc_port=args.rpc_port,
        pub_port=args.pub_port
    )

    # 信号处理
    def signal_handler(signum, frame):
        logger.info(f'收到信号 {signum}，停止服务...')
        adapter.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 启动适配器
    try:
        adapter.start()
        logger.info(f'资源管理服务已启动 (PID: {os.getpid()})')
        logger.info(f'  总线: {args.host}:{args.rpc_port} (RPC), {args.host}:{args.pub_port} (PUB)')

        # 保持运行
        while True:
            time.sleep(1)
    except Exception as e:
        logger.error(f'服务启动失败: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
