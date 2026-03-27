# -*- coding: utf-8 -*-
"""
BusClient - 总线客户端（调用端）

模拟 OpenBMC 中 bmcweb 调用后端服务的模式。
bmcweb 不继承 BaseDBusService，它只是一个普通的 D-Bus 客户端。

用法：

    from servicebus import BusClient

    client = BusClient('com.dplayer.web')

    # 同步方法调用
    result = client.call_method(
        service='com.dplayer.thumbnail',
        interface='com.dplayer.Thumbnail',
        method='Generate',
        params={'video_path': '/path/to/video.mp4', 'video_hash': 'abc123'}
    )

    # 订阅信号
    client.on_signal('com.dplayer.Thumbnail', 'ThumbnailGenerated',
                     on_thumbnail_generated)

    def on_thumbnail_generated(signal_data, msg):
        print(f"缩略图已生成: {signal_data}")
"""

from typing import Dict, Any, Optional, Callable

from .bus import BusEndpoint, DEFAULT_HOST, DEFAULT_RPC_PORT, DEFAULT_PUB_PORT


class BusClient:
    """
    总线客户端 — 用于调用其他服务的方法

    与 BaseDBusService 的区别：
    - BaseDBusService：既提供服务，又可调用其他服务
    - BusClient：只调用其他服务，不导出任何方法

    D-Bus 对应：
      BusClient  →  dbus.proxies.ObjectProxy / sdbusplus::proxy::proxy
      call_method  →  proxy.call()
      on_signal  →  signal.add_signal_receiver()
    """

    def __init__(self, client_name: str,
                 host: str = DEFAULT_HOST,
                 rpc_port: int = DEFAULT_RPC_PORT,
                 pub_port: int = DEFAULT_PUB_PORT):
        self._endpoint = BusEndpoint(client_name, host, rpc_port, pub_port)
        self._endpoint.connect()
        self._endpoint.start_listening()

    def call_method(self, service: str, interface: str, method: str,
                    params: Dict[str, Any] = None,
                    timeout: int = 5000) -> Optional[Dict[str, Any]]:
        """
        调用远程服务方法

        Args:
            service: 目标服务名，如 'com.dplayer.thumbnail'
            interface: 接口名，如 'com.dplayer.Thumbnail'
            method: 方法名，如 'Generate'
            params: 方法参数
            timeout: 超时（毫秒）

        Returns:
            方法返回值字典，或 None（超时/错误）
        """
        return self._endpoint.call_method(service, interface, method,
                                          params, timeout)

    def on_signal(self, interface: str, signal_name: str,
                  handler: Callable):
        """
        注册信号处理器

        Args:
            interface: 接口名
            signal_name: 信号名
            handler: 回调函数 handler(signal_data: dict, msg: BusMessage)
        """
        self._endpoint.on_signal(interface, signal_name, handler)

    def stop(self):
        """断开连接"""
        self._endpoint.stop()
