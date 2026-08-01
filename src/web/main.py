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
# PROJECT_ROOT: 项目根目录 (Dplayer2.0/)
PROJECT_ROOT = os.path.dirname(_SRC_DIR)
# CONFIGS_DIR: configs/
_CONFIGS_DIR = os.path.join(PROJECT_ROOT, 'configs')
# DATA_DIR: data/
_DATA_DIR = os.path.join(PROJECT_ROOT, 'data')

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

# 资源库扫描进度（web 侧，驱动 Video 表作为唯一索引源）
_library_scan_progress = {}
# 全量扫描进度（一键扫描所有资源库）
_library_scan_all_progress = {'status': 'idle', 'total': 0, 'done': 0, 'message': ''}

def _resolve_resource_library_id(dplayer_library_id: int) -> int:
    """
    将 dplayer.db 的资源库 ID 映射为 resource.db 的资源库 ID
    通过库名称匹配（库名称在两个系统中都唯一）
    
    Returns:
        resource.db 中对应的库 ID，如果找不到则返回原始的 dplayer_library_id
    """
    if not _HAS_RESOURCE_DB:
        return dplayer_library_id
    
    library = ResourceLibrary.query.get(dplayer_library_id)
    if not library:
        return dplayer_library_id
    
    # 按名称在 resource.db 中查找匹配的库
    all_resources = ResourceLibraryDB.get_all()
    for res_lib in all_resources:
        if res_lib.name == library.name:
            return res_lib.id
    
    # 找不到匹配的，返回原始 ID（resourced 会返回"库不存在"错误）
    return dplayer_library_id

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


# ============ 电脑关机控制（系统级，仅管理员） ============
import threading as _shutdown_threading

_SHUTDOWN_CANCEL = {'after_tasks': False}
_SHUTDOWN_LOCK = _shutdown_threading.Lock()


def _count_active_tasks():
    """统计当前活跃任务数：转码/缩略图(ffmpeg) 进程 + 下载器活跃任务(best-effort)。"""
    count = 0
    try:
        import psutil
        for p in psutil.process_iter(['name', 'cmdline']):
            try:
                info = p.info
                name = (info.get('name') or '').lower()
                cmd = ' '.join(info.get('cmdline') or []).lower()
                if 'ffmpeg' in name or 'ffmpeg' in cmd:
                    if any(k in cmd for k in ('thumb', 'transcode', 'encode', 'scale', 'thumbnail')):
                        count += 1
            except Exception:
                continue
    except Exception:
        pass
    # 下载器活跃任务（best-effort，不可达则忽略）
    try:
        import urllib.request
        import json as _json
        try:
            with urllib.request.urlopen('http://127.0.0.1:8092/api/tasks/active', timeout=1.5) as resp:
                if resp.status == 200:
                    data = _json.loads(resp.read().decode('utf-8'))
                    count += int(data.get('count', 0) or 0)
        except Exception:
            pass
    except Exception:
        pass
    return count


def _do_windows_shutdown(seconds=0):
    import subprocess
    # /f 强制关闭应用程序，/t 设置超时秒数
    subprocess.run(f'shutdown /s /t {max(0, int(seconds))} /f', shell=True)






# ============ 资源库管理员权限（按库授权，区别于全局管理员） ============
def _resolve_dplayer_library_id_by_folder(folder_id):
    """folder_id 为 resourced 的文件夹 id，反查对应的 dplayer 资源库 id。"""
    if not _HAS_RESOURCE_DB:
        return None
    try:
        folder = ResourceFolderDB.get_by_id(folder_id)
        if not folder:
            return None
        rl = ResourceLibraryDB.get_by_id(folder.library_id)
        if not rl:
            return None
        lib = ResourceLibrary.query.filter_by(name=rl.name).first()
        return lib.id if lib else None
    except Exception:
        return None


# ============ 分层设置（用户 / 全局 / 浏览器） ============
# 合并优先级（高 -> 低）：browser > user > global > defaults
SETTINGS_DEFAULTS = {
    'autoplay': False,
    'defaultQuality': 'auto',
    'subtitleLanguage': 'off',
    'theme': 'dark',
    'language': 'zh-CN',
    'blockDisliked': False,
    'defaultSort': 'recommended',
    'defaultOrder': 'desc',
    'enableNotifications': True,
    'notifyOnNewVideos': True,
}






# ============ 配置管理 ============
CONFIG_FILE = os.path.join(_CONFIGS_DIR, 'web', 'config.json')

def load_config():
    default = {
        "scan_directories": [{"path": "M:/<媒体库>", "recursive": True, "enabled": True}],
        "auto_scan_on_startup": True,
        "supported_formats": [".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"],
        "default_tags": [],
        "default_priority": 0,
        "ports": {"web": 8080, "thumbnail": "bus://127.0.0.1:15555"}
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return {**default, **json.load(f)}
        except:
            pass
    return default

def save_config(cfg):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        log.debug('ERROR', f'保存配置失败: {e}')
        return False

app_config = load_config()

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

def record_interaction(video_id, user_session, interaction_type, score=1.0):
    try:
        interaction = UserInteraction(
            video_id=video_id,
            user_session=user_session,
            interaction_type=interaction_type,
            interaction_score=score
        )
        db.session.add(interaction)
        
        video_tags = VideoTag.query.filter_by(video_id=video_id).all()
        for vt in video_tags:
            pref = UserPreference.query.filter_by(
                user_session=user_session, tag_id=vt.tag_id
            ).first()
            if pref:
                pref.preference_score += score * 0.1
                pref.interaction_count += 1
            else:
                pref = UserPreference(
                    user_session=user_session,
                    tag_id=vt.tag_id,
                    preference_score=1.0 + score * 0.1,
                    interaction_count=1
                )
                db.session.add(pref)
        db.session.commit()
    except Exception as e:
        log.debug('ERROR', f'记录交互失败: {e}')
        db.session.rollback()

# ============ 静态文件服务 ============
# 注意：8080端口仅提供API服务，不提供前端静态文件
# 前端由 dplayer-webui 服务独立提供（5173端口）
# 以下静态文件路由已禁用，如需启用请注释掉

# ============ API 路由 ============


# --- 视频管理 ---





















def _ensure_interaction(video, user_session, itype, score):
    """确保存在某条交互记录（用于批量添加，幂等）"""
    interaction = UserInteraction.query.filter_by(
        video_id=video.id, user_session=user_session, interaction_type=itype
    ).first()
    if not interaction:
        interaction = UserInteraction(
            video_id=video.id, user_session=user_session,
            interaction_type=itype, interaction_score=score
        )
        db.session.add(interaction)
        db.session.flush()
    return interaction






# ============ 收藏夹分组 API ============














# --- 观看次数记录 ---


# --- 视频播放 ---


# --- 标签管理 ---





def _build_tag_tree(tags):
    """将扁平标签列表转换为树形结构"""
    tag_map = {tag['id']: {**tag, 'children': []} for tag in tags}
    tree = []
    
    for tag in tags:
        tag_node = tag_map[tag['id']]
        if tag['parent_id'] is None or tag['parent_id'] not in tag_map:
            tree.append(tag_node)
        else:
            tag_map[tag['parent_id']]['children'].append(tag_node)
    
    return tree


def get_or_create_tag_by_path(tag_path: str, library_id=None, category='类型'):
    """
    根据路径获取或创建标签（支持层级）
    例如: "/动物/狗/哈士奇" 会创建 3 级标签
    
    Args:
        tag_path: 标签路径，如 "/动物/狗/哈士奇"
        library_id: 资源库ID（可选，null表示全局标签）
        category: 分类
    
    Returns:
        Tag 对象
    """
    # 规范化路径
    tag_path = tag_path.strip()
    if not tag_path.startswith('/'):
        tag_path = '/' + tag_path
    
    # 解析路径层级
    parts = [p for p in tag_path.split('/') if p]
    
    if not parts:
        return None
    
    parent_id = None
    current_path = ''
    
    for i, part in enumerate(parts):
        # 构建当前层级的路径
        if i == 0:
            current_path = '/' + part
        else:
            current_path = current_path + '/' + part
        
        # 查询是否已存在（按路径匹配，跨资源库复用规范标签，避免重复创建）
        existing_tag = Tag.query.filter(
            Tag.path == current_path
        ).order_by(Tag.id.asc()).first()
        
        if existing_tag:
            parent_id = existing_tag.id
        else:
            # 创建新标签
            new_tag = Tag(
                name=part,
                path=current_path,
                category=category,
                parent_id=parent_id,
                library_id=library_id
            )
            db.session.add(new_tag)
            db.session.flush()
            parent_id = new_tag.id
    
    # 返回最终创建的标签（按路径复用规范标签，避免重复）
    return Tag.query.filter(
        Tag.path == current_path
    ).order_by(Tag.id.asc()).first()



# 保留旧路径以兼容










def _do_update_tag(tag_id):
    """更新标签的实际逻辑"""
    try:
        tag = Tag.query.get_or_404(tag_id)
        data = request.get_json()
        
        name = data.get('name', '').strip()
        if name:
            if len(name) < 2 or len(name) > 20:
                return jsonify({'success': False, 'message': '标签名长度需在2-20字符之间'}), 400
            
            # 检查名称唯一性（排除当前标签）
            existing = Tag.query.filter_by(name=name).first()
            if existing and existing.id != tag_id:
                return jsonify({'success': False, 'message': '标签名已存在'}), 400
            
            tag.name = name
        
        if 'category' in data:
            tag.category = data['category'].strip() or '类型'
        
        if 'qualifiers' in data:
            tag.set_qualifiers(data['qualifiers'])
        
        # 支持修改父标签
        if 'parent_id' in data:
            new_parent_id = data['parent_id']
            if new_parent_id:
                # 验证父标签存在
                parent_tag = Tag.query.get(new_parent_id)
                if not parent_tag:
                    return jsonify({'success': False, 'message': '父标签不存在'}), 400
                # 避免循环引用：不能设置自己或自己的子标签为父标签
                child_ids = tag.get_all_child_ids()
                if new_parent_id in child_ids:
                    return jsonify({'success': False, 'message': '不能设置自己的子标签为父标签'}), 400
            tag.parent_id = new_parent_id
        
        db.session.commit()
        log.maintenance('INFO', f"更新标签: {tag.name} (ID: {tag_id})")
        return jsonify({'success': True, 'tag': tag.to_dict()})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"更新标签失败: {tag_id}, {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


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

_INVALID_NAME_RE = _re.compile(r'[\\/:*?"<>|]')


def _list_system_drives():
    """返回 Windows 盘符列表；其他平台返回 ['/']。"""
    try:
        if os.name == 'nt' and _ctypes is not None:
            bitmask = _ctypes.windll.kernel32.GetLogicalDrives()
            drives = []
            for i in range(26):
                if bitmask & (1 << i):
                    drives.append(chr(65 + i) + ':\\')
            if drives:
                return drives
    except Exception:
        pass
    return ['C:\\'] if os.name == 'nt' else ['/']






# ============ 资源库扫描 API =================









# ============ 用户权限管理 API =================









# ============ 批量导入视频 API =================







# ============ 用户可访问资源库 API =================





# ============ 用户组管理 API =================











# ============ 审计日志 API =================



# ============ 系统日志查询 API =================



def parse_log_line(line: str, log_type: str) -> dict | None:
    """
    解析单行日志
    
    格式:
    - maintenance/runtime/debug: [时间] | [等级] | [服务] | [内容]
    - operation: [时间] | [IP] | [服务] | [内容]
    """
    import re
    
    # 匹配格式: [xxx] | [xxx] | [xxx] | [xxx]
    match = re.match(r'^\[([^\]]+)\]\s*\|\s*\[([^\]]+)\]\s*\|\s*\[([^\]]+)\]\s*\|\s*\[(.+)\]$', line)
    if not match:
        return None
    
    timestamp = match.group(1).strip()
    field2 = match.group(2).strip()  # 等级（或 IP）
    service = match.group(3).strip()
    content = match.group(4).strip()

    result = {
        'timestamp': timestamp,
        'level': field2 if log_type != 'operation' else '',
        'source': field2 if log_type == 'operation' else '',
        'service': service,
        'content': content,
        'type': log_type,
        'user': ''
    }

    # 操作日志：从内容段提取「user=xxx」（兼容旧格式「用户=xxx」）作为独立字段，
    # 便于审计查看谁触发的
    if log_type == 'operation':
        user_match = re.search(r'(?:用户|user)=([^|]+)', content)
        if user_match:
            result['user'] = user_match.group(1).strip()

    return result


# ============ 缩略图管理 API =================

# 缩略图配置文件路径
_THUMB_CONFIG_FILE = os.path.join(_DATA_DIR, 'thumbnail_config.json')

# 默认缩略图配置
_DEFAULT_THUMB_CONFIG = {
    'auto_generate': False,          # 是否自动扫描生成缺失缩略图
    'max_workers': 2,                # 最大并发生成线程数
    'task_interval': 3,              # 任务间隔时间（秒）
    'auto_generate_interval': 3600   # 自动扫描间隔（秒），默认1小时
}

# 自动生成后台线程控制
_thumb_auto_thread = None
_thumb_auto_stop_event = threading.Event()


def _load_thumb_config():
    """加载缩略图配置"""
    try:
        if os.path.exists(_THUMB_CONFIG_FILE):
            with open(_THUMB_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            # 合并默认值，确保新字段存在
            merged = {**_DEFAULT_THUMB_CONFIG, **config}
            return merged
    except Exception as e:
        log.debug('ERROR', f'加载缩略图配置失败: {e}')
    return {**_DEFAULT_THUMB_CONFIG}


def _save_thumb_config(config):
    """保存缩略图配置"""
    try:
        os.makedirs(os.path.dirname(_THUMB_CONFIG_FILE), exist_ok=True)
        with open(_THUMB_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        log.debug('ERROR', f'保存缩略图配置失败: {e}')
        return False






def _start_auto_generate(config=None):
    """启动自动生成缩略图后台线程"""
    global _thumb_auto_thread

    if config is None:
        config = _load_thumb_config()

    _thumb_auto_stop_event.clear()

    def _auto_generate_worker():
        """自动扫描并生成缺失缩略图"""
        log.maintenance('INFO', '缩略图自动生成线程已启动')

        while not _thumb_auto_stop_event.is_set():
            try:
                _generate_missing_thumbnails(config)
            except Exception as e:
                log.debug('ERROR', f'自动生成缩略图出错: {e}')

            # 等待下一次扫描
            _thumb_auto_stop_event.wait(config.get('auto_generate_interval', 3600))

        log.maintenance('INFO', '缩略图自动生成线程已停止')

    _thumb_auto_thread = threading.Thread(target=_auto_generate_worker, daemon=True)
    _thumb_auto_thread.start()


def _generate_missing_thumbnails(config=None):
    """扫描并生成缺失的缩略图"""
    if config is None:
        config = _load_thumb_config()

    thumb_dir = os.path.join(_DATA_DIR, 'thumbnails')
    max_workers = config.get('max_workers', 2)
    task_interval = config.get('task_interval', 3)

    from core.models import Video
    db_videos = Video.query.all()

    missing_videos = []
    for v in db_videos:
        if v.hash and v.local_path and os.path.exists(v.local_path):
            has_thumb = any(
                os.path.exists(os.path.join(thumb_dir, f'{v.hash}.{ext}'))
                for ext in ['gif', 'jpg', 'png']
            )
            if not has_thumb:
                missing_videos.append(v)

    if not missing_videos:
        log.maintenance('INFO', '没有需要生成缩略图的视频')
        return

    log.maintenance('INFO', f'发现 {len(missing_videos)} 个视频缺少缩略图，开始批量生成（并发数: {max_workers}，间隔: {task_interval}秒）')

    if thumbnail_bus:
        # 使用封面生成器批量提交
        import concurrent.futures

        def _submit_one(video):
            try:
                thumbnail_bus.call_method(
                    service='com.dplayer.thumbnaild',
                    interface='com.dplayer.Thumbnaild',
                    method='Generate',
                    params={'video_path': video.local_path, 'video_hash': video.hash, 'output_format': 'gif'}
                )
                return (video.hash, True, None)
            except Exception as e:
                return (video.hash, False, str(e))

        # 使用线程池控制并发
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for i, video in enumerate(missing_videos):
                # 如果停止信号触发，提前退出
                if _thumb_auto_stop_event.is_set():
                    log.maintenance('INFO', f'自动生成被停止，已提交 {i}/{len(missing_videos)} 个任务')
                    break

                future = executor.submit(_submit_one, video)
                futures.append(future)

                # 任务间隔
                if i < len(missing_videos) - 1 and task_interval > 0:
                    _thumb_auto_stop_event.wait(task_interval)

            # 收集结果
            success = 0
            failed = 0
            for future in concurrent.futures.as_completed(futures):
                try:
                    _, ok, err = future.result()
                    if ok:
                        success += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1

        log.maintenance('INFO', f'批量生成缩略图完成: 成功 {success}, 失败 {failed}')
    else:
        # 缩略图服务不可用，使用本地生成
        log.maintenance('WARN', '缩略图微服务不可用，无法批量生成')

    return {'submitted': len(missing_videos)}








# ============ 服务管理 API =================

# 服务元信息映射（nssm service name -> 服务描述）
_SERVICE_META = {
    'dplayer-web': {
        'display_name': 'DPlayer Web服务',
        'description': 'Web API 服务 - 视频管理、用户认证等',
        'health_url': None,  # 自己就是 web 服务，特殊处理
        'port': 8080,
    },
    'dplayer-bus': {
        'display_name': 'DPlayer 服务总线',
        'description': '服务总线代理，所有内部服务通信中枢',
        'health_url': None,  # 无 HTTP，纯后台
        'port': None,         # 无 HTTP 端口，纯总线通信
    },
    'dplayer-servicemgr': {
        'display_name': 'DPlayer 服务管理',
        'description': '服务管理守护进程，定期扫描 dplayer-* 服务状态',
        'health_url': None,  # 无 HTTP，纯后台
        'port': None,         # 无 HTTP 端口，纯总线通信
    },
    'dplayer-thumbnail': {
        'display_name': 'DPlayer 缩略图服务',
        'description': '视频缩略图生成微服务（通过服务总线）',
        'health_url': None,  # 通过 ServiceBus 总线检查，不暴露 HTTP
        'port': None,         # 无 HTTP 端口，纯总线通信
    },
    'dplayer-webui': {
        'display_name': 'DPlayer WebUI服务',
        'description': 'Vue3 前端界面',
        'health_url': 'http://localhost:5173',
        'port': 5173,
        'health_check_json': False,  # 前端返回 HTML，只检查 HTTP 状态码
    },
    'dplayer-downloader': {
        'display_name': 'DPlayer 资源下载器',
        'description': '独立进程：外部脚本 / 下载器服务（与主服务解耦，崩溃不影响主服务）',
        'health_url': 'http://127.0.0.1:8092/api/health',
        'port': 8092,
    },
}

# Windows 服务状态码映射
_WIN32_SVC_STATUS = {
    1: 'STOPPED',
    2: 'START_PENDING',
    3: 'STOP_PENDING',
    4: 'RUNNING',
    5: 'CONTINUE_PENDING',
    6: 'PAUSE_PENDING',
    7: 'PAUSED',
}

# 控制服务操作的锁（防止并发操作同一服务）
_svc_control_locks = {}


def _open_scm():
    """打开服务控制管理器 (SCM)"""
    import win32service
    return win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)


def _scan_services() -> list:
    """
    扫描 dplayer- 前缀的 Windows 服务
    优先使用 win32service API，失败时 fallback 到 sc query 命令
    """
    # 方法1: 通过 win32service API（需要足够的权限）
    try:
        import win32service

        scm = _open_scm()
        try:
            services = win32service.EnumServicesStatus(
                scm, win32service.SERVICE_WIN32, win32service.SERVICE_STATE_ALL
            )
            return [s[0] for s in services if s[0].startswith('dplayer-')]
        finally:
            win32service.CloseServiceHandle(scm)
    except Exception as e:
        log.debug('DEBUG', f'[服务管理] win32service 扫描失败: {type(e).__name__}: {e}')

    # 方法2: fallback 到 sc query 命令（权限要求较低）
    try:
        import subprocess
        # Windows 上 sc 是 cmd 内置命令，需要 shell=True 才能正确执行
        result = subprocess.run(
            'sc query type= service state= all',
            capture_output=True, text=True, timeout=30, shell=True
        )
        if result.returncode == 0:
            # 解析 sc query 输出，查找 dplayer- 前缀的服务
            dplayer_svcs = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith('SERVICE_NAME:'):
                    svc_name = line.split(':', 1)[1].strip()
                    if svc_name.startswith('dplayer-'):
                        dplayer_svcs.append(svc_name)
            if dplayer_svcs:
                log.debug('DEBUG', f'[服务管理] sc query fallback 找到 {len(dplayer_svcs)} 个服务')
                return dplayer_svcs
    except Exception as e2:
        log.debug('DEBUG', f'[服务管理] sc query fallback 也失败: {type(e2).__name__}: {e2}')

    # 方法3: 直接查询已知的服务名（基于 install.py 的定义）
    known_services = [
        'dplayer-web', 'dplayer-bus', 'dplayer-servicemgr', 'dplayer-thumbnail',
        'dplayer-webui', 'dplayer-resource', 'dplayer-userd', 'dplayer-systemd',
        'dplayer-historyd', 'dplayer-collectiond', 'dplayer-searchd',
        'dplayer-downloader',
    ]
    verified = []
    try:
        import win32service
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        for svc_name in known_services:
            try:
                hs = win32service.OpenService(scm, svc_name, win32service.SERVICE_QUERY_STATUS)
                win32service.CloseServiceHandle(hs)
                verified.append(svc_name)
            except Exception:
                pass
        win32service.CloseServiceHandle(scm)
    except Exception:
        pass

    # 合并静态元信息中定义的所有服务（如独立进程方式运行的下载器），
    # 保证它们始终出现在服务列表中，即使未注册为 Windows 服务。
    merged = list(verified)
    for name in _SERVICE_META.keys():
        if name not in merged:
            merged.append(name)

    if merged:
        log.debug('DEBUG', f'[服务管理] 探测/合并找到 {len(merged)} 个服务: {merged}')
        return merged

    log.debug('DEBUG', '[服务管理] 扫描服务失败: 所有方法均无法获取服务列表')
    return []


def _get_service_status(service_name: str) -> dict:
    """
    获取单个服务的系统层状态信息（通过 win32service + psutil）

    Returns:
        dict: { status, pid, memory_mb, cpu_percent }
    """
    info = {
        'status': 'unknown',
        'pid': None,
        'memory_mb': None,
        'cpu_percent': None,
    }

    # 1. 通过 win32service 获取 Windows 服务状态和进程 PID
    try:
        import win32service

        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
        svc = win32service.OpenService(scm, service_name, win32service.SERVICE_QUERY_STATUS)
        status_info = win32service.QueryServiceStatus(svc)
        win32service.CloseServiceHandle(svc)
        win32service.CloseServiceHandle(scm)

        state_code = status_info[1]
        info['status'] = _WIN32_SVC_STATUS.get(state_code, f'UNKNOWN({state_code})')

        # 尝试获取服务的进程 PID
        # win32service 不直接提供 PID，但 NSSM 服务的实际进程是子进程
        # 通过状态信息中的 process ID 获取（如果可用）
        # status_info 结构: (serviceType, currentState, controlsAccepted, ...)
        # 注意：标准的 QueryServiceStatus 不包含 PID，需要用 QueryServiceStatusEx
    except Exception as e:
        log.debug('DEBUG', f'[服务管理] 获取服务状态异常 {service_name}: {type(e).__name__}: {e}')
        info['status'] = 'unknown'
        return info

    # PAUSED / RUNNING 状态都尝试获取 PID/CPU/内存（进程实际仍在运行）
    if info['status'] not in ('RUNNING', 'PAUSED'):
        return info

    # 2. 获取进程 PID
    try:
        import psutil

        # 方法1: 通过端口查找进程（最可靠）
        meta = _SERVICE_META.get(service_name, {})
        port = meta.get('port')
        if port:
            for conn in psutil.net_connections(kind='inet'):
                if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                    info['pid'] = conn.pid
                    break

        # 方法2: 通过进程名查找
        if not info['pid']:
            app_name = 'python.exe'
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['name'] and proc.info['name'].lower() == app_name.lower():
                        # 检查命令行是否包含 dplayer 相关路径
                        cmdline = proc.info.get('cmdline') or []
                        cmdline_str = ' '.join(cmdline).lower()
                        if 'dplayer' in cmdline_str and service_name.replace('dplayer-', '') in cmdline_str:
                            info['pid'] = proc.info['pid']
                            break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        # 3. 获取内存和 CPU
        if info['pid']:
            try:
                proc = psutil.Process(info['pid'])
                mem_info = proc.memory_info()
                info['memory_mb'] = round(mem_info.rss / (1024 * 1024), 1)
                # 注意：cpu_percent() 不再使用 interval 参数避免阻塞
                # 使用上一次的值（如果可用），否则设为 None
                # 如果需要实时 CPU，需要单独的后台任务采集
                try:
                    info['cpu_percent'] = proc.cpu_percent(interval=None)
                except Exception:
                    info['cpu_percent'] = None
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                info['pid'] = None
    except ImportError:
        pass

    return info


def _check_service_health(service_name: str) -> dict:
    """
    检查服务层健康状态（通过 HTTP 健康检查）
    
    Returns:
        dict: { status: 'healthy'|'unhealthy'|'unknown', latency_ms, detail }
    """
    meta = _SERVICE_META.get(service_name, {})
    health_url = meta.get('health_url')

    result = {
        'status': 'unknown',
        'latency_ms': None,
        'detail': '',
    }

    if not health_url:
        # web 服务自身，直接返回 healthy
        result['status'] = 'healthy'
        result['detail'] = '自身服务'
        return result

    try:
        import requests
        start = time.time()
        # 减小超时到 1.5 秒，避免阻塞太久
        resp = requests.get(health_url, timeout=1.5)
        latency = (time.time() - start) * 1000

        result['latency_ms'] = round(latency, 1)

        if resp.status_code == 200:
            # 判断是否需要解析 JSON（部分服务如 webui 只返回 HTML）
            if meta.get('health_check_json', True):
                try:
                    data = resp.json()
                    if data.get('status') == 'healthy':
                        result['status'] = 'healthy'
                        result['detail'] = '正常'
                    else:
                        result['status'] = 'unhealthy'
                        result['detail'] = f"状态异常: {data.get('status', 'unknown')}"
                except (ValueError, KeyError):
                    result['status'] = 'unhealthy'
                    result['detail'] = '响应格式异常'
            else:
                # 非 JSON 服务，HTTP 200 即为 healthy
                result['status'] = 'healthy'
                result['detail'] = '正常'
        else:
            result['status'] = 'unhealthy'
            result['detail'] = f"HTTP {resp.status_code}"
    except requests.exceptions.Timeout:
        result['status'] = 'unhealthy'
        result['detail'] = '超时（>1.5s）'
    except requests.exceptions.ConnectionError:
        result['status'] = 'unhealthy'
        result['detail'] = '连接失败'
    except Exception as e:
        result['status'] = 'unknown'
        result['detail'] = str(e)[:100]

    return result






# ============ 资源库文件夹自动感知 ============
def _restart_library_watchers():
    """（重新）启动资源库文件夹监控，供服务启动 / 新增文件夹后调用。

    监控路径优先从 resourced 查询（资源库/文件夹的磁盘路径），回退到现有 Video.local_path。
    文件的新增/删除/重命名会实时同步到 Video 表，无需手动扫描。
    """
    if not app_config.get('library_watch_enabled', True):
        log.debug('INFO', '资源库文件夹自动感知已通过配置禁用')
        return
    try:
        from library_watcher import start_library_watchers as _sw
        _sw(app=app, resource_bus=resource_bus, app_config=app_config,
            thumbnail_bus=thumbnail_bus, log=log)
    except Exception as e:
        log.debug('ERROR', f'启动资源库文件夹监控失败: {e}')


try:
    import threading as _tw
    _tw.Thread(target=_restart_library_watchers, daemon=True,
               name='library-watcher-boot').start()
except Exception as e:
    log.maintenance('WARN', f'资源库文件夹监控模块不可用: {e}')


# ============ 帖子（Post）API ============
# 帖子只持有对 resource_index 的引用，可自由引用视频 / 图片集（图集）/ 未来文本等，
# 同一资源可被多个帖子共享，且移动磁盘资源只需更新索引表一行即可全局跟随。

def _resolve_post_refs(refs):
    """将请求体中的引用解析为 (ResourceIndex, note) 列表。

    支持两种写法：
      - {resource_index_id: <id>}                                 直接指定索引
      - {type: 'video'|'gallery', id: <视频/图集实体 id>}            由实体反查其索引
    """
    result = []
    if not refs:
        return result
    for r in refs:
        if not isinstance(r, dict):
            continue
        ri_id = r.get('resource_index_id')
        if not ri_id:
            typ = (r.get('type') or r.get('kind') or '').lower()
            eid = r.get('id')
            if typ in ('video', 'video_file') and eid:
                v = Video.query.get(eid)
                if v and v.resource_index_id:
                    ri_id = v.resource_index_id
            elif typ in ('gallery', 'gallery_folder', 'image_set') and eid:
                c = Gallery.query.get(eid)
                if c and c.resource_index_id:
                    ri_id = c.resource_index_id
        if ri_id:
            ri = ResourceIndex.query.get(ri_id)
            if ri:
                result.append((ri, r.get('note', '') or ''))
    return result


def _build_post_refs(content, refs_param):
    """由帖子正文的内联标记构建 PostRef 列表（含 display_mode）。

    优先解析正文里的 [文字](res:ID:mode) 标记；若正文无标记，回退到传统的 refs 参数。
    """
    tokens = parse_post_content_tokens(content or '')
    built = []
    if tokens:
        for pos, t in enumerate(tokens):
            ri = ResourceIndex.query.get(t['resource_index_id'])
            if ri:
                built.append(PostRef(
                    resource_index_id=ri.id, position=pos,
                    note='', display_mode=t['display_mode']))
        return built
    for pos, (ri, note) in enumerate(_resolve_post_refs(refs_param)):
        built.append(PostRef(
            resource_index_id=ri.id, position=pos,
            note=note, display_mode='embed'))
    return built
















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
