# -*- coding: utf-8 -*-
"""蓝图注册集中管理。

将 main.py 中分散的 ``app.register_blueprint(...)`` 调用收敛到本模块，
使 main.py 入口保持清爽。注册顺序与时机与原实现一致：

* ``register_core_blueprints`` 注册在 main 完整初始化后即可加载的蓝图
  （这些模块的 import 不触发循环依赖，可在 main 顶部直接导入）。
* ``register_domain_blueprints`` 注册从 main 拆分出的领域蓝图，保持
  **延迟局部导入**（函数内 import），避免在 main 导入期产生循环依赖。
"""
from flask import Flask


def register_core_blueprints(app: Flask) -> None:
    """注册核心蓝图（main 顶部已可安全导入的部分）。"""
    from api.auth_api import auth_bp
    from api.playlist_api import playlist_bp
    from api.system_api import system_bp
    from api.history_api import history_bp
    from api.collection_api import collection_bp
    from api.collection_set_api import collection_set_api  # 独立合集模块（视频+图集）
    from api.search_api import search_bp
    from api.suggestion_api import suggestion_bp
    from backend.api.shared_watch_api import shared_watch_bp
    from backend.api.auth_api_v2 import auth_v2_bp  # v2版本JWT认证API
    from backend.gallery.gallery_api import gallery_bp  # 图集模式 API
    from backend.api.markers_api import markers_bp  # 精彩片段标记 API

    app.register_blueprint(auth_bp)
    app.register_blueprint(auth_v2_bp)
    app.register_blueprint(playlist_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(history_bp)  # 播放历史API
    app.register_blueprint(collection_bp)  # 收藏夹API
    app.register_blueprint(collection_set_api)  # 独立合集模块（视频+图集）
    app.register_blueprint(search_bp)  # 搜索API
    app.register_blueprint(suggestion_bp, url_prefix='/api/suggestion')  # 建议反馈API / Issue
    app.register_blueprint(shared_watch_bp)  # 共享观看API
    app.register_blueprint(gallery_bp)  # 图集模式 API
    app.register_blueprint(markers_bp)  # 精彩片段标记 API


def register_domain_blueprints(app: Flask) -> None:
    """注册领域蓝图（延迟导入，避免 main 导入期循环依赖）。"""
    from backend.api.video_api import bp as video_api_bp
    from backend.api.tag_api import bp as tag_api_bp
    from backend.api.collection_api import bp as collection_api_bp
    from backend.api.watch_later_api import bp as watch_later_api_bp
    from backend.api.library_api import bp as library_api_bp
    from backend.api.thumbnail_api import bp as thumbnail_api_bp
    from backend.api.system_api import bp as system_api_bp
    from backend.api.post_resource_api import bp as post_resource_api_bp
    from backend.api.serve_api import bp as serve_api_bp

    app.register_blueprint(video_api_bp)
    app.register_blueprint(tag_api_bp)
    app.register_blueprint(collection_api_bp)
    app.register_blueprint(watch_later_api_bp)
    app.register_blueprint(library_api_bp)
    app.register_blueprint(thumbnail_api_bp)
    app.register_blueprint(system_api_bp)
    app.register_blueprint(post_resource_api_bp)
    app.register_blueprint(serve_api_bp)
