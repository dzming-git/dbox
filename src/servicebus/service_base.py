# -*- coding: utf-8 -*-
"""
BaseDBusService - 服务基类

模拟 OpenBMC phosphor-* 服务的风格：
  phosphor-gpio-monitor  →  ThumbnailDBusService
  phosphor-led-manager   →  FutureDBusService

每个 phosphor-* 服务都会：
1. 连接到 D-Bus System Bus
2. 注册自己的 Bus Name
3. 导出接口（Interface）和方法（Method）
4. 监听并处理方法调用
5. 发出信号（Signal）通知状态变更

D-Bus 对应关系：
  phosphor-* 继承 sdbusplus::xyz::openbmc_project::Common::Interface
  → BaseDBusService

  phosphor-* 的 handleMethodCall() 
  → BaseDBusService.on_method_xxx()

  phosphor-* 的 emit_property_changed()
  → BaseDBusService.emit_signal()

使用方式：

    class ThumbnailService(BaseDBusService):
        BUS_NAME = 'com.dplayer.thumbnail'
        INTERFACES = ['com.dplayer.Thumbnail']
        OBJECT_PATH = '/com/dplayer/thumbnail'

        def on_method_generate(self, params):
            # 处理 Generate 方法调用
            video_hash = params.get('video_hash')
            # ... 生成缩略图 ...
            return {'success': True, 'task_id': 'xxx'}

        def on_method_get_status(self, params):
            return {'status': 'ready'}

    # 启动服务
    service = ThumbnailService()
    service.start()
"""

import threading
import traceback
from typing import Dict, Any, Optional, List

import zmq

from .protocol import BusMessage, MessageType
from .bus import BusEndpoint, DEFAULT_HOST, DEFAULT_RPC_PORT, DEFAULT_PUB_PORT


class BaseDBusService:
    """
    服务基类 — 模拟 phosphor-* 服务的通用模式

    子类只需要：
    1. 定义 BUS_NAME、INTERFACES、OBJECT_PATH
    2. 实现 on_method_xxx() 方法处理对应的 D-Bus 方法调用
    3. 调用 self.emit_signal() 发出信号

    生命周期：
      start()     → 连接总线、启动监听线程
      stop()      → 断开连接、停止监听
      running     → 是否在运行
    """

    # 子类必须定义
    BUS_NAME: str = ""            # D-Bus 服务名，如 'com.dplayer.thumbnail'
    INTERFACES: List[str] = []   # 支持的接口列表
    OBJECT_PATH: str = ""        # D-Bus 对象路径，如 '/com/dplayer/thumbnail'

    def __init__(self, host: str = DEFAULT_HOST,
                 rpc_port: int = DEFAULT_RPC_PORT,
                 pub_port: int = DEFAULT_PUB_PORT):
        if not self.BUS_NAME:
            raise ValueError(f"{self.__class__.__name__}: BUS_NAME 未定义")

        self._host = host
        self._rpc_port = rpc_port
        self._pub_port = pub_port
        self._running = False
        self._endpoint: Optional[BusEndpoint] = None
        self._dealer: Optional[zmq.Socket] = None
        self._ctx: Optional[zmq.Context] = None
        self._recv_thread: Optional[threading.Thread] = None
        self._publisher: Optional[zmq.Socket] = None
        self._pub_port_actual: Optional[int] = None

    def start(self, block: bool = False):
        """
        启动服务 — 连接总线并开始监听

        模拟 phosphor-* 服务启动时连接 D-Bus System Bus。

        Args:
            block: 是否阻塞（True=在当前线程中运行，False=后台线程）
        """
        self._ctx = zmq.Context()

        # ROUTER socket：接收方法调用请求（充当服务端）
        self._dealer = self._ctx.socket(zmq.DEALER)
        self._dealer.setsockopt_string(zmq.IDENTITY, self.BUS_NAME)
        self._dealer.connect(f"tcp://{self._host}:{self._rpc_port}")

        # 发送 HELLO 消息注册到总线（模拟 D-Bus bus.request_name()）
        hello_msg = BusMessage.hello(self.BUS_NAME, self.INTERFACES)
        self._dealer.send(hello_msg.to_json())

        # PUB socket：发送信号
        self._publisher = self._ctx.socket(zmq.PUB)
        self._pub_port_actual = self._publisher.bind_to_random_port(
            f"tcp://{self._host}")

        self._running = True

        if block:
            self._recv_loop()
        else:
            self._recv_thread = threading.Thread(
                target=self._recv_loop, daemon=True, name=f"bus-{self.BUS_NAME}")
            self._recv_thread.start()

    def stop(self):
        """停止服务"""
        self._running = False
        if self._dealer:
            self._dealer.close(linger=0)
        if self._publisher:
            self._publisher.close(linger=0)
        if self._ctx:
            self._ctx.term()

    @property
    def running(self) -> bool:
        return self._running

    def call_method(self, service: str, interface: str, method: str,
                    params: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """
        调用其他服务的方法（便捷方法）

        使用服务自己的 DEALER socket 发送方法调用，
        不需要额外的 BusClient 实例。

        模拟 phosphor-* 服务之间通过 D-Bus 互相调用。
        """
        if not self._dealer:
            raise RuntimeError("服务未启动，请先调用 start()")

        # 创建临时 DEALER socket（避免和 _recv_loop 冲突）
        caller = self._ctx.socket(zmq.DEALER)
        caller.setsockopt_string(zmq.IDENTITY, f"{self.BUS_NAME}.caller.{method}")
        caller.connect(f"tcp://{self._host}:{self._rpc_port}")

        try:
            msg = BusMessage.method_call(service, interface, method, params)
            msg.sender = self.BUS_NAME
            caller.send(msg.to_json())

            # 同步等待回复（带超时）
            # ROUTER → DEALER 是 3 帧：[identity, empty, data]
            if caller.poll(timeout=5000):
                frames = caller.recv_multipart()
                # 取最后一帧（消息数据）
                reply_data = frames[-1] if frames else None
                if reply_data:
                    reply = BusMessage.from_json(reply_data)
                    if reply.type == MessageType.ERROR:
                        raise RuntimeError(f"Bus error from {service}: {reply.error}")
                    return reply.result
            return None
        finally:
            caller.close(linger=0)

    def emit_signal(self, interface: str, signal_name: str,
                    signal_data: Dict[str, Any] = None,
                    path: str = ""):
        """
        发出信号 — 模拟 D-Bus 的 emit_signal()

        类似 phosphor-* 服务中的：
          emit_property_changed(sdbusplus::com::dplayer::Thumbnail::Thumbnails::taskStatus(), newStatus)

        示例：
          self.emit_signal('com.dplayer.Thumbnail', 'ThumbnailGenerated',
                          {'video_hash': 'abc123', 'path': '/data/thumbnails/abc123.gif'})
        """
        if not self._publisher:
            raise RuntimeError("服务未启动，请先调用 start()")

        msg = BusMessage.signal(self.BUS_NAME, interface, signal_name,
                                path or self.OBJECT_PATH, signal_data)
        self._publisher.send(msg.to_json())

    def _recv_loop(self):
        """
        接收循环 — 监听方法调用并分发

        模拟 D-Bus 的消息分发机制：
          1. 收到 METHOD_CALL → 查找 on_method_xxx 处理器 → 调用 → 回复
          2. 收到 SIGNAL → 查找 on_signal_xxx 处理器 → 调用
        """
        poller = zmq.Poller()
        poller.register(self._dealer, zmq.POLLIN)

        while self._running:
            try:
                events = dict(poller.poll(1000))
                for sock, mask in events.items():
                    if mask & zmq.POLLIN:
                        frames = sock.recv_multipart()
                        # ROUTER → DEALER: [identity, empty, data]（3帧）
                        if len(frames) >= 2:
                            msg_data = frames[-1]
                            try:
                                msg = BusMessage.from_json(msg_data)
                                self._dispatch_message(msg)
                            except Exception:
                                import traceback
                                traceback.print_exc()
            except zmq.ZMQError:
                break
            except Exception:
                pass

    def _dispatch_message(self, msg: BusMessage):
        """分发消息到对应的处理器"""
        if msg.type == MessageType.METHOD_CALL:
            # 方法调用 → 查找 on_method_xxx 处理器
            handler_name = f"on_method_{_to_snake_case(msg.member)}"
            handler = getattr(self, handler_name, None)
            if handler:
                try:
                    result = handler(msg.params)
                    reply = BusMessage.method_reply(msg, result or {})
                    self._dealer.send(reply.to_json())
                except Exception as e:
                    error_reply = BusMessage.error_reply(msg, str(e))
                    self._dealer.send(error_reply.to_json())
            else:
                error_reply = BusMessage.error_reply(
                    msg, f"未知方法: {msg.member}")
                self._dealer.send(error_reply.to_json())

        elif msg.type == MessageType.SIGNAL:
            # 信号 → 查找 on_signal_xxx 处理器
            handler_name = f"on_signal_{_to_snake_case(msg.member)}"
            handler = getattr(self, handler_name, None)
            if handler:
                try:
                    handler(msg.signal_data, msg)
                except Exception:
                    pass

        elif msg.type == MessageType.METHOD_REPLY or msg.type == MessageType.ERROR:
            # 回复消息 → 由 call_method 的 poll 处理
            pass


def _to_snake_case(name: str) -> str:
    """将 CamelCase/ PascalCase 转为 snake_case"""
    import re
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
