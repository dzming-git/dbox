"""
Dbox - 纯后端 Web 服务
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
    USER_CONFIG_DIR,
    THUMB_CONFIG_FILE as _THUMB_CONFIG_FILE,
    WEB_CONFIG_FILE as CONFIG_FILE,
    _ensure_user_dirs,
)

# 确保用户数据区/配置区存在（含首次启动从项目 data/ 的迁移），在创建 DB 前执行
_ensure_user_dirs()

# 把解析后的用户数据区/配置区写入环境变量，供脚本引擎等子模块继承一致路径
os.environ.setdefault('DBOX_DATA_DIR', _DATA_DIR)
os.environ.setdefault('DBOX_USER_CONFIG_DIR', USER_CONFIG_DIR)

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
log = get_service_logger('dbox-web')
import time
import hashlib
import random
import re
from functools import wraps

# 总线客户端初始化收敛至 backend.service_buses（组合根保持轻量）
from backend.service_buses import init_service_buses

# 导入JWT SECRET_KEY（统一使用 backend/utils/jwt_authlib.py 中的配置）
from backend.utils.jwt_authlib import SECRET_KEY as JWT_SECRET_KEY

# 导入核心模块
from core.models import db, Video, Tag, VideoTag, UserInteraction, UserPreference, User, UserSession, UserRole, ROLE_NAMES, AppSetting, WatchLater
from core.models import FavoriteCollection, CollectionVideo, Gallery
from core.models import ResourceLibrary, LibraryPermission, LibraryUserGroup, LibraryUserGroupMember, LibraryAuditLog
from core.models import ResourceIndex, Post, PostRef, ResourceMode, ResourceModeMembership, Collection, Text, set_resource_modes as apply_resource_modes, User, parse_post_content_tokens
from core.models import migrate_collection_videos_schema, migrate_owner_columns, migrate_video_libraries_rename, migrate_trash_columns, migrate_tag_qualifiers, migrate_resource_index, migrate_post_title_nullable, migrate_post_source_columns, migrate_post_group_key, _migrate_gallery_playlists_col, migrate_main_library, migrate_watch_later_deleted_at
from auth_service import AuthService, init_root_user

# 导入资源管理模块的数据库操作（用于库 ID 映射）
try:
    sys.path.insert(0, os.path.join(_SRC_DIR, 'resource'))
    from resource.models import ResourceLibraryDB, ResourceFolderDB
    _HAS_RESOURCE_DB = True
except Exception:
    _HAS_RESOURCE_DB = False

from backend.trash import move_to_trash, purge_trash, restore_from_trash, get_trash_list, get_trash_obj

# ============ 配置 ============
app = Flask(__name__)
app.config['SECRET_KEY'] = 'dbox2-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(_DATA_DIR, 'databases', 'dbox.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB

# CORS配置
CORS(app, resources={
    r"/api/*": {"origins": "*", "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"], "allow_headers": ["Content-Type", "Authorization"]},
    r"/api/admin/*": {"origins": "*", "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"], "allow_headers": ["Content-Type", "Authorization"]}
})

# ============ 日志（使用 liblog 统一日志） ============
log.maintenance('INFO', 'Dbox Web 服务日志系统初始化完成')

# ============ 数据库初始化 ============
db.init_app(app)
with app.app_context():
    migrate_video_libraries_rename()
    migrate_trash_columns()
    migrate_watch_later_deleted_at()
    db.create_all()
    migrate_resource_index()
    _migrate_gallery_playlists_col()
    migrate_collection_videos_schema()
    migrate_owner_columns()
    migrate_tag_qualifiers()
    migrate_post_title_nullable()
    migrate_post_source_columns()
    migrate_post_group_key()
    migrate_main_library()
    init_root_user()

# ============ 注册蓝图 ============
# 蓝图注册逻辑收敛至 backend.blueprints，保持注册时机与顺序不变
from backend.blueprints import register_core_blueprints, register_domain_blueprints
register_core_blueprints(app)
# 注：「拓展管理」（外部脚本执行引擎、脚本管理、UI 扩展面板、AI 助手、凭证保险库）
#     已完全独立为 extensions_host 进程（src/extensions_host，端口 8093）。
#     主 Web 服务不再注册任何 script_engine 蓝图，仅作为网关把相关接口反向代理过去
#     （见下方 _gateway_extensions_routes），彻底实现拓展管理与主模块的解耦：
#     即使拓展宿主崩溃，主服务只返回 503 而不影响视频/图集/帖子等核心功能。
#     下载器（src/downloader，端口 8092）复用同一份引擎代码作为独立崩溃域，
#     但前端统一走 8093，脚本执行/回调均在 8093 内自洽。

# ===== 拓展管理宿主网关代理 =====
_EXTENSIONS_HOST_URL = 'http://127.0.0.1:8093'
_SCRIPT_PREFIXES = ('/api/scripts', '/api/admin/scripts', '/api/admin/cookies',
                    '/api/ui-extensions', '/api/ui-panel', '/api/ui-proxy',
                    '/api/ai-chat')


def _proxy_to_extensions_host(path):
    """将请求原样转发给拓展管理宿主（8093），透传方法/头/查询/Body/Cookie。"""
    import requests as _requests
    target = _EXTENSIONS_HOST_URL + path
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
            'message': '拓展管理宿主不可用，请检查 extensions_host 进程是否运行',
            'code': 503,
        }), 503
    _excluded = {'content-length', 'transfer-encoding', 'connection', 'content-encoding'}
    resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in _excluded}
    return resp.content, resp.status_code, resp_headers


@app.before_request
def _gateway_extensions_routes():
    """拓展管理相关接口统一经主服务网关转发到独立的 extensions_host 进程。"""
    path = request.path
    for _p in _SCRIPT_PREFIXES:
        if path == _p or path.startswith(_p + '/'):
            return _proxy_to_extensions_host(path)
    return None

# ============ 操作审计日志 ============
# after_request 钩子：对所有 /api 写操作自动记录「是谁触发的」（含游客/登录用户与来源 IP）
from backend.audit import auto_audit_hook, log_operation
app.after_request(auto_audit_hook)

# ============ 初始化 API 总线客户端 ============
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
    _resolve_dbox_library_id_by_folder, _resolve_resource_library_id,
    _build_tag_tree, _ensure_interaction, record_interaction,
    get_or_create_tag_by_path, _resolve_post_refs, _build_post_refs,
)
from backend.library_helpers import (
    _list_system_drives, _restart_library_watchers, _initial_library_scan,
    _library_scan_progress, _library_scan_all_progress, _INVALID_NAME_RE,
)
from backend.thumbnail_helpers import (
    _load_thumb_config, _save_thumb_config, _start_auto_generate,
    _generate_missing_thumbnails, _thumb_auto_thread, _thumb_auto_stop_event,
    _DEFAULT_THUMB_CONFIG,
)

# 运行时单例统一注入到 backend.runtime，彻底消除 helper 对 main 的依赖
from backend.runtime import runtime as _runtime
from backend.tls_helpers import build_tls_context
app_config = load_config()
_runtime.init(db=db, app=app, app_config=app_config)
# 总线客户端创建并注入 runtime（收敛至 backend.service_buses）
init_service_buses(_SRC_DIR)



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
# 前端由 dbox-webui 服务独立提供（5173端口）
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
    # 启动时全量扫描（受 auto_scan_on_startup 开关控制，独立于实时监控）
    _tw.Thread(target=_initial_library_scan, daemon=True,
               name='library-initial-scan').start()
except Exception as e:
    log.maintenance('WARN', f'资源库文件夹监控模块不可用: {e}')


# ============ 帖子（Post）API ============
# 帖子只持有对 resource_index 的引用，可自由引用视频 / 图片集（图集）/ 未来文本等，
# 同一资源可被多个帖子共享，且移动磁盘资源只需更新索引表一行即可全局跟随。
















# ============ 多模式资源管理（资源归属模式：视频/图集/图文/文本/帖子） ============

















# ============ 从 main.py 拆分出的领域蓝图（main 完整初始化后再注册，避免循环导入） ============
# 延迟导入与注册逻辑收敛至 backend.blueprints.register_domain_blueprints
register_domain_blueprints(app)

# 启动时若缩略图配置开启了自动生成，则自动恢复后台批量生成线程，
# 避免服务重启后需管理员手动重新打开开关才能继续生成缩略图。
try:
    _thumb_cfg = _load_thumb_config()
    if _thumb_cfg.get('auto_generate') and (_thumb_auto_thread is None or not _thumb_auto_thread.is_alive()):
        _start_auto_generate(_thumb_cfg, app=app)
        log.maintenance('INFO', '缩略图自动生成线程已随 Web 服务启动自动恢复')
except Exception as _e:
    log.maintenance('WARN', f'恢复缩略图自动生成线程失败: {_e}')

# ============ 双协议栈（HTTP + HTTPS 同时监听） ============
def _serve_dual_stack(app, host, http_port, https_port, ssl_ctx):
    """同时启动明文 HTTP 与 HTTPS 服务（HTTPS 在后台线程）。

    主线程阻塞在明文 HTTP 上，HTTPS 在守护线程中运行；
    两者使用同一个 Flask app 实例，共享全部路由与中间件。
    """
    from werkzeug.serving import make_server
    import threading

    http_srv = make_server(host, http_port, app, threaded=True)
    https_srv = make_server(host, https_port, app, ssl_context=ssl_ctx, threaded=True)

    def _run_https():
        try:
            https_srv.serve_forever()
        except Exception as e:  # pragma: no cover - 守护线程异常不应杀死进程
            log.runtime('ERROR', f'HTTPS 服务异常: {e}')

    t = threading.Thread(target=_run_https, daemon=True, name='dbox-https')
    t.start()
    try:
        http_srv.serve_forever()
    finally:
        https_srv.shutdown()


def _serve_internal_http(app, host, port):
    """内部契约接口（/internal/*）专用明文 HTTP 服务，仅绑定 127.0.0.1 本机回环。

    即便生产模式「对外禁用 http」（仅 HTTPS），拓展宿主（8093）与主服务之间的内部
    契约调用也必须本机可达。该服务只监听 127.0.0.1，不会对外暴露，因此不破坏
    「对外禁用明文 http」的安全设定；同时让 platform_client 经 127.0.0.1:port 的
    明文 HTTP 正常建单 / 入库，避免「AI 处理完成却无法在反馈中心落单」这类静默失败。
    """
    from werkzeug.serving import make_server
    import threading
    srv = make_server(host, port, app, threaded=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True,
                         name='dbox-internal-http')
    t.start()
    log.runtime('INFO', f'内部契约 HTTP 服务启动于 {host}:{port}（仅本机回环）')


# ============ 主入口 ============
if __name__ == '__main__':
    # 启动守卫：生产模式必须通过 NSSM 启动，开发模式允许直接运行。
    # 注意：守卫放在 __main__ 块内（而非模块导入期），避免 import web.main 时
    # 误触发 sys.exit，从而让本模块可被测试与静态分析。
    check_service_launch('Dbox Web Service', 'src/web/main.py')

    # 检查是否为开发模式
    is_dev_mode = os.environ.get('DBOX_DEV_MODE') == '1'

    host = app_config.get('host', '0.0.0.0')
    port = app_config.get('ports', {}).get('web', 8080)
    tls_cfg = app_config.get('tls', {}) or {}
    tls_port = int(tls_cfg.get('port', 8443)) if isinstance(tls_cfg, dict) else 8443
    # 开发模式不做 TLS（避免与调试器/热重载冲突）；生产模式按配置启用 HTTPS
    tls_ctx = build_tls_context(tls_cfg, USER_CONFIG_DIR) if (not is_dev_mode and isinstance(tls_cfg, dict)) else None
    tls_enabled = tls_ctx is not None
    disable_http = bool(tls_cfg.get('disable_http')) if isinstance(tls_cfg, dict) else False

    if tls_enabled and disable_http:
        # 仅 HTTPS 对外：禁用对外明文 HTTP（呼应反馈「禁用 http，使用 https」）。
        # 但内部契约（拓展宿主 ↔ 主服务）必须本机可达，故在 127.0.0.1 额外起一个
        # 明文 HTTP 端口专供 /internal/*，不对外暴露，不影响对外安全设定。
        internal_port = int(app_config.get('ports', {}).get('web', 8080))
        _serve_internal_http(app, '127.0.0.1', internal_port)
        print(f"[PRODUCTION] Starting Dbox Web service (HTTPS only) on port {tls_port}")
        log.runtime('INFO', f'Dbox Web 服务（仅 HTTPS）启动于端口 {tls_port}')
        app.run(host=host, port=tls_port, debug=False, use_reloader=False,
                threaded=True, ssl_context=tls_ctx)
    elif tls_enabled:
        # 双栈：HTTPS(tls_port) + 明文 HTTP(web port)，便于平滑过渡
        print(f"[PRODUCTION] Starting Dbox Web service: HTTPS on {tls_port}, HTTP on {port}")
        log.runtime('INFO', f'Dbox Web 服务（HTTPS+HTTP）启动: HTTPS={tls_port}, HTTP={port}')
        _serve_dual_stack(app, host, port, tls_port, tls_ctx)
    elif is_dev_mode:
        print(f"[DEV MODE] Starting Dbox Web service on port {port}")
        print(f"[DEV MODE] Access at: http://localhost:{port}")
        log.runtime('INFO', f'Dbox Web 服务（开发模式）启动于端口 {port}')
        # 注意：禁用 use_reloader，因为 zmq socket 与 Flask reloader 不兼容
        # 代码变化后需要手动重启服务
        app.run(host=host, port=port, debug=True, use_reloader=False, threaded=True)
    else:
        print(f"[PRODUCTION] Starting Dbox Web service on port {port}")
        log.runtime('INFO', f'Dbox Web 服务启动于端口 {port}')
        # 生产模式：不启用 debug
        app.run(host=host, port=port, debug=False, threaded=True)
