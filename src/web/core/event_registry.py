"""事件注册中心（Event Registry）。

设计目标：高自由度的事件体系。
- 任何服务模块都可以在自己的初始化代码中调用 register_event(...) 自由注册事件，
  无需在监听器框架中硬编码。
- 事件只描述「发生了什么」以及「如何被监听器探测到（probe）」，
  不绑定任何具体处理逻辑（handler 由用户在配置中独立指定）。
- 监听器（独立 NSSM 进程）与 Web 主进程共享同一份注册表文件（data/event_registry.json），
  因此监听器能发现所有已注册事件并据此轮询。

事件定义字段：
  name       事件唯一名，如 feedback.status_changed / service.status_changed
  description 人类可读描述
  probe      状态探针名（监听器据此拉取实体状态快照做 diff），如 feedback / service
  params     触发时传给 handler 的参数键列表（从实体快照 + 变化信息中取值）
  source     注册该事件的服务/模块名（仅用于展示）

示例（反馈服务在启动时注册）：
  register_event(
      name='feedback.status_changed',
      description='反馈状态发生变化',
      probe='feedback',
      params=['issue_id', 'old_status', 'new_status', 'title', 'category'],
      source='feedback',
  )

示例（服务管理模块注册）：
  register_event(
      name='service.status_changed',
      description='服务运行状态发生变化',
      probe='service',
      params=['service_key', 'old_status', 'new_status'],
      source='service',
  )
"""
import os
import json
import threading

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    'data',
)
_REGISTRY_PATH = os.path.join(_DATA_DIR, 'event_registry.json')

_lock = threading.Lock()


def _ensure_dir():
    os.makedirs(_DATA_DIR, exist_ok=True)


def _load():
    if not os.path.exists(_REGISTRY_PATH):
        return {}
    try:
        with open(_REGISTRY_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save(registry):
    _ensure_dir()
    tmp = _REGISTRY_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _REGISTRY_PATH)


def register_event(name, description, probe, params=None, source=None, extra=None):
    """注册（或更新）一个事件。幂等：重复注册以最新调用为准。

    Args:
        name: 事件唯一名
        description: 描述
        probe: 探针名（监听器据此探测状态变化）
        params: list[str]，触发时传给 handler 的参数键
        source: 注册来源（服务/模块名），可选
        extra: dict，附加元信息，可选
    """
    if not name or not isinstance(name, str):
        raise ValueError('event name required')
    if not probe:
        raise ValueError('event probe required')
    ev = {
        'name': name,
        'description': description or '',
        'probe': probe,
        'params': list(params) if params else [],
        'source': source or '',
    }
    if extra:
        ev['extra'] = extra
    with _lock:
        reg = _load()
        reg[name] = ev
        _save(reg)
    return ev


def unregister_event(name):
    with _lock:
        reg = _load()
        if name in reg:
            del reg[name]
            _save(reg)
            return True
    return False


def get_event(name):
    with _lock:
        return _load().get(name)


def list_events():
    with _lock:
        return list(_load().values())


def clear_events():
    with _lock:
        _save({})
