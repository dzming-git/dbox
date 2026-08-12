"""蓝图集中注册。

统一收敛所有 Flask 蓝图，避免 main.py 散落大量 import 与注册代码。
原 src/web/api/* 下的遗留蓝图已全部迁移到 backend/api 体系并删除，
此处只负责 backend/api 与 backend.gallery 下的蓝图。
"""
from flask import Flask


def register_core_blueprints(app: Flask) -> None:
    """注册核心蓝图（导入顺序与原 main.py 保持一致，避免循环依赖）。"""
    from backend.api.auth_api_v2 import auth_v2_bp  # v2版本JWT认证API
    from backend.api.shared_watch_api import shared_watch_bp
    from backend.gallery.gallery_api import gallery_bp
    from backend.api.markers_api import markers_bp
    from backend.api.system_info_api import system_info_bp
    from backend.api.suggestion_api import suggestion_bp

    # 初始化反馈独立数据库（建表 + 从旧 issues.json 幂等迁移）
    from backend.feedback_db import init_feedback_db
    init_feedback_db()

    # 主服务内部 API：生成内部密钥并注册，供独立运行的 extensions_host 回调业务
    from backend.internal_api import internal_bp as _internal_bp, init_internal_key as _init_internal_key
    _init_internal_key(app)
    app.register_blueprint(_internal_bp)

    app.register_blueprint(auth_v2_bp)
    app.register_blueprint(shared_watch_bp)
    app.register_blueprint(gallery_bp)
    app.register_blueprint(markers_bp)
    app.register_blueprint(system_info_bp)
    app.register_blueprint(suggestion_bp)


def register_domain_blueprints(app: Flask) -> None:
    """注册领域蓝图（延迟导入，避免与核心蓝图循环依赖）。"""
    from backend.api.video_api import bp as video_api_bp
    from backend.api.tag_api import bp as tag_api_bp
    from backend.api.collection_api import bp as collection_api_bp
    from backend.api.watch_later_api import bp as watch_later_api_bp
    from backend.api.history_api import bp as history_api_bp
    from backend.api.interaction_api import bp as interaction_api_bp
    from backend.api.library_api import bp as library_api_bp
    from backend.api.thumbnail_api import bp as thumbnail_api_bp
    from backend.api.system_api import bp as system_api_bp
    from backend.api.post_resource_api import bp as post_resource_api_bp
    from backend.api.serve_api import bp as serve_api_bp
    from task_routes import bp as task_bp

    app.register_blueprint(video_api_bp)
    app.register_blueprint(tag_api_bp)
    app.register_blueprint(collection_api_bp)
    app.register_blueprint(watch_later_api_bp)
    app.register_blueprint(history_api_bp)
    app.register_blueprint(interaction_api_bp)
    app.register_blueprint(library_api_bp)
    app.register_blueprint(thumbnail_api_bp)
    app.register_blueprint(system_api_bp)
    app.register_blueprint(post_resource_api_bp)
    app.register_blueprint(serve_api_bp)
    app.register_blueprint(task_bp)
