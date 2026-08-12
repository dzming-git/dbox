# -*- coding: utf-8 -*-
"""
ServiceBus - 内部服务总线核心实现

模拟 OpenBMC 的 D-Bus 系统总线，提供：
- ROUTER/DEALER 模式：方法调用（同步请求/回复）
- PUB/SUB 模式：信号广播（发布/订阅）
- 服务注册表：服务发现和健康监控

D-Bus 映射对照：
  D-Bus System Bus     →  ServiceBus (ZeroMQ)
  dbus-daemon          →  ServiceBus._daemon_loop()
  bus.register_service  →  ServiceBus.register_service()
  bus.send_signal()     →  ServiceBus.broadcast_signal()
  bus.call_method()     →  通过 BusClient

端口规划（模拟 D-Bus 地址）：
  RPC 端口：tcp://127.0.0.1:15555（ROUTER/DEALER，方法调用）
  PUB 端口：tcp://127.0.0.1:15556（PUB/SUB，信号广播）
"""

import os
import sys
import time
import threading
from typing import Dict, List, Optional, Callable, Any

import zmq

from .protocol import BusMessage, MessageType


# ============ 默认配置 ============
DEFAULT_RPC_PORT = int(os.getenv('DBOX_BUS_RPC_PORT', '15555'))
DEFAULT_PUB_PORT = int(os.getenv('DBOX_BUS_PUB_PORT', '15556'))
DEFAULT_HOST = os.getenv('DBOX_BUS_HOST', '127.0.0.1')
RPC_TIMEOUT = int(os.getenv('DBOX_BUS_TIMEOUT', '5000'))  # ms


class ServiceRegistry:
    """
    服务注册表 — 模拟 D-Bus 的服务名注册

    当服务发送 HELLO 消息后，注册到总线。
    其他服务可以通过服务名查找目标地址。

    D-Bus 对应：
      org.freedesktop.DBus.ListNames() → list_services()
      org.freedesktop.DBus.NameHasOwner() → has_service()
    """

    def __init__(self):
        self._services: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def register(self, service_name: str, dealer_identity: bytes,
                 interfaces: list = None):
        """注册服务"""
        with self._lock:
            self._services[service_name] = {
                'identity': dealer_identity,
                'interfaces': interfaces or [],
                'registered_at': time.time(),
                'last_heartbeat': time.time(),
            }

    def unregister(self, service_name: str):
        """注销服务"""
        with self._lock:
            self._services.pop(service_name, None)

    def has_service(self, service_name: str) -> bool:
        """检查服务是否存在"""
        with self._lock:
            return service_name in self._services

    def get_identity(self, service_name: str) -> Optional[bytes]:
        """获取服务的 DEALER identity"""
        with self._lock:
            entry = self._services.get(service_name)
            return entry['identity'] if entry else None

    def list_services(self) -> List[str]:
        """列出所有已注册服务"""
        with self._lock:
            return list(self._services.keys())

    def get_service_info(self, service_name: str) -> Optional[dict]:
        """获取服务详细信息"""
        with self._lock:
            return dict(self._services.get(service_name, {}))

    def update_heartbeat(self, service_name: str):
        """更新服务心跳时间"""
        with self._lock:
            entry = self._services.get(service_name)
            if entry:
                entry['last_heartbeat'] = time.time()


class ServiceBus:
    """
    内部服务总线 — 模拟 D-Bus System Bus

    两种使用模式：
    1. 独立守护进程模式（推荐生产用）：ServiceBus.run_daemon()
    2. 内嵌模式（开发用）：每个服务自带 BusClient，无需 daemon

    当前实现使用内嵌模式 — 服务之间直接通过 ZeroMQ 通信，
    不需要单独的 daemon 进程。

    D-Bus 对应：
      ServiceBus              →  dbus-daemon
      register_service()      →  bus.request_name()
      broadcast_signal()      →  bus.emit_signal()
      call_method()           →  proxy.call_async()
    """

    def __init__(self, rpc_port: int = DEFAULT_RPC_PORT,
                 pub_port: int = DEFAULT_PUB_PORT,
                 host: str = DEFAULT_HOST):
        self.rpc_port = rpc_port
        self.pub_port = pub_port
        self.host = host
        self.rpc_addr = f"tcp://{host}:{rpc_port}"
        self.pub_addr = f"tcp://{host}:{pub_port}"

        self._ctx: Optional[zmq.Context] = None
        self._registry = ServiceRegistry()
        self._running = False
        self._daemon_thread: Optional[threading.Thread] = None
        self._signal_subscribers: Dict[str, Callable] = {}
        self._subscribers_lock = threading.Lock()

    @staticmethod
    def register_service(service_name: str, interfaces: list = None, *,
                         handler: callable = None, object_path: str = "",
                         host: str = DEFAULT_HOST,
                         rpc_port: int = DEFAULT_RPC_PORT,
                         pub_port: int = DEFAULT_PUB_PORT,
                         auto_start: bool = True):
        """
        注册一个服务到总线（静态方法，便捷 API），返回已注册的服务实例。

        模拟 D-Bus 的 ``bus.request_name()`` + 启动监听线程。调用方无需手动
        编写 ``BaseDBusService`` 子类，一行即可上线一个可被其它进程发现的 D-Bus
        风格服务。

        参数
        ----
        service_name : str
            服务名（Bus Name），如 ``com.dbox.thumbnail``。
        interfaces : list[str]
            该服务声明的接口名列表，如 ``['com.dbox.Thumbnail']``；用于 HELLO 注册。
        handler : callable | None
            方法分发处理器，签名 ``handler(method: str, params: dict) -> dict``。
            省略时服务仍会完成注册并响应一个内置 ``Ping`` 探活方法（返回
            ``{'success': True, 'pong': True}``），便于健康检查。
        object_path : str
            对象路径（D-Bus Object Path）；空字符串时回退为
            ``/com/dbox/<service_name 末段>``。
        host / rpc_port / pub_port :
            总线地址（与 ``BaseDBusService`` 一致）。
        auto_start : bool
            是否立即 ``start()`` 启动监听（默认 True）。

        返回
        ----
        BaseDBusService
            已 HELLO 注册、监听线程已启动（auto_start=True）的服务实例。
            可通过 ``svc.running`` 判断存活、``svc.stop()`` 下线。

        典型用法
        --------
        >>> svc = ServiceBus.register_service(
        ...     "com.example.MySvc",
        ...     interfaces=["com.example.MySvc"],
        ...     handler=lambda m, p: {"success": True, "result": "ok"} if m == "DoWork" else None,
        ... )
        >>> # svc 已上线：其它进程可经 BusRouter 发现并调用 DoWork
        """
        # 内置探活：未提供 handler 时仍能响应 Ping（健康检查 / 就绪探测）
        def _default_handler(method, params):
            if method == "Ping":
                return {"success": True, "pong": True, "service": service_name}
            return None

        _handler = handler or _default_handler
        _interfaces = list(interfaces or [service_name])

        # 延迟导入避免 service_base <-> bus 的循环依赖
        from .service_base import BaseDBusService

        # 动态构造匿名子类：把每个接口声明与统一 handler 分发挂上去
        import re as _re

        def _snake(name: str) -> str:
            s1 = _re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
            return _re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

        def _make_on_method(method_name):
            def _on(self, params):
                return _handler(method_name, params or {})
            _on.__name__ = f"on_method_{_snake(method_name)}"
            return _on

        # 默认支持的方法：handler 可能响应的任意方法名无法在类层面穷举，
        # 因此额外挂一个通配处理器——通过重写 _dispatch_message 实现。
        ns = {
            "BUS_NAME": service_name,
            "INTERFACES": _interfaces,
            "OBJECT_PATH": object_path or ("/com/dbox/" + service_name.split(".")[-1]
                                           if "." in service_name else "/" + service_name),
        }

        # 用闭包改写分发：优先 on_method_xxx，否则交给统一 handler
        def _dispatch_message(self, msg):
            if msg.type == MessageType.METHOD_CALL:
                handler_name = f"on_method_{_snake(msg.member)}"
                h = getattr(self, handler_name, None)
                if h is not None:
                    self._executor.submit(self._execute_handler, h, msg)
                    return
                # 统一 handler 兜底（支持动态方法名）
                self._executor.submit(
                    self._execute_handler,
                    lambda params: _handler(msg.member, params),
                    msg,
                )
            elif msg.type == MessageType.SIGNAL:
                handler_name = f"on_signal_{_snake(msg.member)}"
                h = getattr(self, handler_name, None)
                if h is not None:
                    try:
                        h(msg.signal_data, msg)
                    except Exception:
                        pass
            # METHOD_REPLY / ERROR 由 call_method 的 poll 处理

        ns["_dispatch_message"] = _dispatch_message

        svc_cls = type(f"_RegisteredService_{_snake(service_name)}", (BaseDBusService,), ns)
        svc = svc_cls(host=host, rpc_port=rpc_port, pub_port=pub_port)
        if auto_start:
            svc.start()
        return svc

    def _daemon_loop(self):
        """
        总线守护线程（预留）

        在独立 daemon 模式下，此线程负责：
        1. 接收 HELLO 消息 → 注册服务
        2. 转发 METHOD_CALL → 路由到目标服务
        3. 转发 SIGNAL → 广播给所有订阅者
        4. 心跳检测 → 清理已死亡的服务
        """
        pass


class BusEndpoint:
    """
    总线端点 — 每个服务持有一个

    封装 ZeroMQ DEALER（RPC）+ SUB（信号订阅）+ PUB（信号发布）。

    D-Bus 对应：
      BusEndpoint  →  dbus.Bus / dbus.connection.Connection
      call_method  →  proxy.call()
      emit_signal  →  bus.emit_signal()
    """

    def __init__(self, service_name: str,
                 host: str = DEFAULT_HOST,
                 rpc_port: int = DEFAULT_RPC_PORT,
                 pub_port: int = DEFAULT_PUB_PORT):
        self.service_name = service_name
        self.host = host
        self.rpc_addr = f"tcp://{host}:{rpc_port}"
        self.pub_addr = f"tcp://{host}:{pub_port}"

        self._ctx = zmq.Context()
        self._dealer: Optional[zmq.Socket] = None
        self._subscriber: Optional[zmq.Socket] = None
        self._publisher: Optional[zmq.Socket] = None
        self._poller = zmq.Poller()
        self._pending_replies: Dict[str, threading.Event] = {}
        self._reply_data: Dict[str, Any] = {}
        self._signal_handlers: Dict[str, Callable] = {}
        self._lock = threading.Lock()
        self._recv_thread: Optional[threading.Thread] = None
        self._running = False

    def connect(self):
        """
        连接到总线

        模拟 D-Bus 的 Connection 到 dbus-daemon 的连接。
        """
        # DEALER socket：用于方法调用（请求/回复）
        self._dealer = self._ctx.socket(zmq.DEALER)
        self._dealer.setsockopt_string(zmq.IDENTITY, self.service_name)
        # 总线重启后由 zmq 自动重连底层 TCP，上层服务再周期重发 HELLO 完成登记
        self._dealer.setsockopt(zmq.RECONNECT_IVL, 200)
        self._dealer.setsockopt(zmq.RECONNECT_IVL_MAX, 2000)
        self._dealer.setsockopt(zmq.TCP_KEEPALIVE, 1)
        self._dealer.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 30)
        self._dealer.connect(self.rpc_addr)
        self._poller.register(self._dealer, zmq.POLLIN)

        # SUB socket：用于接收信号
        self._subscriber = self._ctx.socket(zmq.SUB)
        self._subscriber.connect(self.pub_addr)
        # 默认订阅所有消息（按需过滤）
        self._subscriber.setsockopt_string(zmq.SUBSCRIBE, "")
        self._poller.register(self._subscriber, zmq.POLLIN)

        # PUB socket：用于发送信号
        self._publisher = self._ctx.socket(zmq.PUB)
        self._publisher.bind(f"tcp://{self.host}:*")  # 自动分配端口

    def start_listening(self):
        """启动后台接收线程"""
        self._running = True
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

    def stop(self):
        """断开总线连接"""
        self._running = False
        if self._recv_thread:
            self._recv_thread.join(timeout=2)
        for sock in [self._dealer, self._subscriber, self._publisher]:
            if sock:
                sock.close(linger=0)
        self._ctx.term()

    def call_method(self, service: str, interface: str, method: str,
                    params: Dict[str, Any] = None,
                    timeout: int = RPC_TIMEOUT) -> Optional[Dict[str, Any]]:
        """
        调用远程服务方法 — 模拟 D-Bus Method Call

        类似 OpenBMC 中 bmcweb 调用 phosphor-* 服务的 D-Bus 方法。

        Args:
            service: 目标服务名，如 'com.dbox.thumbnail'
            interface: 接口名，如 'com.dbox.Thumbnail'
            method: 方法名，如 'Generate'
            params: 方法参数
            timeout: 超时（毫秒）

        Returns:
            方法返回值字典，或 None（超时/错误）
        """
        msg = BusMessage.method_call(service, interface, method, params)
        msg.sender = self.service_name

        # 注册等待回复
        reply_event = threading.Event()
        with self._lock:
            self._pending_replies[msg.id] = reply_event

        try:
            self._dealer.send(msg.to_json())
            if reply_event.wait(timeout=timeout / 1000):
                with self._lock:
                    return self._reply_data.pop(msg.id, None)
            return None
        finally:
            with self._lock:
                self._pending_replies.pop(msg.id, None)
                self._reply_data.pop(msg.id, None)

    def emit_signal(self, interface: str, signal_name: str,
                    signal_data: Dict[str, Any] = None,
                    path: str = ""):
        """
        发送信号 — 模拟 D-Bus Signal

        类似 OpenBMC 中服务发出 PropertiesChanged 信号。

        Args:
            interface: 接口名，如 'com.dbox.Thumbnail'
            signal_name: 信号名，如 'ThumbnailGenerated'
            signal_data: 信号数据
            path: 对象路径
        """
        msg = BusMessage.signal(self.service_name, interface, signal_name,
                                path, signal_data)
        self._publisher.send(msg.to_json())

    def on_signal(self, interface: str, signal_name: str,
                  handler: Callable):
        """
        注册信号处理器 — 模拟 D-Bus 的 signal.add_signal_receiver()

        Args:
            interface: 接口名
            signal_name: 信号名
            handler: 回调函数 handler(signal_data: dict)
        """
        key = f"{interface}.{signal_name}"
        with self._lock:
            self._signal_handlers[key] = handler

    def _recv_loop(self):
        """后台接收线程"""
        while self._running:
            try:
                events = dict(self._poller.poll(1000))
                for sock, mask in events.items():
                    if mask & zmq.POLLIN:
                        if sock == self._dealer:
                            # ROUTER → DEALER: [identity, empty, data]（3帧）
                            frames = sock.recv_multipart()
                            if len(frames) >= 2:
                                msg_data = frames[-1]
                                try:
                                    msg = BusMessage.from_json(msg_data)
                                    self._handle_message(msg)
                                except Exception:
                                    pass
                        else:
                            # SUB socket: 1 帧
                            data = sock.recv()
                            try:
                                msg = BusMessage.from_json(data)
                                self._handle_message(msg)
                            except Exception:
                                pass
            except zmq.ZMQError:
                break
            except Exception:
                pass

    def _handle_message(self, msg: BusMessage):
        """处理接收到的消息"""
        if msg.type == MessageType.METHOD_REPLY:
            # 方法回复 → 唤醒等待的 call_method
            with self._lock:
                event = self._pending_replies.get(msg.id)
                if event:
                    self._reply_data[msg.id] = msg.result
                    event.set()

        elif msg.type == MessageType.ERROR:
            # 错误回复
            with self._lock:
                event = self._pending_replies.get(msg.id)
                if event:
                    self._reply_data[msg.id] = {'_error': msg.error}
                    event.set()

        elif msg.type == MessageType.SIGNAL:
            # 信号 → 调用注册的 handler
            key = f"{msg.interface}.{msg.member}"
            with self._lock:
                handler = self._signal_handlers.get(key)
            if handler:
                try:
                    handler(msg.signal_data, msg)
                except Exception:
                    pass

        elif msg.type == MessageType.METHOD_CALL:
            # 方法调用 → 由 BaseDBusService 处理（这里只是接收）
            # 实际的分发逻辑在 BaseDBusService 的 _recv_loop 中
            pass
