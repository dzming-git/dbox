# -*- coding: utf-8 -*-
"""
BusRouter - 总线路由守护进程

模拟 D-Bus 的 dbus-daemon，负责消息路由。

架构：
  BusRouter (ROUTER)  ←→  Service A (DEALER)
                     ←→  Service B (DEALER)
                     ←→  Service C (DEALER)

  BusRouter (PUB)    →  Service A (SUB)
                    →  Service B (SUB)
                    →  Service C (SUB)

D-Bus 对应：
  BusRouter  →  dbus-daemon / dbus-broker
  启动方式    →  DBUS_SYSTEM_BUS_ADDRESS=... dbus-daemon

使用方式：

    from servicebus import BusRouter
    router = BusRouter()
    router.start()  # 后台运行

    # 或阻塞运行（测试用）
    router.run()    # 阻塞
"""

import threading
import traceback
from typing import Dict, Optional

import zmq

from .protocol import BusMessage, MessageType
from .bus import DEFAULT_HOST, DEFAULT_RPC_PORT, DEFAULT_PUB_PORT, ServiceRegistry


# ============ 默认配置 ============
_REPLY_TIMEOUT = 10  # 跟踪回复的时间窗口（秒）


class BusRouter:
    """
    总线路由器 — 消息转发中心

    职责：
    1. 接收所有服务的消息（ROUTER socket）
    2. 根据目标服务名转发 METHOD_CALL
    3. 将 SIGNAL 广播给所有连接的服务
    4. 管理服务注册表（HELLO / 心跳）
    """

    def __init__(self, host: str = DEFAULT_HOST,
                 rpc_port: int = DEFAULT_RPC_PORT,
                 pub_port: int = DEFAULT_PUB_PORT):
        self._host = host
        self._rpc_port = rpc_port
        self._pub_port = pub_port
        self._rpc_addr = f"tcp://{host}:{rpc_port}"
        self._pub_addr = f"tcp://{host}:{pub_port}"

        self._ctx: Optional[zmq.Context] = None
        self._router: Optional[zmq.Socket] = None
        self._publisher: Optional[zmq.Socket] = None
        self._registry = ServiceRegistry()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        # 跟踪 METHOD_CALL 的 sender_identity，用于路由回复
        self._pending_calls: Dict[str, bytes] = {}  # msg_id → sender_identity

    def start(self):
        """后台启动路由器"""
        self._init_sockets()
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="bus-router")
        self._thread.start()

    def run(self):
        """阻塞运行路由器（主要用于测试）"""
        self._init_sockets()
        self._running = True
        self._run()

    def stop(self):
        """停止路由器"""
        self._running = False
        if self._router:
            self._router.close(linger=0)
        if self._publisher:
            self._publisher.close(linger=0)
        if self._ctx:
            self._ctx.term()

    def list_services(self):
        """列出已注册服务"""
        return self._registry.list_services()

    def _init_sockets(self):
        """初始化 ZeroMQ socket"""
        self._ctx = zmq.Context()

        # ROUTER socket：接收和转发消息
        self._router = self._ctx.socket(zmq.ROUTER)
        self._router.bind(self._rpc_addr)

        # PUB socket：广播信号
        self._publisher = self._ctx.socket(zmq.PUB)
        self._publisher.bind(self._pub_addr)

    def _run(self):
        """主路由循环"""
        poller = zmq.Poller()
        poller.register(self._router, zmq.POLLIN)

        while self._running:
            try:
                events = dict(poller.poll(1000))
                for sock, mask in events.items():
                    if mask & zmq.POLLIN:
                        try:
                            # ROUTER 消息格式：[identity, ... , data]
                            # DEALER → ROUTER: [identity, data]（2帧）
                            # ROUTER → DEALER: [identity, empty, data]（3帧）
                            frames = sock.recv_multipart()
                            if len(frames) >= 2:
                                sender_identity = frames[0]
                                # 最后一帧是消息数据
                                msg_data = frames[-1]
                                msg = BusMessage.from_json(msg_data)
                                self._route(sender_identity, msg)
                        except Exception:
                            traceback.print_exc()
            except zmq.ZMQError:
                break
            except Exception:
                pass

    def _route(self, sender_identity: bytes, msg: BusMessage):
        """
        路由消息

        模拟 dbus-daemon 的消息路由逻辑：
        - HELLO → 注册服务
        - METHOD_CALL → 转发到目标服务
        - METHOD_REPLY / ERROR → 转发到调用者
        - SIGNAL → 广播给所有服务
        """
        msg_type = msg.type

        if msg_type == MessageType.HELLO:
            # 服务注册（周期性 HELLO 会重复调用，仅在首次或 identity 变化时打印）
            sender = msg.sender or msg.params.get('service', '')
            interfaces = msg.params.get('interfaces', [])
            is_new = not self._registry.has_service(sender)
            self._registry.register(sender, sender_identity, interfaces)
            if is_new:
                print(f"[BusRouter] 服务注册: {sender} (interfaces: {interfaces})")

        elif msg_type == MessageType.METHOD_CALL:
            # 方法调用 → 转发到目标服务
            target = msg.service
            target_identity = self._registry.get_identity(target)
            # 记录调用者的 identity（用于路由回复）
            self._pending_calls[msg.id] = sender_identity
            if target_identity:
                # 转发消息：[target_identity, empty, data]
                # ROUTER → DEALER 需要 3 帧
                self._router.send_multipart([
                    target_identity,
                    b'',
                    msg.to_json()
                ])
            else:
                # 目标服务不存在 → 回复错误
                reply = BusMessage.error_reply(msg, f"服务不存在: {target}")
                self._router.send_multipart([
                    sender_identity,
                    b'',
                    reply.to_json()
                ])

        elif msg_type in (MessageType.METHOD_REPLY, MessageType.ERROR):
            # 回复 → 使用记录的 sender_identity 路由
            caller_identity = self._pending_calls.pop(msg.id, None)
            if caller_identity:
                self._router.send_multipart([
                    caller_identity,
                    b'',
                    msg.to_json()
                ])
            # 如果没有记录，尝试通过 service name 查找（兼容旧模式）
            elif msg.service:
                target_identity = self._registry.get_identity(msg.service)
                if target_identity:
                    self._router.send_multipart([
                        target_identity,
                        b'',
                        msg.to_json()
                    ])

        elif msg_type == MessageType.SIGNAL:
            # 信号 → 广播给所有已注册服务（除发送者外）
            self._publisher.send(msg.to_json())

        elif msg_type == MessageType.HEARTBEAT:
            # 心跳 → 更新注册表
            sender = msg.sender
            if sender:
                self._registry.update_heartbeat(sender)

        elif msg_type == MessageType.DISCOVER:
            # 服务发现 → 回复服务列表
            services = self._registry.list_services()
            reply = BusMessage(
                type=MessageType.DISCOVER_REPLY,
                id=msg.id,
                service=msg.sender,
                sender="com.dbox.bus",
                result={"services": services}
            )
            self._router.send_multipart([
                sender_identity,
                b'',
                reply.to_json()
            ])
