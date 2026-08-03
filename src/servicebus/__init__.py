# -*- coding: utf-8 -*-
"""
ServiceBus - 模拟 OpenBMC D-Bus 的内部服务总线

提供进程间通信能力，支持：
- 方法调用（Method Call）：同步请求/回复，模拟 D-Bus Method
- 信号广播（Signal）：发布/订阅模式，模拟 D-Bus Signal
- 服务注册/发现：模拟 D-Bus 服务注册到总线
- 属性变更通知：模拟 D-Bus PropertiesChanged 信号

目录结构：
  src/servicebus/
    __init__.py        - 本文件
    bus.py             - ServiceBus 核心实现
    service_base.py    - BaseDBusService 基类（phosphor-* 风格）
    client.py          - BusClient 客户端（调用端）
    protocol.py        - 通信协议定义（JSON 消息格式）

用法示例（服务端，模拟 phosphor-* 风格）：

    from servicebus import BaseDBusService, ServiceBus

    class ThumbnailService(BaseDBusService):
        BUS_NAME = 'com.dbox.thumbnail'
        INTERFACES = ['com.dbox.Thumbnail']

        def on_method_generate(self, params):
            # 处理方法调用
            return {'success': True, 'task_id': 'xxx'}

    ServiceBus.register_service(ThumbnailService())
    ServiceBus.run()  # 阻塞运行

用法示例（客户端，模拟 bmcweb 风格）：

    from servicebus import BusClient

    client = BusClient()
    result = client.call_method(
        service='com.dbox.thumbnail',
        interface='com.dbox.Thumbnail',
        method='Generate',
        params={'video_path': '/path/to/video', 'video_hash': 'abc'}
    )
"""
from .bus import ServiceBus
from .service_base import BaseDBusService
from .client import BusClient
from .router import BusRouter
from .protocol import BusMessage, MessageType
from .service_mgr_adapter import BusServiceMgrAdapter
from .thumbnail_adapter import BusThumbnailAdapter

__all__ = [
    'ServiceBus',
    'BaseDBusService',
    'BusClient',
    'BusRouter',
    'BusMessage',
    'MessageType',
    'BusServiceMgrAdapter',
    'BusThumbnailAdapter',
]
