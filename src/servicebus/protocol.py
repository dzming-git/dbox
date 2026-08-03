# -*- coding: utf-8 -*-
"""
ServiceBus 通信协议定义

模拟 D-Bus 消息格式，使用 JSON 序列化。

D-Bus 消息类型映射：
  - METHOD_CALL  → 同步请求/回复（类似 D-Bus Method Call）
  - METHOD_REPLY → 方法调用的回复
  - SIGNAL       → 广播信号（类似 D-Bus Signal）
  - ERROR        → 错误回复
  - HELLO        → 服务注册握手
  - HEARTBEAT    → 心跳检测

D-Bus 地址映射：
  - com.dbox.web        → Web 服务
  - com.dbox.thumbnail  → 缩略图服务
  - com.dbox.webui      → WebUI 服务（未来）
  - com.dbox.*          → 未来扩展

消息格式（JSON）：
  {
    "type": "method_call|method_reply|signal|error|hello|heartbeat",
    "id": "uuid-string",                    // 消息唯一 ID
    "timestamp": "2026-03-27T01:00:00",    // 时间戳
    "service": "com.dbox.thumbnail",     // 目标服务名（method_call）
    "sender": "com.dbox.web",           // 发送者服务名（reply/signal）
    "interface": "com.dbox.Thumbnail",  // D-Bus 接口名
    "path": "/com/dbox/thumbnail",      // D-Bus 对象路径
    "member": "Generate",                   // 方法名或信号名
    "params": { ... },                      // 方法参数
    "result": { ... },                      // 方法返回值（reply）
    "error": "error message",               // 错误信息（error）
    "signal_data": { ... },                 // 信号数据（signal）
  }
"""

import json
import time
import uuid
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, Any, Dict


class MessageType(str, Enum):
    """消息类型，模拟 D-Bus 消息类型"""
    METHOD_CALL = "method_call"      # 方法调用（请求）
    METHOD_REPLY = "method_reply"    # 方法回复
    SIGNAL = "signal"                # 信号广播
    ERROR = "error"                  # 错误回复
    HELLO = "hello"                  # 服务注册握手
    HEARTBEAT = "heartbeat"          # 心跳检测
    DISCOVER = "discover"            # 服务发现请求
    DISCOVER_REPLY = "discover_reply"  # 服务发现回复


@dataclass
class BusMessage:
    """
    总线消息，模拟 D-Bus Message。

    每条消息包含完整的路由信息，类似 D-Bus 消息的
    destination、sender、interface、path、member 等字段。
    """
    type: str
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: time.strftime('%Y-%m-%dT%H:%M:%S'))
    service: str = ""                    # 目标服务（method_call 时使用）
    sender: str = ""                     # 发送者（reply/signal 时使用）
    interface: str = ""                  # D-Bus 接口名
    path: str = ""                       # D-Bus 对象路径
    member: str = ""                     # 方法名或信号名
    params: Dict[str, Any] = field(default_factory=dict)    # 方法参数
    result: Dict[str, Any] = field(default_factory=dict)    # 方法返回值
    error: str = ""                      # 错误信息
    signal_data: Dict[str, Any] = field(default_factory=dict)  # 信号数据

    def to_json(self) -> bytes:
        """序列化为 JSON bytes（ZeroMQ 传输格式）"""
        return json.dumps(asdict(self), ensure_ascii=False).encode('utf-8')

    @classmethod
    def from_json(cls, data: bytes) -> 'BusMessage':
        """从 JSON bytes 反序列化"""
        d = json.loads(data.decode('utf-8'))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def method_call(cls, service: str, interface: str, member: str,
                    params: Dict[str, Any] = None) -> 'BusMessage':
        """创建方法调用消息（模拟 dbus-python 的 method_call）"""
        path = f"/{service.replace('.', '/')}"
        return cls(
            type=MessageType.METHOD_CALL,
            service=service,
            interface=interface,
            path=path,
            member=member,
            params=params or {}
        )

    @classmethod
    def create_method_call(cls, service: str, interface: str, method: str,
                           params: Dict[str, Any] = None) -> 'BusMessage':
        """创建方法调用消息（method 作为 member 的别名，更直观）"""
        return cls.method_call(service, interface, method, params)

    @classmethod
    def method_reply(cls, request: 'BusMessage', result: Dict[str, Any] = None) -> 'BusMessage':
        """创建方法回复消息"""
        return cls(
            type=MessageType.METHOD_REPLY,
            id=request.id,
            service=request.sender,
            sender=request.service,
            interface=request.interface,
            path=request.path,
            member=request.member,
            result=result or {}
        )

    @classmethod
    def error_reply(cls, request: 'BusMessage', error: str) -> 'BusMessage':
        """创建错误回复消息"""
        return cls(
            type=MessageType.ERROR,
            id=request.id,
            service=request.sender,
            sender=request.service,
            interface=request.interface,
            path=request.path,
            member=request.member,
            error=error
        )

    @classmethod
    def signal(cls, sender: str, interface: str, member: str,
               path: str = "", signal_data: Dict[str, Any] = None) -> 'BusMessage':
        """创建信号广播消息（模拟 D-Bus Signal）"""
        if not path:
            path = f"/{sender.replace('.', '/')}"
        return cls(
            type=MessageType.SIGNAL,
            sender=sender,
            interface=interface,
            path=path,
            member=member,
            signal_data=signal_data or {}
        )

    @classmethod
    def hello(cls, service: str, interfaces: list = None) -> 'BusMessage':
        """创建服务注册握手消息"""
        return cls(
            type=MessageType.HELLO,
            sender=service,
            params={"interfaces": interfaces or []}
        )

    @classmethod
    def heartbeat(cls, service: str) -> 'BusMessage':
        """创建心跳消息"""
        return cls(
            type=MessageType.HEARTBEAT,
            sender=service
        )

    def __repr__(self):
        return (f"BusMessage(type={self.type}, id={self.id}, "
                f"service={self.service}, member={self.member})")
