# -*- coding: utf-8 -*-
"""缓存管理微服务入口（com.dbox.cached）。

启动后自动加入服务总线（15555/15556），负责接管并治理各拓展的媒体/资源磁盘缓存：
- 发现并统计所有托管缓存分区
- 后台周期执行容量上限兜底淘汰
- 启动时自检迁移历史散落缓存目录

作为独立后端微服务运行（无 HTTP 端口），由 dbox-bus 路由、servicemgr/watchdog 纳管。
"""
import os
import sys
import time
import signal

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from servicebus.service_base import DEFAULT_HOST, DEFAULT_RPC_PORT, DEFAULT_PUB_PORT
from cache.bus_adapter import BusCacheAdapter


def main():
    service = BusCacheAdapter(
        host=DEFAULT_HOST,
        rpc_port=DEFAULT_RPC_PORT,
        pub_port=DEFAULT_PUB_PORT,
    )

    def _stop(signum, frame):
        service.stop()
        os._exit(0)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    service.start()

    # 保活：总线 broker 在 15555/15556 上路由消息，进程需常驻。
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        service.stop()


if __name__ == '__main__':
    main()
