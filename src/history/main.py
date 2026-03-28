# -*- coding: utf-8 -*-
"""
播放历史服务入口

Usage:
    python src/history/main.py

依赖:
    - pyzmq (已安装到 venv)
    - ServiceBus (BusRouter 必须在 15555/15556 运行)
"""

import os
import sys
import signal

# 添加 src 目录到 path
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from servicebus.service_base import DEFAULT_HOST, DEFAULT_RPC_PORT, DEFAULT_PUB_PORT

# 导入总线适配器
try:
    from .bus_adapter import BusHistoryAdapter
except ImportError:
    from bus_adapter import BusHistoryAdapter


def main():
    """主函数"""
    print("=" * 50)
    print("DPlayer 播放历史服务 (historyd)")
    print("=" * 50)
    print(f"RPC 端口: {DEFAULT_RPC_PORT}")
    print(f"PUB 端口: {DEFAULT_PUB_PORT}")
    print("=" * 50)

    # 创建服务实例
    service = BusHistoryAdapter(
        host=DEFAULT_HOST,
        rpc_port=DEFAULT_RPC_PORT,
        pub_port=DEFAULT_PUB_PORT,
    )

    # 信号处理
    def signal_handler(sig, frame):
        print("\n正在停止服务...")
        service.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # 启动服务
        print("服务启动中...")
        service.start()
        print("服务已启动，按 Ctrl+C 停止")
        print()

        # 保持运行
        import time
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n收到键盘中断")
    except Exception as e:
        print(f"服务异常: {e}")
        raise
    finally:
        service.stop()
        print("服务已停止")


if __name__ == '__main__':
    main()
