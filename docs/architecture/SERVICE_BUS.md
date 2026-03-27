# ServiceBus - 内部服务总线

基于 OpenBMC D-Bus 架构思想，用纯 Python + ZeroMQ 实现的内部服务通信框架。

## 架构对照

| OpenBMC D-Bus | ServiceBus 实现 |
|---|---|
| dbus-daemon | BusRouter（ROUTER/PUB 模式） |
| phosphor-* 服务 | BaseDBusService（DEALER/SUB 模式） |
| bmcweb | BusClient / BaseDBusService（调用方） |
| D-Bus Method Call | call_method()（ROUTER↔DEALER） |
| D-Bus Signal | emit_signal() + on_signal()（PUB↔SUB） |
| D-Bus 服务注册 | HELLO 消息（启动时发送） |
| D-Bus ListNames | list_services()（服务注册表） |

## 目录结构

```
src/servicebus/
├── __init__.py          # 包入口，导出核心类
├── protocol.py          # 消息协议（JSON 格式，模拟 D-Bus Message）
├── bus.py               # BusEndpoint（底层 ZeroMQ 封装）
├── router.py           # BusRouter（消息路由守护进程）
├── service_base.py     # BaseDBusService（服务基类，phosphor-* 风格）
├── client.py           # BusClient（调用端，bmcweb 风格）
└── thumbnail_adapter.py # BusThumbnailAdapter（缩略图服务适配器）
```

## 快速开始

### 1. 启动总线路由器

```python
from servicebus import BusRouter

router = BusRouter(rpc_port=15555, pub_port=15556)
router.start()  # 后台运行
```

### 2. 创建服务（phosphor-* 风格）

```python
from servicebus import BaseDBusService

class ThumbnailService(BaseDBusService):
    BUS_NAME = 'com.dplayer.thumbnail'
    INTERFACES = ['com.dplayer.Thumbnail']
    OBJECT_PATH = '/com/dplayer/thumbnail'

    def on_method_generate(self, params):
        video_hash = params.get('video_hash')
        return {'success': True, 'task_id': 'xxx'}

    def on_method_health_check(self, params):
        return {'status': 'healthy'}

# 启动服务（连接总线并注册）
svc = ThumbnailService(rpc_port=15555, pub_port=15556)
svc.start()
```

### 3. 调用远程服务方法（bmcweb 风格）

```python
from servicebus import BusClient

client = BusClient('com.dplayer.web')
client.connect()

# 同步方法调用
result = client.call_method(
    service='com.dplayer.thumbnail',
    interface='com.dplayer.Thumbnail',
    method='Generate',
    params={'video_hash': 'abc123', 'video_path': '/video.mp4'}
)
print(result)  # {'success': True, 'task_id': 'xxx'}
```

### 4. 发送和接收信号

```python
# 发送信号（类似 phosphor-* 的 emit_property_changed）
svc.emit_signal(
    'com.dplayer.Thumbnail',
    'ThumbnailGenerated',
    {'video_hash': 'abc123', 'path': '/data/thumbnails/abc123.gif'}
)

# 接收信号
client.on_signal(
    'com.dplayer.Thumbnail',
    'ThumbnailGenerated',
    lambda data, msg: print(f"收到信号: {data}")
)
```

## 通信协议

消息格式（JSON over ZeroMQ）：

```json
{
  "type": "method_call | method_reply | signal | error | hello",
  "id": "msg-uuid",
  "timestamp": "2026-03-27T01:00:00",
  "service": "com.dplayer.thumbnail",
  "sender": "com.dplayer.web",
  "interface": "com.dplayer.Thumbnail",
  "path": "/com/dplayer/thumbnail",
  "member": "Generate",
  "params": {"video_hash": "abc123"},
  "result": {"success": true, "task_id": "xxx"},
  "error": "",
  "signal_data": {}
}
```

### 端口规划

| 端口 | 用途 |
|------|------|
| 15555 | RPC（ROUTER/DEALER，方法调用） |
| 15556 | PUB/SUB（信号广播） |

可通过环境变量覆盖：
```bash
set DPLAYER_BUS_RPC_PORT=15555
set DPLAYER_BUS_PUB_PORT=15556
```

## ZeroMQ 帧格式

- DEALER → ROUTER：**2 帧** `[identity, data]`
- ROUTER → DEALER：**3 帧** `[identity, empty, data]`
- PUB → SUB：**1 帧** `[data]`

## 依赖

```
pip install pyzmq
```

## 运行测试

```bash
python tests/test_servicebus.py
```

预期输出：
```
============================================================
  ServiceBus 集成测试
  模拟 OpenBMC D-Bus 通信模式
============================================================

[测试1] 协议消息序列化/反序列化          [OK] 通过
[测试2] 方法调用                        [OK] 通过
[测试3] 信号广播                        [OK] 通过
[测试4] 服务注册和发现                  [OK] 通过
[测试5] 错误处理                        [OK] 通过

  测试结果: 5 通过, 0 失败
============================================================
```
