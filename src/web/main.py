"""
DPlayer - 纯后端 Web 服务
提供视频管理、标签管理、缩略图等 API 接口

目录结构：
  src/web/main.py      - 本文件（Web 服务入口）
  src/web/api/         - API 蓝图
  src/web/core/        - 数据模型
  src/web/backend/     - 后端工具
  src/thumbnail/       - 缩略图服务
  src/liblog/          - 日志库
  configs/services/    - 服务管理
"""
import os
import sys
import threading

# 目录定义
# _THIS_DIR: src/web/
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# _SRC_DIR: src/
_SRC_DIR = os.path.dirname(_THIS_DIR)
# 路径常量统一收敛到 backend.paths，避免重复推导与硬编码
from backend.paths import (
    PROJECT_ROOT,
    CONFIGS_DIR as _CONFIGS_DIR,
    DATA_DIR as _DATA_DIR,
    THUMB_CONFIG_FILE as _THUMB_CONFIG_FILE,
    WEB_CONFIG_FILE as CONFIG_FILE,
)

# 添加模块路径
for _p in [_THIS_DIR, _SRC_DIR, os.path.join(_CONFIGS_DIR, 'services'), _DATA_DIR]:
    if _p not in sys.path and os.path.exists(_p):
        sys.path.insert(0, _p)

from launcher_guard import check_service_launch

from flask import Flask, jsonify, request, send_file, abort, Response, g, session, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from sqlalchemy.orm import joinedload
from urllib.parse import quote, unquote
import json
import struct


from backend.utils.media import extract_mp4_duration


import threading
from liblog import get_service_logger
log = get_service_logger('dplayer-web')
import time
import hashlib
import random
import re
from functools import wraps

# 导入总线客户端（封面生成器）
try:
    sys.path.insert(0, os.path.join(_SRC_DIR, 'servicebus'))
    from servicebus import BusClient
    # 连接总线调用 thumbnaild
    thumbnail_bus = BusClient(
        'web-client',
        host='127.0.0.1',
        rpc_port=15555,
        pub_port=15556
    )
    # 连接总线调用 servicemgr
    svc_mgr_bus = BusClient(
        'web-svc-mgr',
        host='127.0.0.1',
        rpc_port=15555,
        pub_port=15556
    )
    # 连接总线调用 historyd (播放历史服务)
    history_bus = BusClient(
        'web-history',
        host='127.0.0.1',
        rpc_port=15555,
        pub_port=15556
    )
    # 连接总线调用 collectiond (收藏夹服务)
    collection_bus = BusClient(
        'web-collection',
        host='127.0.0.1',
        rpc_port=15555,
        pub_port=15556
    )
    # 连接总线调用 searchd (搜索服务)
    search_bus = BusClient(
        'web-search',
        host='127.0.0.1',
        rpc_port=15555,
        pub_port=15556
    )
    # 连接总线调用 resourced (资源管理服务)
    resource_bus = BusClient(
        'web-resource',
        host='127.0.0.1',
        rpc_port=15555,
        pub_port=15556
    )
except Exception as e:
    thumbnail_bus = None
    svc_mgr_bus = None
    history_bus = None
    collection_bus = None
    search_bus = None
    resource_bus = None
    log.maintenance('WARN', f'总线客户端初始化失败: {e}')

# 导入JWT SECRET_KEY（统一使用 backend/utils/jwt_authlib.py 中的配置）
from backend.utils.jwt_authlib import SECRET_KEY as JWT_SECRET_KEY

# 导入核心模块
from core.models import db, Video, Tag, VideoTag, UserInteraction, UserPreference, User, UserSession, UserRole, ROLE_NAMES, AppSetting, WatchLater
from core.models import FavoriteCollection, CollectionVideo, Gallery
from core.models import ResourceLibrary, LibraryPermission, LibraryUserGroup, LibraryUserGroupMember, LibraryAuditLog
from core.models import ResourceIndex, Post, PostRef, ResourceMode, ResourceModeMembership, Collection, Text, set_resource_modes as apply_resource_modes, User, parse_post_content_tokens
from core.models import migrate_collection_videos_schema, migrate_owner_columns, migrate_video_libraries_rename, migrate_trash_columns, migrate_tag_qualifiers, migrate_resource_index, migrate_post_title_nullable, migrate_post_source_columns, migrate_post_group_key
from auth_service import AuthService, init_root_user

# 导入资源管理模块的数据库操作（用于库 ID 映射）
try:
    sys.path.insert(0, os.path.join(_SRC_DIR, 'resource'))
    from resource.models import ResourceLibraryDB, ResourceFolderDB
    _HAS_RESOURCE_DB = True
except Exception:
    _HAS_RESOURCE_DB = False

# 导入API蓝图
from api.auth_api import auth_bp
from api.playlist_api import playlist_bp
from api.system_api import system_bp
from api.history_api import history_bp, init_history_api
from api.collection_api import collection_bp, init_collection_api
from api.collection_set_api import collection_set_api  # 独立合集模块（视频+图集）
from api.search_api import search_bp, init_search_api
from api.suggestion_api import suggestion_bp
from backend.api.shared_watch_api import shared_watch_bp
from backend.api.auth_api_v2 import auth_v2_bp
from backend.gallery.gallery_api import gallery_bp
from backend.trash import move_to_trash, purge_trash, restore_from_trash, get_trash_list, get_trash_obj
from backend.api.markers_api import markers_bp

# ============ 配置 ============
app = Flask(__name__)
app.config['SECRET_KEY'] = 'dplayer2-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(_DATA_DIR, 'databases', 'dplayer.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB

# CORS配置
CORS(app, resources={
    r"/api/*": {"origins": "*", "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"], "allow_headers": ["Content-Type", "Authorization"]},
    r"/api/admin/*": {"origins": "*", "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"], "allow_headers": ["Content-Type", "Authorization"]}
})

# ============ 日志（使用 liblog 统一日志） ============
log.maintenance('INFO', 'DPlayer Web 服务日志系统初始化完成')

# ============ 数据库初始化 ============
db.init_app(app)
with app.app_context():
    migrate_video_libraries_rename()
    migrate_trash_columns()
    db.create_all()
    migrate_resource_index()
    migrate_collection_videos_schema()
    migrate_owner_columns()
    migrate_tag_qualifiers()
    migrate_post_title_nullable()
    migrate_post_source_columns()
    migrate_post_group_key()
    init_root_user()

# ============ 注册蓝图 ============
app.register_blueprint(auth_bp)
app.register_blueprint(auth_v2_bp)  # v2版本JWT认证API
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
# 注：通用外部脚本接口（下载器）已迁移至独立的「资源下载器」服务（src/downloader/main.py，端口 8092），
#     主服务作为网关将脚本相关接口反向代理过去（见下方 _gateway_script_routes）。
#     前端仍统一访问 8080（开发/生产一致），主服务不直接执行脚本代码：
#     即使下载器崩溃，主服务也只返回 503 而不会抛异常、不影响其他功能。

# ===== 资源下载器网关代理 =====
_DOWNLOADER_BASE_URL = 'http://127.0.0.1:8092'
_SCRIPT_PREFIXES = ('/api/scripts', '/api/admin/scripts', '/api/admin/cookies')


def _proxy_to_downloader(path):
    """将请求原样转发给资源下载器服务（8092），透传方法/头/查询/Body/Cookie。"""
    import requests as _requests
    target = _DOWNLOADER_BASE_URL + path
    _hop = {'host', 'content-length', 'connection', 'transfer-encoding'}
    fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in _hop}
    try:
        resp = _requests.request(
            method=request.method,
            url=target,
            params=request.args,
            headers=fwd_headers,
            data=request.get_data(cache=True),
            cookies=request.cookies,
            allow_redirects=False,
            timeout=30,
        )
    except _requests.exceptions.RequestException:
        return jsonify({
            'success': False,
            'message': '资源下载器服务不可用，请检查下载器进程是否运行',
            'code': 503,
        }), 503
    _excluded = {'content-length', 'transfer-encoding', 'connection', 'content-encoding'}
    resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in _excluded}
    return resp.content, resp.status_code, resp_headers


@app.before_request
def _gateway_script_routes():
    """脚本/下载器相关接口统一经主服务网关转发到独立下载器进程。"""
    path = request.path
    for _p in _SCRIPT_PREFIXES:
        if path == _p or path.startswith(_p + '/'):
            return _proxy_to_downloader(path)
    return None

# ============ 操作审计日志 ============
# after_request 钩子：对所有 /api 写操作自动记录「是谁触发的」（含游客/登录用户与来源 IP）
from backend.audit import auto_audit_hook, log_operation
app.after_request(auto_audit_hook)

# ============ 初始化 API 总线客户端 ============
init_history_api(history_bus)
init_collection_api(collection_bus)
init_search_api(search_bus)
log.maintenance('INFO', 'Service bus clients initialized for APIs')

# ============ 认证装饰器 ============
# auth_required / admin_required / library_admin_required / resource_manager_required
# 已统一下沉至 backend.access（基于 resolve_identity），避免重复定义与硬编码 secret。
from backend.access import (auth_required, admin_required, library_admin_required, resource_manager_required)
# 辅助函数已下沉到 backend.*_helpers，运行时从对应模块导入并回绑到本命名空间。
# 运行时单例（db/app/app_config/buses）统一注入 backend.runtime，彻底消除对 main 的依赖。
from backend.system_helpers import (
    _count_active_tasks, _do_windows_shutdown, parse_log_line,
    SETTINGS_DEFAULTS, load_config, save_config,
    _scan_services, _get_service_status, _check_service_health, _open_scm,
    _SERVICE_META, _WIN32_SVC_STATUS, _svc_control_locks,
    _SHUTDOWN_CANCEL, _SHUTDOWN_LOCK, _shutdown_threading, _apply_setting,
)
from backend.helpers import (
    _resolve_dplayer_library_id_by_folder, _resolve_resource_library_id,
    _build_tag_tree, _ensure_interaction, record_interaction,
    get_or_create_tag_by_path, _resolve_post_refs, _build_post_refs,
)
from backend.library_helpers import (
    _list_system_drives, _restart_library_watchers,
    _library_scan_progress, _library_scan_all_progress, _INVALID_NAME_RE,
)
from backend.thumbnail_helpers import (
    _load_thumb_config, _save_thumb_config, _start_auto_generate,
    _generate_missing_thumbnails, _thumb_auto_thread, _thumb_auto_stop_event,
    _DEFAULT_THUMB_CONFIG,
)

# 运行时单例统一注入到 backend.runtime，彻底消除 helper 对 main 的依赖
from backend.runtime import runtime as _runtime
app_config = load_config()
_runtime.init(
    db=db, app=app, app_config=app_config,
    thumbnail_bus=thumbnail_bus, resource_bus=resource_bus,
    svc_mgr_bus=svc_mgr_bus, history_bus=history_bus,
    collection_bus=collection_bus, search_bus=search_bus,
)



# ============ 电脑关机控制（系统级，仅管理员） ============






# ============ 配置管理 ============
# CONFIG_FILE 已在文件顶部从 backend.paths 导入（WEB_CONFIG_FILE）

# ============ 辅助函数 ============
# 鉴权与资源库权限解析统一收敛到 backend.access，供本模块与所有蓝图共享，
# 避免各蓝图从 main 延迟 import 造成的循环依赖。
from backend.access import (
    get_user_session,
    resolve_identity,
    current_interaction_key,
    get_allowed_library_ids,
    resolve_user,
    _post_library_ids,
    _user_can_read_post,
    _is_library_admin,
    _user_library_admin_ids,
)

# ============ 静态文件服务 ============
# 注意：8080端口仅提供API服务，不提供前端静态文件
# 前端由 dplayer-webui 服务独立提供（5173端口）
# 以下静态文件路由已禁用，如需启用请注释掉

# ============ API 路由 ============


# --- 视频管理 ---






# ============ 收藏夹分组 API ============














# --- 观看次数记录 ---


# --- 视频播放 ---


# --- 标签管理 ---



# 保留旧路径以兼容


# --- 管理后台 API ---








# --- 回收站管理（管理员） ---










# ============ 统一管理界面：资源列表（视频/图集/帖子/文本，管理员高权限） ============






# --- 缩略图服务 ---








# --- 配置 API ---



# --- 上传 API ---


# --- 状态 API ---


# --- 扫描 API ---


# --- 本地视频服务 ---


# ============ 资源库管理 API =================













# ============ 文件夹管理 API（调用 resourced 服务） =================



# 测试端点 - 不需要认证










# ============ 服务器文件系统浏览 API =================

import re as _re
try:
    import ctypes as _ctypes
except Exception:
    _ctypes = None






# ============ 资源库扫描 API =================









# ============ 用户权限管理 API =================









# ============ 批量导入视频 API =================







# ============ 用户可访问资源库 API =================





# ============ 用户组管理 API =================











# ============ 审计日志 API =================



# ============ 系统日志查询 API =================


# ============ 缩略图管理 API =================

# 缩略图配置文件路径：已在文件顶部从 backend.paths 导入（THUMB_CONFIG_FILE）








# ============ 服务管理 API =================


try:
    import threading as _tw
    _tw.Thread(target=_restart_library_watchers, daemon=True,
               name='library-watcher-boot').start()
except Exception as e:
    log.maintenance('WARN', f'资源库文件夹监控模块不可用: {e}')


# ============ 帖子（Post）API ============
# 帖子只持有对 resource_index 的引用，可自由引用视频 / 图片集（图集）/ 未来文本等，
# 同一资源可被多个帖子共享，且移动磁盘资源只需更新索引表一行即可全局跟随。
















# ============ 多模式资源管理（资源归属模式：视频/图集/图文/文本/帖子） ============

















# ============ 从 main.py 拆分出的领域蓝图（main 完整初始化后再注册，避免循环导入） ============
from backend.api.video_api import bp as video_api_bp
app.register_blueprint(video_api_bp)
from backend.api.tag_api import bp as tag_api_bp
app.register_blueprint(tag_api_bp)
from backend.api.collection_api import bp as collection_api_bp
app.register_blueprint(collection_api_bp)
from backend.api.watch_later_api import bp as watch_later_api_bp
app.register_blueprint(watch_later_api_bp)
from backend.api.library_api import bp as library_api_bp
app.register_blueprint(library_api_bp)
from backend.api.thumbnail_api import bp as thumbnail_api_bp
app.register_blueprint(thumbnail_api_bp)
from backend.api.system_api import bp as system_api_bp
app.register_blueprint(system_api_bp)
from backend.api.post_resource_api import bp as post_resource_api_bp
app.register_blueprint(post_resource_api_bp)
from backend.api.serve_api import bp as serve_api_bp
app.register_blueprint(serve_api_bp)

# ============ 主入口 ============
if __name__ == '__main__':
    # 启动守卫：生产模式必须通过 NSSM 启动，开发模式允许直接运行。
    # 注意：守卫放在 __main__ 块内（而非模块导入期），避免 import web.main 时
    # 误触发 sys.exit，从而让本模块可被测试与静态分析。
    check_service_launch('DPlayer Web Service', 'src/web/main.py')

    # 检查是否为开发模式
    is_dev_mode = os.environ.get('DPLAYER_DEV_MODE') == '1'
    
    port = app_config.get('ports', {}).get('web', 8080)
    
    if is_dev_mode:
        print(f"[DEV MODE] Starting DPlayer Web service on port {port}")
        print(f"[DEV MODE] Access at: http://localhost:{port}")
        log.runtime('INFO', f'DPlayer Web 服务（开发模式）启动于端口 {port}')
        # 注意：禁用 use_reloader，因为 zmq socket 与 Flask reloader 不兼容
        # 代码变化后需要手动重启服务
        app.run(host='0.0.0.0', port=port, debug=True, use_reloader=False, threaded=True)
    else:
        print(f"[PRODUCTION] Starting DPlayer Web service on port {port}")
        log.runtime('INFO', f'DPlayer Web 服务启动于端口 {port}')
        # 生产模式：不启用 debug
        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
