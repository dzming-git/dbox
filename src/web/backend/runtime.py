# -*- coding: utf-8 -*-
"""运行时单例注册中心。

彻底消除 helper 模块 / 蓝图对 ``main`` 模块的依赖：所有需要运行时
单例（SQLAlchemy ``db``、Flask ``app``、配置 ``app_config``、服务总线
``thumbnail_bus`` / ``resource_bus`` 等）的代码，统一从本模块读取。

``main.py`` 在应用完全初始化（总线连接、app 创建、配置加载）之后调用
:func:`init` 注入这些单例；helper 模块在请求处理时（此时 app 已就绪）
通过模块属性访问即可，无需延迟导入，避免循环依赖。
"""


class _Runtime:
    def __init__(self):
        self.db = None
        self.app = None
        self.app_config = None
        self.thumbnail_bus = None
        self.resource_bus = None
        self.svc_mgr_bus = None
        self.history_bus = None
        self.collection_bus = None
        self.search_bus = None

    def init(self, db=None, app=None, app_config=None,
             thumbnail_bus=None, resource_bus=None, svc_mgr_bus=None,
             history_bus=None, collection_bus=None, search_bus=None):
        if db is not None:
            self.db = db
        if app is not None:
            self.app = app
        if app_config is not None:
            self.app_config = app_config
        if thumbnail_bus is not None:
            self.thumbnail_bus = thumbnail_bus
        if resource_bus is not None:
            self.resource_bus = resource_bus
        if svc_mgr_bus is not None:
            self.svc_mgr_bus = svc_mgr_bus
        if history_bus is not None:
            self.history_bus = history_bus
        if collection_bus is not None:
            self.collection_bus = collection_bus
        if search_bus is not None:
            self.search_bus = search_bus


# 全局唯一运行时注册表
runtime = _Runtime()


def init(**kwargs):
    """向运行时注册表注入单例。仅在 main.py 应用初始化完成后调用一次。"""
    runtime.init(**kwargs)
