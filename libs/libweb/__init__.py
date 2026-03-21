# -*- coding: utf-8 -*-
"""
LibWeb - 异步请求处理框架 (原NodeManager)

提供基于Node的异步请求处理架构，支持：
- TaskContext: 异步任务上下文管理
- ContextPool: 任务上下文对象池
- Node: 异步请求处理基类
- NodeManager: 路由注册与请求分发

子模块：
- nodes: 预定义的Node实现（包含所有API路由）
- middleware: 中间件（认证、会话、日志、指标）
- adapters: 适配器（Flask）
- handlers: 处理器（异步、优先级）

使用示例：
    from libweb import NodeManager, FlaskAdapter
    from libweb.nodes import register_all_routes

    nm = NodeManager()
    register_all_routes(nm)  # 注册所有API路由

    adapter = FlaskAdapter(nm)
    adapter.register_to_flask(app)  # 集成到Flask
"""

# 核心模块
from .core import (
    TaskContext,
    ContextPool,
    Node,
    NodeManager,
)

# 节点模块
from .nodes import (
    HealthNode,
    register_all_routes,
    get_registered_routes_count,
)

# 中间件模块
from .middleware import (
    AuthMiddleware,
    SessionManager,
    LoggingMiddleware,
    MetricsCollector,
)

# 适配器模块
from .adapters import (
    FlaskAdapter,
    DualRouter,
)

# 处理器模块
from .handlers import (
    AsyncRequestHandler,
    PriorityContextPool,
)

__all__ = [
    # 核心
    'TaskContext',
    'ContextPool',
    'Node',
    'NodeManager',
    # 节点
    'HealthNode',
    'register_all_routes',
    'get_registered_routes_count',
    # 中间件
    'AuthMiddleware',
    'SessionManager',
    'LoggingMiddleware',
    'MetricsCollector',
    # 适配器
    'FlaskAdapter',
    'DualRouter',
    # 处理器
    'AsyncRequestHandler',
    'PriorityContextPool',
]

__version__ = '1.2.0'
