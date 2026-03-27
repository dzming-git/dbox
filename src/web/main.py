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
check_service_launch('DPlayer Web Service', 'src/web/main.py')

print(f"[DEBUG] web.py loading from: {os.path.abspath(__file__)}")
print(f"[DEBUG] PROJECT_ROOT: {PROJECT_ROOT}")

from flask import Flask, jsonify, request, send_file, abort, Response, g, session, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from urllib.parse import quote, unquote
import json
import threading
from liblog import get_module_logger
log = get_module_logger()
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
except Exception as e:
    thumbnail_bus = None
    svc_mgr_bus = None
    print(f"[WARNING] 总线客户端初始化失败: {e}")

# 导入JWT SECRET_KEY（统一使用 backend/utils/jwt_authlib.py 中的配置）
from backend.utils.jwt_authlib import SECRET_KEY as JWT_SECRET_KEY

# 导入核心模块
from core.models import db, Video, Tag, VideoTag, UserInteraction, UserPreference, User, UserSession, UserRole, ROLE_NAMES
from core.models import VideoLibrary, LibraryPermission, LibraryUserGroup, LibraryUserGroupMember, LibraryAuditLog
from auth_service import AuthService, init_root_user

# 导入API蓝图
from api.auth_api import auth_bp
from api.playlist_api import playlist_bp
from api.system_api import system_bp
from backend.api.shared_watch_api import shared_watch_bp
from backend.api.auth_api_v2 import auth_v2_bp

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
print("[DEBUG] Initializing database...")
db.init_app(app)
with app.app_context():
    db.create_all()
    init_root_user()
    print("[DEBUG] Database initialized")

# ============ 注册蓝图 ============
print("[DEBUG] Registering blueprints...")
app.register_blueprint(auth_bp)
app.register_blueprint(auth_v2_bp)  # v2版本JWT认证API
app.register_blueprint(playlist_bp)
app.register_blueprint(system_bp)
app.register_blueprint(shared_watch_bp)  # 共享观看API

# ============ 认证装饰器 ============
def auth_required(f):
    """通用认证装饰器 - 同时支持 Session、JWT Bearer Token 和 URL query token"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # 优先检查 JWT Bearer Token
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
        
        # 回退到 URL query 参数 token（用于 video/audio 标签等无法自定义 header 的场景）
        if not token:
            token = request.args.get('token')
        
        if token:
            try:
                from authlib.jose import jwt as _jwt
                payload = _jwt.decode(token, JWT_SECRET_KEY)
                if payload.get('type') == 'access':
                    g.user_id = payload.get('user_id')
                    g.role = payload.get('role', 0)
                    g.username = payload.get('username')
                    return f(*args, **kwargs)
            except Exception as e:
                log.debug('WARN', f'JWT 认证失败: {e}')
                # JWT 无效时继续尝试 session
        
        # 回退到 Session 认证
        if 'user_id' in session:
            g.user_id = session.get('user_id')
            g.role = session.get('role', 0)
            g.username = session.get('username')
            return f(*args, **kwargs)
        
        return jsonify({'success': False, 'message': '未授权', 'code': 401}), 401
    return decorated

def admin_required(f):
    """管理员权限装饰器 - 需要 JWT 认证"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '')
        if token.startswith('Bearer '):
            token = token[7:]
        
        if not token:
            return jsonify({'success': False, 'message': '未授权', 'code': 401}), 401
        
        try:
            from authlib.jose import jwt
            SECRET_KEY = 'dplayer-jwt-secret-key-change-in-production-2024'
            payload = jwt.decode(token, SECRET_KEY)
            
            if payload.get('type') != 'access':
                return jsonify({'success': False, 'message': 'token 类型错误', 'code': 401}), 401
            
            g.user_id = payload.get('user_id')
            g.role = payload.get('role', 0)
            g.username = payload.get('username')
            
            # 检查是否是管理员或更高权限
            if g.role < UserRole.ADMIN:
                return jsonify({'success': False, 'message': '需要管理员权限', 'code': 403}), 403
            
            return f(*args, **kwargs)
        except Exception as e:
            return jsonify({'success': False, 'message': f'无效的 token: {str(e)}', 'code': 401}), 401
    
    return decorated

# ============ 配置管理 ============
CONFIG_FILE = os.path.join(_CONFIGS_DIR, 'web', 'config.json')

def load_config():
    default = {
        "scan_directories": [{"path": "M:/<媒体库>", "recursive": True, "enabled": True}],
        "auto_scan_on_startup": True,
        "supported_formats": [".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"],
        "default_tags": ["本地视频"],
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
def get_user_session():
    if 'user_session' not in session:
        session['user_session'] = str(random.randint(100000, 999999))
    return session['user_session']

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

# DIST_DIR = os.path.join(PROJECT_ROOT, 'static', 'dist')

# @app.route('/')
# def index():
#     """返回前端首页"""
#     return send_from_directory(DIST_DIR, 'index.html')

# @app.route('/assets/<path:filename>')
# def serve_assets(filename):
#     """返回前端资源文件"""
#     return send_from_directory(os.path.join(DIST_DIR, 'assets'), filename)

# @app.route('/favicon.svg')
# def serve_favicon():
#     """返回favicon"""
#     return send_from_directory(DIST_DIR, 'favicon.svg')

# ============ API 路由 ============

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

# --- 视频管理 ---

def get_allowed_library_ids():
    """
    获取当前用户允许访问的视频库ID列表
    返回: allowed_library_ids (list)
    """
    allowed_library_ids = []
    
    # 检查 Video 模型是否有 library_id 属性
    if not hasattr(Video, 'library_id'):
        return allowed_library_ids
    
    # 获取用户ID和角色 —— 优先 JWT token，其次 session
    user_id = None
    user_role = 0
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        try:
            from authlib.jose import jwt as _jwt
            _secret = 'dplayer-jwt-secret-key-change-in-production-2024'
            _payload = _jwt.decode(auth_header[7:], _secret)
            user_id = _payload.get('user_id')
            user_role = _payload.get('role', 0)
        except Exception:
            pass
    if not user_id and 'user_id' in session:
        user_id = session['user_id']
        user_role = session.get('role', 0)
    
    # 管理员和ROOT可以访问所有激活的库
    if user_role in [UserRole.ADMIN, UserRole.ROOT]:
        all_active_libs = VideoLibrary.query.filter_by(is_active=True).all()
        allowed_library_ids = [lib.id for lib in all_active_libs]
    elif user_id:
        # 已登录的普通用户：查询用户直接权限 + 用户组权限
        # 1. 获取用户直接权限的库
        user_perms = LibraryPermission.query.filter_by(user_id=user_id).all()
        for perm in user_perms:
            lib = VideoLibrary.query.get(perm.library_id)
            if lib and lib.is_active:
                allowed_library_ids.append(perm.library_id)
        
        # 2. 获取用户组权限的库
        user_groups = LibraryUserGroupMember.query.filter_by(user_id=user_id).all()
        for ugm in user_groups:
            group_perms = LibraryPermission.query.filter_by(group_id=ugm.group_id).all()
            for perm in group_perms:
                lib = VideoLibrary.query.get(perm.library_id)
                if lib and lib.is_active and perm.library_id not in allowed_library_ids:
                    allowed_library_ids.append(perm.library_id)
        
        # 3. 获取通用权限（user_id=NULL，表示所有人都可以访问）
        general_perms = LibraryPermission.query.filter_by(user_id=None).all()
        for perm in general_perms:
            lib = VideoLibrary.query.get(perm.library_id)
            if lib and lib.is_active and perm.library_id not in allowed_library_ids:
                allowed_library_ids.append(perm.library_id)
    else:
        # 未登录用户：只能看到主数据库的视频（library_id=NULL）
        # 以及有通用权限的库
        # 1. 获取通用权限的库
        general_perms = LibraryPermission.query.filter_by(user_id=None).all()
        for perm in general_perms:
            lib = VideoLibrary.query.get(perm.library_id)
            if lib and lib.is_active and perm.library_id not in allowed_library_ids:
                allowed_library_ids.append(perm.library_id)
    
    return allowed_library_ids


@app.route('/api/videos', methods=['GET'])
def get_videos():
    try:
        limit = request.args.get('limit', 20, type=int)
        offset = request.args.get('offset', 0, type=int)
        tag_id = request.args.get('tag_id', type=int)
        search = request.args.get('search', '').strip()
        filter_library_id = request.args.get('library_id', type=int)  # 管理员按库筛选
        sort = request.args.get('sort', 'recommended')  # 排序方式: recommended, name, created_at, view_count, priority, like_count
        order = request.args.get('order', 'desc')  # 排序方向: asc, desc

        query = Video.query

        # ============ 过滤被禁用的视频库 ============
        # 获取当前用户可访问的激活视频库ID列表
        allowed_library_ids = []

        # 检查 Video 模型是否有 library_id 属性
        has_library_id = hasattr(Video, 'library_id')

        if has_library_id:
            # 获取用户ID和角色 —— 优先 JWT token，其次 session
            user_id = None
            user_role = 0
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                try:
                    from authlib.jose import jwt as _jwt
                    _secret = 'dplayer-jwt-secret-key-change-in-production-2024'
                    _payload = _jwt.decode(auth_header[7:], _secret)
                    user_id = _payload.get('user_id')
                    user_role = _payload.get('role', 0)
                except Exception:
                    pass
            if not user_id and 'user_id' in session:
                user_id = session['user_id']
                user_role = session.get('role', 0)

            # 管理员和ROOT可以访问所有激活的库
            if user_role in [UserRole.ADMIN, UserRole.ROOT]:
                all_active_libs = VideoLibrary.query.filter_by(is_active=True).all()
                allowed_library_ids = [lib.id for lib in all_active_libs]
            elif user_id:
                # 已登录的普通用户：查询用户直接权限 + 用户组权限
                # 1. 获取用户直接权限的库
                user_perms = LibraryPermission.query.filter_by(user_id=user_id).all()
                for perm in user_perms:
                    lib = VideoLibrary.query.get(perm.library_id)
                    if lib and lib.is_active:
                        allowed_library_ids.append(perm.library_id)

                # 2. 获取用户组权限的库
                user_groups = LibraryUserGroupMember.query.filter_by(user_id=user_id).all()
                for ugm in user_groups:
                    group_perms = LibraryPermission.query.filter_by(group_id=ugm.group_id).all()
                    for perm in group_perms:
                        lib = VideoLibrary.query.get(perm.library_id)
                        if lib and lib.is_active and perm.library_id not in allowed_library_ids:
                            allowed_library_ids.append(perm.library_id)
            
            # 3. 获取通用权限（user_id=NULL，表示所有人都可以访问）
            # 这个在用户没有特定权限时也生效
            general_perms = LibraryPermission.query.filter_by(user_id=None).all()
            for perm in general_perms:
                lib = VideoLibrary.query.get(perm.library_id)
                if lib and lib.is_active and perm.library_id not in allowed_library_ids:
                    allowed_library_ids.append(perm.library_id)

            # 过滤条件：library_id 为 NULL（主数据库的视频）或在允许的视频库中
            if allowed_library_ids:
                query = query.filter(
                    (Video.library_id == None) |
                    (Video.library_id.in_(allowed_library_ids))
                )
            else:
                # 未登录或无权限用户只能看到主数据库的视频
                query = query.filter(Video.library_id == None)

        # 如果调用方指定了 library_id（管理员按库精确筛选），直接用精确过滤覆盖宽泛条件
        if filter_library_id is not None:
            query = Video.query.filter(Video.library_id == filter_library_id)

        # 搜索功能
        if search:
            query = query.filter(Video.title.ilike(f'%{search}%'))

        # 标签筛选
        if tag_id:
            query = query.join(VideoTag).filter(VideoTag.tag_id == tag_id)

        # ============ 重要：total 统计必须在权限过滤之后 ============
        # 获取总数（已应用权限过滤）
        total = query.count()

        # ============ 排序策略 ============
        from sqlalchemy import func, case

        # 根据 order 参数确定排序方向
        is_desc = order.lower() == 'desc'

        # 排序方式映射
        if sort == 'name':
            # 按视频名排序
            videos = query.order_by(Video.title.desc() if is_desc else Video.title.asc()).offset(offset).limit(limit).all()
        elif sort == 'created_at':
            # 按文件创建时间排序
            videos = query.order_by(Video.created_at.desc() if is_desc else Video.created_at.asc()).offset(offset).limit(limit).all()
        elif sort == 'view_count':
            # 按播放量排序
            videos = query.order_by(Video.view_count.desc() if is_desc else Video.view_count.asc()).offset(offset).limit(limit).all()
        elif sort == 'priority':
            # 按优先级排序
            videos = query.order_by(Video.priority.desc() if is_desc else Video.priority.asc()).offset(offset).limit(limit).all()
        elif sort == 'like_count':
            # 按点赞数排序
            videos = query.order_by(Video.like_count.desc() if is_desc else Video.like_count.asc()).offset(offset).limit(limit).all()
        elif sort == 'download_count':
            # 按下载数排序
            videos = query.order_by(Video.download_count.desc() if is_desc else Video.download_count.asc()).offset(offset).limit(limit).all()
        else:
            # 默认推荐排序：首页推荐带随机成分（仅支持倒序）
            # 如果没有指定 tag_id 和 search，则认为是首页推荐，加入随机成分
            if not tag_id and not search:
                # 使用 func.random() 为每个视频赋予随机权重
                # 排序公式：priority + view_count * 0.1 + random() * 50
                # 这样热门视频仍有优势，但随机视频也有机会排在前面
                videos = query.order_by(
                    (Video.priority + Video.view_count * 0.1 + func.random() * 50).desc()
                ).offset(offset).limit(limit).all()
            else:
                # 标签页或搜索结果按原排序规则
                videos = query.order_by(
                    (Video.priority + Video.view_count).desc()
                ).offset(offset).limit(limit).all()

        return jsonify({
            'success': True,
            'videos': [v.to_dict() for v in videos],
            'total': total,
            'sort': sort,
            'order': order
        })
    except Exception as e:
        log.debug('ERROR', f"获取视频列表失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/video/<video_hash>', methods=['GET'])
def get_video(video_hash):
    """获取单个视频详情 - 需要检查视频库权限"""
    try:
        video = Video.query.filter_by(hash=video_hash).first_or_404()
        
        # ============ 权限检查 ============
        # 检查视频是否属于某个视频库
        if video.library_id:
            # 获取用户ID和角色
            user_id = None
            user_role = 0
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                try:
                    from authlib.jose import jwt as _jwt
                    _secret = 'dplayer-jwt-secret-key-change-in-production-2024'
                    _payload = _jwt.decode(auth_header[7:], _secret)
                    user_id = _payload.get('user_id')
                    user_role = _payload.get('role', 0)
                except Exception:
                    pass
            if not user_id and 'user_id' in session:
                user_id = session['user_id']
                user_role = session.get('role', 0)
            
            # 管理员和ROOT可以访问所有视频
            if user_role not in [UserRole.ADMIN, UserRole.ROOT]:
                # 检查用户权限
                user_perm = LibraryPermission.query.filter_by(
                    library_id=video.library_id, user_id=user_id
                ).first()
                
                # 检查用户组权限
                has_access = bool(user_perm)
                if not has_access:
                    user_groups = LibraryUserGroupMember.query.filter_by(user_id=user_id).all()
                    for ugm in user_groups:
                        group_perm = LibraryPermission.query.filter_by(
                            library_id=video.library_id, group_id=ugm.group_id
                        ).first()
                        if group_perm:
                            has_access = True
                            break
                
                if not has_access:
                    return jsonify({
                        'success': False,
                        'message': '无权访问此视频',
                        'code': 403
                    }), 403
        
        return jsonify({'success': True, 'video': video.to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/video/<video_hash>/like', methods=['POST'])
def like_video(video_hash):
    try:
        video = Video.query.filter_by(hash=video_hash).first_or_404()
        video.like_count += 1
        record_interaction(video.id, get_user_session(), 'like', 2.0)
        db.session.commit()
        return jsonify({'success': True, 'like_count': video.like_count})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/video/<video_hash>/favorite', methods=['POST'])
def toggle_favorite(video_hash):
    try:
        video = Video.query.filter_by(hash=video_hash).first_or_404()
        user_session = get_user_session()
        
        interaction = UserInteraction.query.filter_by(
            video_id=video.id, user_session=user_session, interaction_type='favorite'
        ).first()
        
        if interaction:
            db.session.delete(interaction)
            favorited = False
        else:
            interaction = UserInteraction(
                video_id=video.id, user_session=user_session,
                interaction_type='favorite', interaction_score=5.0
            )
            db.session.add(interaction)
            favorited = True
        
        db.session.commit()
        log.operation('WEB', f"{'收藏' if favorited else '取消收藏'}视频: {video.title}")
        return jsonify({'success': True, 'favorited': favorited})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"收藏操作失败: {video_hash}, {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/video/<video_hash>', methods=['DELETE'])
def delete_video(video_hash):
    try:
        # 获取是否同时删除文件的选项（默认不删除文件）
        delete_file = request.json.get('delete_file', False) if request.json else False

        video = Video.query.filter_by(hash=video_hash).first_or_404()

        # 只有明确要求删除文件时才删除
        if delete_file and video.local_path and os.path.exists(video.local_path):
            os.remove(video.local_path)
            # 同时删除缩略图
            thumb_dir = os.path.join(_DATA_DIR, 'thumbnails')
            for ext in ['gif', 'jpg', 'png']:
                thumb_path = os.path.join(thumb_dir, f'{video_hash}.{ext}')
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)

        db.session.delete(video)
        db.session.commit()
        log.maintenance('INFO', f"删除视频: {video.title} (hash: {video_hash}), 删除文件: {delete_file}")
        return jsonify({'success': True, 'message': '视频已删除'})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"删除视频失败: {video_hash}, {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# --- 观看次数记录 ---

@app.route('/api/video/<video_hash>/view', methods=['POST'])
def increment_view_count(video_hash):
    """增加视频观看次数"""
    try:
        video = Video.query.filter_by(hash=video_hash).first_or_404()
        video.view_count = (video.view_count or 0) + 1
        db.session.commit()
        return jsonify({'success': True, 'view_count': video.view_count})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

# --- 视频播放 ---

@app.route('/api/videos/<int:video_id>/play', methods=['GET'])
@auth_required
def play_video(video_id):
    """播放视频 - 需要检查视频库权限"""
    try:
        video = Video.query.get(video_id)
        if not video:
            return jsonify({'success': False, 'message': '视频不存在'}), 404
        
        # ============ 权限检查 ============
        # 检查视频是否属于某个视频库
        if video.library_id:
            # 获取用户ID和角色
            user_id = g.user_id
            user_role = g.role
            
            # 管理员和ROOT可以访问所有视频
            if user_role not in [UserRole.ADMIN, UserRole.ROOT]:
                # 检查用户权限
                user_perm = LibraryPermission.query.filter_by(
                    library_id=video.library_id, user_id=user_id
                ).first()
                
                # 检查用户组权限
                has_access = bool(user_perm)
                if not has_access:
                    user_groups = LibraryUserGroupMember.query.filter_by(user_id=user_id).all()
                    for ugm in user_groups:
                        group_perm = LibraryPermission.query.filter_by(
                            library_id=video.library_id, group_id=ugm.group_id
                        ).first()
                        if group_perm:
                            has_access = True
                            break
                
                if not has_access:
                    return jsonify({
                        'success': False,
                        'message': '无权播放此视频',
                        'code': 403
                    }), 403
        
        video_path = video.local_path or video.url
        if not video_path or not os.path.exists(video_path):
            return jsonify({'success': False, 'message': '视频文件不存在'}), 404
        
        range_header = request.headers.get('Range', None)
        file_size = os.path.getsize(video_path)
        
        if range_header:
            match = re.search('bytes=(\d+)-(\d*)', range_header)
            byte1 = int(match.group(1)) if match else 0
            byte2 = int(match.group(2)) if match and match.group(2) else file_size - 1
            length = byte2 - byte1 + 1
            
            def generate():
                with open(video_path, 'rb') as f:
                    f.seek(byte1)
                    yield f.read(length)
            
            resp = Response(generate(), 206, mimetype='video/mp4', direct_passthrough=True)
            resp.headers.add('Content-Range', f'bytes {byte1}-{byte2}/{file_size}')
            resp.headers.add('Content-Length', str(length))
        else:
            def generate():
                with open(video_path, 'rb') as f:
                    while data := f.read(8192):
                        yield data
            resp = Response(generate(), 200, mimetype='video/mp4', direct_passthrough=True)
            resp.headers.add('Content-Length', str(file_size))
        
        return resp
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# --- 标签管理 ---

@app.route('/api/tags', methods=['GET'])
def get_tags():
    """获取标签列表 - 支持树形结构，融合模式可跨视频库聚合"""
    try:
        # 获取参数
        tree_mode = request.args.get('tree', 'false').lower() == 'true'
        library_id = request.args.get('library_id', type=int)  # 可选，按视频库筛选
        merge_mode = request.args.get('merge', 'false').lower() == 'true'  # 融合模式
        
        # ============ 获取用户可访问的视频库 ============
        user_id = None
        user_role = 0
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            try:
                from authlib.jose import jwt as _jwt
                _secret = 'dplayer-jwt-secret-key-change-in-production-2024'
                _payload = _jwt.decode(auth_header[7:], _secret)
                user_id = _payload.get('user_id')
                user_role = _payload.get('role', 0)
            except Exception:
                pass
        if not user_id and 'user_id' in session:
            user_id = session['user_id']
            user_role = session.get('role', 0)
        
        allowed_library_ids = []
        
        if user_id:
            if user_role in [UserRole.ADMIN, UserRole.ROOT]:
                all_active_libs = VideoLibrary.query.filter_by(is_active=True).all()
                allowed_library_ids = [lib.id for lib in all_active_libs]
            else:
                user_perms = LibraryPermission.query.filter_by(user_id=user_id).all()
                for perm in user_perms:
                    lib = VideoLibrary.query.get(perm.library_id)
                    if lib and lib.is_active:
                        allowed_library_ids.append(perm.library_id)
                
                user_groups = LibraryUserGroupMember.query.filter_by(user_id=user_id).all()
                for ugm in user_groups:
                    group_perms = LibraryPermission.query.filter_by(group_id=ugm.group_id).all()
                    for perm in group_perms:
                        lib = VideoLibrary.query.get(perm.library_id)
                        if lib and lib.is_active and perm.library_id not in allowed_library_ids:
                            allowed_library_ids.append(perm.library_id)
        
        is_admin = user_id and user_role in [2, 3]
        
        # 检查用户是否有视频库权限
        has_library_access = is_admin or (user_id and allowed_library_ids)
        
        # ============ 融合模式：合并相同路径的标签 ============
        if merge_mode:
            # 查询所有用户可见的标签（只有有视频库权限时才过滤）
            if has_library_access and not is_admin:
                query = Tag.query.filter(
                    (Tag.library_id == None) | 
                    (Tag.library_id.in_(allowed_library_ids))
                )
            else:
                query = Tag.query
            
            all_tags = query.all()
            
            # 按路径分组，合并视频数量
            from sqlalchemy import or_ as sql_or
            path_video_map = {}  # {path: total_video_count}
            
            for tag in all_tags:
                tag_ids = tag.get_all_child_ids()
                video_query = Video.query.join(VideoTag).filter(VideoTag.tag_id.in_(tag_ids))
                
                if has_library_access and not is_admin:
                    video_query = video_query.filter(
                        sql_or(
                            Video.library_id == None,
                            Video.library_id.in_(allowed_library_ids)
                        )
                    )
                
                video_count = video_query.count()
                
                if tag.path in path_video_map:
                    path_video_map[tag.path] += video_count
                else:
                    path_video_map[tag.path] = video_count
            
            # 构建融合后的标签列表
            result_tags = []
            seen_paths = set()
            for tag in all_tags:
                if tag.path in seen_paths:
                    continue
                seen_paths.add(tag.path)
                
                video_count = path_video_map.get(tag.path, 0)
                # 非管理员用户：如果没有视频库权限，不显示任何标签
                if not has_library_access:
                    continue
                # 如果没有可访问的活跃视频库（即使管理员），也不显示标签
                if not allowed_library_ids:
                    continue
                if video_count > 0:
                    tag_dict = tag.to_dict()
                    tag_dict['video_count'] = video_count
                    result_tags.append(tag_dict)
            
            result_tags.sort(key=lambda t: t['video_count'], reverse=True)
            
            if tree_mode:
                tree = _build_tag_tree(result_tags)
                return jsonify({'success': True, 'tags': tree})
            
            return jsonify({'success': True, 'tags': result_tags})
        
        # ============ 普通模式（原有逻辑）==========
        if has_library_access and not is_admin:
            query = Tag.query.filter(
                (Tag.library_id == None) | 
                (Tag.library_id.in_(allowed_library_ids))
            )
        else:
            query = Tag.query
        
        if library_id:
            query = query.filter(
                (Tag.library_id == None) | 
                (Tag.library_id == library_id)
            )
        
        tags = query.all()
        
        from sqlalchemy import or_ as sql_or
        result_tags = []
        for tag in tags:
            tag_ids = tag.get_all_child_ids()
            video_query = Video.query.join(VideoTag).filter(VideoTag.tag_id.in_(tag_ids))
            
            if has_library_access and not is_admin:
                video_query = video_query.filter(
                    sql_or(
                        Video.library_id == None,
                        Video.library_id.in_(allowed_library_ids)
                    )
                )
            
            video_count = video_query.count()
            
            # 非管理员用户：如果没有视频库权限，不显示任何标签
            if not has_library_access:
                continue

            # 如果没有可访问的活跃视频库（即使管理员），也不显示标签
            if not allowed_library_ids:
                continue

            if video_count > 0:
                tag_dict = tag.to_dict()
                tag_dict['video_count'] = video_count
                result_tags.append(tag_dict)
        
        result_tags.sort(key=lambda t: t['video_count'], reverse=True)
        
        if tree_mode:
            tree = _build_tag_tree(result_tags)
            return jsonify({'success': True, 'tags': tree})
        
        return jsonify({'success': True, 'tags': result_tags})
    except Exception as e:
        log.debug('ERROR', f"获取标签列表失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/tags/all', methods=['GET'])
def get_all_tags():
    """获取所有标签（不进行权限过滤）"""
    try:
        tags = Tag.query.all()
        result = []
        for tag in tags:
            result.append({
                'id': tag.id,
                'name': tag.name,
                'category': tag.category,
                'parent_id': tag.parent_id,
                'video_count': tag.video_count()
            })
        return jsonify({'success': True, 'tags': result})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


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
        library_id: 视频库ID（可选，null表示全局标签）
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
        
        # 查询是否已存在
        existing_tag = Tag.query.filter_by(
            path=current_path,
            library_id=library_id
        ).first()
        
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
    
    # 返回最终创建的标签
    return Tag.query.filter_by(
        path=current_path,
        library_id=library_id
    ).first()


@app.route('/api/tags', methods=['POST'])
def create_tag():
    """创建新标签 - 支持多级标签，按路径+视频库判断唯一性"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        if not name:
            return jsonify({'success': False, 'message': '标签名不能为空'}), 400
        
        if len(name) < 1 or len(name) > 20:
            return jsonify({'success': False, 'message': '标签名长度需在1-20字符之间'}), 400
        
        # 获取视频库ID（可选，null表示全局标签）
        library_id = data.get('library_id')
        
        # 计算路径
        parent_id = data.get('parent_id')
        if parent_id:
            parent_tag = Tag.query.get(parent_id)
            if not parent_tag:
                return jsonify({'success': False, 'message': '父标签不存在'}), 400
            # 避免循环引用
            if parent_tag.parent_id == int(parent_id) if parent_tag else False:
                return jsonify({'success': False, 'message': '不能设置自己的子标签为父标签'}), 400
            # 计算子标签路径
            parent_path = parent_tag.path if parent_tag.path != '/' else ''
            tag_path = f"{parent_path}/{name}"
        else:
            tag_path = f"/{name}"
        
        # 基于路径+视频库判断唯一性
        existing = Tag.query.filter_by(path=tag_path, library_id=library_id).first()
        if existing:
            return jsonify({'success': False, 'message': f'标签路径已存在: {tag_path}'}), 400
        
        tag = Tag(
            name=name,
            path=tag_path,
            category=data.get('category', '类型'),
            parent_id=parent_id,
            library_id=library_id
        )
        db.session.add(tag)
        db.session.commit()
        log.maintenance('INFO', f"创建标签: {name} (路径: {tag_path})")
        return jsonify({'success': True, 'tag': tag.to_dict()})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"创建标签失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# 保留旧路径以兼容
@app.route('/api/tags/add', methods=['POST'])
def add_tag():
    """创建新标签 - 旧路径兼容"""
    return create_tag()


@app.route('/api/video/<video_hash>/tags', methods=['POST'])
@admin_required
def set_video_tags(video_hash):
    """
    为视频设置标签（自动创建不存在的标签）
    请求体: { "tags": ["/动物/狗", "/动物/猫", "/可爱"] }
    用 "/" 分隔层级，如 "/动物/狗/哈士奇"
    """
    try:
        video = Video.query.filter_by(hash=video_hash).first()
        if not video:
            return jsonify({'success': False, 'message': '视频不存在'}), 404
        
        data = request.get_json()
        tag_paths = data.get('tags', [])
        
        if not tag_paths:
            return jsonify({'success': False, 'message': '标签列表不能为空'}), 400
        
        # 获取视频库ID（用于标签隔离）
        library_id = video.library_id
        
        # 先移除所有现有标签关联
        VideoTag.query.filter_by(video_id=video.id).delete()
        
        # 添加新标签
        created_tags = []
        for tag_path in tag_paths:
            if not tag_path:
                continue
            # 自动创建标签（如果不存在）
            tag = get_or_create_tag_by_path(tag_path, library_id)
            if tag:
                # 创建关联
                vt = VideoTag(video_id=video.id, tag_id=tag.id)
                db.session.add(vt)
                created_tags.append(tag.to_dict())
        
        db.session.commit()
        
        log.runtime('INFO', f"为视频设置标签: {len(created_tags)}个标签 (video_hash: {video_hash})")
        
        return jsonify({
            'success': True,
            'message': f'已设置 {len(created_tags)} 个标签',
            'tags': created_tags
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/video/<video_hash>/tags', methods=['DELETE'])
@admin_required
def remove_video_tag(video_hash):
    """
    从视频移除单个标签（引用计数为0时自动删除标签）
    请求体: { "tag_path": "/动物/狗" }
    """
    try:
        video = Video.query.filter_by(hash=video_hash).first()
        if not video:
            return jsonify({'success': False, 'message': '视频不存在'}), 404
        
        data = request.get_json()
        tag_path = data.get('tag_path', '').strip()
        
        if not tag_path:
            return jsonify({'success': False, 'message': '标签路径不能为空'}), 400
        
        # 查找标签
        library_id = video.library_id
        tag = Tag.query.filter_by(path=tag_path, library_id=library_id).first()
        
        if not tag:
            return jsonify({'success': False, 'message': '标签不存在'}), 404
        
        # 移除关联
        VideoTag.query.filter_by(video_id=video.id, tag_id=tag.id).delete()
        
        # 检查引用计数，如果为0则删除标签
        remaining_count = VideoTag.query.filter_by(tag_id=tag.id).count()
        if remaining_count == 0:
            # 删除标签及其子标签
            def delete_tag_and_children(tag_id):
                # 先递归删除子标签
                children = Tag.query.filter_by(parent_id=tag_id).all()
                for child in children:
                    delete_tag_and_children(child.id)
                # 删除标签
                Tag.query.filter_by(id=tag_id).delete()
            
            delete_tag_and_children(tag.id)
        
        db.session.commit()
        log.runtime('INFO', f"从视频移除标签: {tag_path} (video_hash: {video_hash})")
        
        return jsonify({
            'success': True,
            'message': '标签已移除' + ('（标签已删除）' if remaining_count == 0 else '')
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/tags/search', methods=['GET'])
def search_tags():
    """搜索标签 - 用于智能提示，按路径匹配"""
    try:
        keyword = request.args.get('q', '').strip()
        library_id = request.args.get('library_id', type=int)  # 可选，按视频库筛选
        limit = request.args.get('limit', 20, type=int)

        if not keyword:
            return jsonify({'success': True, 'tags': []})

        # 获取当前用户权限
        user_id = getattr(g, 'user_id', None)
        user_role = getattr(g, 'role', None)

        # 判断是否是管理员/ROOT
        is_admin = user_id and user_role in [2, 3]  # ADMIN=2, ROOT=3

        # 构建查询：匹配路径包含关键词的标签
        query = Tag.query.filter(Tag.path.like(f'%{keyword}%'))

        # ============ 优先级：如果指定了 library_id，优先返回该视频库的标签 ============
        if library_id:
            # 验证用户是否有权限访问该视频库
            if not is_admin:
                # 管理员/ROOT 可以搜索任何视频库的标签
                # 检查用户是否有权限访问该视频库
                user_perm = LibraryPermission.query.filter_by(
                    library_id=library_id, user_id=user_id
                ).first()

                # 检查用户组权限
                has_access = bool(user_perm)
                if not has_access:
                    user_groups = LibraryUserGroupMember.query.filter_by(user_id=user_id).all()
                    for ugm in user_groups:
                        group_perm = LibraryPermission.query.filter_by(
                            library_id=library_id, group_id=ugm.group_id
                        ).first()
                        if group_perm:
                            has_access = True
                            break

                # 如果没有权限，只能看全局标签
                if not has_access:
                    query = query.filter(Tag.library_id == None)
                else:
                    # 有权限：全局标签 + 该视频库标签
                    query = query.filter(
                        (Tag.library_id == None) |
                        (Tag.library_id == library_id)
                    )
            else:
                # 管理员：全局标签 + 该视频库标签
                query = query.filter(
                    (Tag.library_id == None) |
                    (Tag.library_id == library_id)
                )
        else:
            # 未指定 library_id：普通用户只能看到自己有权限的库的标签 + 全局标签
            if not is_admin:
                allowed_library_ids = []

                if user_id:
                    # 已登录普通用户：获取有权限的视频库ID
                    # 直接权限
                    perms = LibraryPermission.query.filter_by(user_id=user_id).all()
                    allowed_library_ids.extend([p.library_id for p in perms])

                    # 用户组权限
                    group_members = LibraryUserGroupMember.query.filter_by(user_id=user_id).all()
                    for gm in group_members:
                        group_perms = LibraryPermission.query.filter_by(group_id=gm.group_id).all()
                        allowed_library_ids.extend([p.library_id for p in group_perms])

                    # 允许查看：全局标签(null) + 有权限的视频库标签
                    if allowed_library_ids:
                        query = query.filter(
                            (Tag.library_id == None) |
                            (Tag.library_id.in_(allowed_library_ids))
                        )
                # else: 未登录用户，只能看到全局标签

        # 限制结果数量
        tags = query.order_by(Tag.path).limit(limit).all()

        return jsonify({
            'success': True,
            'tags': [t.to_dict() for t in tags]
        })
    except Exception as e:
        log.debug('ERROR', f"搜索标签失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/tags/<int:tag_id>', methods=['PUT'])
def update_tag(tag_id):
    """更新标签 - PUT方法"""
    return _do_update_tag(tag_id)

@app.route('/api/tags/update/<int:tag_id>', methods=['POST'])
def update_tag_post(tag_id):
    """更新标签 - POST方法（兼容前端）"""
    return _do_update_tag(tag_id)

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

@app.route('/api/tags/<int:tag_id>', methods=['DELETE'])
def delete_tag(tag_id):
    try:
        tag = Tag.query.get_or_404(tag_id)
        
        # 处理子标签：将子标签提升为顶级标签
        for child in tag.children:
            child.parent_id = None
        
        # 删除标签与视频的关联
        VideoTag.query.filter_by(tag_id=tag_id).delete()
        
        # 删除标签
        db.session.delete(tag)
        db.session.commit()
        log.maintenance('INFO', f"删除标签: {tag.name} (ID: {tag_id})")
        return jsonify({'success': True, 'message': '标签已删除'})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"删除标签失败: {tag_id}, {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# --- 管理后台 API ---

@app.route('/api/admin/users', methods=['GET'])
@admin_required
def get_admin_users():
    """获取用户列表（管理员）"""
    try:
        users = User.query.all()
        return jsonify({
            'success': True,
            'users': [{
                'id': u.id,
                'username': u.username,
                'role': u.role,
                'role_name': u.role_name,
                'created_at': u.created_at.isoformat() if u.created_at else None
            } for u in users]
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/users', methods=['POST'])
@admin_required
def create_admin_user():
    """创建新用户（管理员）"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        role_str = data.get('role', 'user')
        
        # 将字符串角色转换为数字
        role_map = {
            'guest': UserRole.GUEST,
            'user': UserRole.USER,
            'admin': UserRole.ADMIN,
            'root': UserRole.ROOT
        }
        role = role_map.get(role_str, UserRole.USER)
        
        if not username or not password:
            return jsonify({'success': False, 'message': '用户名和密码不能为空'}), 400
        
        if User.query.filter_by(username=username).first():
            return jsonify({'success': False, 'message': '用户名已存在'}), 400
        
        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        log.maintenance('INFO', f"创建用户: {username} (角色: {user.role_name})")
        
        return jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'role': user.role,
                'role_name': user.role_name
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/users/<int:user_id>', methods=['PUT'])
@admin_required
def update_admin_user(user_id):
    """更新用户信息（管理员）"""
    try:
        user = User.query.get_or_404(user_id)
        data = request.get_json()

        # 更新用户名
        if 'username' in data:
            new_username = data['username'].strip()
            if not new_username:
                return jsonify({'success': False, 'message': '用户名不能为空'}), 400
            # 检查用户名是否已被其他用户占用
            existing_user = User.query.filter_by(username=new_username).first()
            if existing_user and existing_user.id != user_id:
                return jsonify({'success': False, 'message': '用户名已存在'}), 400
            user.username = new_username

        # 更新角色
        if 'role' in data:
            role_map = {
                'guest': UserRole.GUEST,
                'user': UserRole.USER,
                'admin': UserRole.ADMIN,
                'root': UserRole.ROOT
            }
            user.role = role_map.get(data['role'], UserRole.USER)

        # 更新密码（如果提供了）
        if data.get('password'):
            user.set_password(data['password'])

        db.session.commit()
        log.maintenance('INFO', f"更新用户信息: {user.username} (ID: {user_id})")

        return jsonify({
            'success': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'role': user.role,
                'role_name': user.role_name
            }
        })
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"更新用户信息失败: {user_id}, {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_admin_user(user_id):
    """删除用户（管理员）"""
    try:
        user = User.query.get_or_404(user_id)
        if user.id == g.user_id:
            return jsonify({'success': False, 'message': '不能删除当前登录用户'}), 400
        db.session.delete(user)
        db.session.commit()
        log.maintenance('INFO', f"删除用户: {user.username} (ID: {user_id})")
        return jsonify({'success': True, 'message': '用户已删除'})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"删除用户失败: {user_id}, {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/config', methods=['GET'])
@admin_required
def get_system_config():
    """获取系统配置"""
    try:
        # 从数据库或配置文件读取
        config = {
            'max_upload_size': 1024,  # MB
            'thumbnail_quality': 85,
            'auto_sync': True,
            'allow_register': False
        }
        return jsonify({'success': True, 'config': config})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/config', methods=['POST'])
@admin_required
def update_system_config():
    """更新系统配置"""
    try:
        data = request.get_json()
        # 这里可以保存到数据库或配置文件
        return jsonify({'success': True, 'message': '配置已保存'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/videos/batch-delete', methods=['POST'])
@admin_required
def batch_delete_videos():
    """批量删除视频"""
    try:
        data = request.get_json()
        hashes = data.get('hashes', [])
        # 获取是否同时删除文件的选项（默认不删除文件）
        delete_file = data.get('delete_file', False)

        if not hashes:
            return jsonify({'success': False, 'message': '未选择视频'}), 400

        deleted_count = 0
        for video_hash in hashes:
            video = Video.query.filter_by(hash=video_hash).first()
            if video:
                # 如果选择删除文件，同时删除视频文件和缩略图
                if delete_file and video.local_path and os.path.exists(video.local_path):
                    os.remove(video.local_path)
                    thumb_dir = os.path.join(_DATA_DIR, 'thumbnails')
                    for ext in ['gif', 'jpg', 'png']:
                        thumb_path = os.path.join(thumb_dir, f'{video_hash}.{ext}')
                        if os.path.exists(thumb_path):
                            os.remove(thumb_path)

                # 删除关联记录
                UserInteraction.query.filter_by(video_id=video.id).delete()
                VideoTag.query.filter_by(video_id=video.id).delete()
                db.session.delete(video)
                deleted_count += 1

        db.session.commit()
        log.maintenance('INFO', f"批量删除视频: {deleted_count}个, 删除文件: {delete_file}")
        return jsonify({
            'success': True,
            'message': f'已删除 {deleted_count} 个视频',
            'deleted_count': deleted_count
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/videos/<video_hash>/update', methods=['POST'])
@admin_required
def update_video_info(video_hash):
    """更新视频信息"""
    try:
        video = Video.query.filter_by(hash=video_hash).first_or_404()
        data = request.get_json()
        
        if 'title' in data:
            video.title = data['title'].strip()
        if 'description' in data:
            video.description = data.get('description', '').strip()
        if 'priority' in data:
            priority = data['priority']
            # 验证优先级范围 0-100
            if not isinstance(priority, (int, float)):
                return jsonify({'success': False, 'message': '优先级必须是数字'}), 400
            if priority < 0 or priority > 100:
                return jsonify({'success': False, 'message': '优先级必须在 0-100 之间'}), 400
            video.priority = int(priority)
        
        db.session.commit()
        log.runtime('INFO', f"更新视频信息: {video.title}")
        return jsonify({'success': True, 'video': video.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/videos/batch-update-priority', methods=['POST'])
@admin_required
def batch_update_priority():
    """批量设置视频优先级"""
    try:
        data = request.get_json()
        hashes = data.get('hashes', [])
        priority = data.get('priority')
        
        if not hashes:
            return jsonify({'success': False, 'message': '未选择视频'}), 400
        
        # 验证优先级
        if priority is None:
            return jsonify({'success': False, 'message': '请提供优先级值'}), 400
        if not isinstance(priority, (int, float)):
            return jsonify({'success': False, 'message': '优先级必须是数字'}), 400
        if priority < 0 or priority > 100:
            return jsonify({'success': False, 'message': '优先级必须在 0-100 之间'}), 400
        
        updated_count = 0
        for video_hash in hashes:
            video = Video.query.filter_by(hash=video_hash).first()
            if video:
                video.priority = int(priority)
                updated_count += 1
        
        db.session.commit()
        log.runtime('INFO', f"批量更新优先级: {updated_count}个视频, 优先级: {priority}")
        return jsonify({
            'success': True,
            'message': f'已更新 {updated_count} 个视频的优先级',
            'updated_count': updated_count
        })
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"批量更新优先级失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# --- 缩略图服务 ---

@app.route('/thumbnail/<video_hash>')
def get_thumbnail(video_hash):
    """获取缩略图，支持懒加载生成 - 需要检查视频库权限"""
    thumb_dir = os.path.join(_DATA_DIR, 'thumbnails')

    # 先尝试查找已存在的文件
    for ext in ['gif', 'jpg', 'png']:
        path = os.path.join(thumb_dir, f'{video_hash}.{ext}')
        if os.path.exists(path):
            resp = send_file(path, mimetype=f'image/{ext}')
            resp.cache_control.max_age = 3600
            return resp

    # 文件不存在，尝试懒加载生成
    try:
        # 查找视频的本地路径
        video = Video.query.filter_by(hash=video_hash).first()
        if not video or not video.local_path:
            # 没有视频记录或本地路径，返回404
            abort(404)

        # ============ 权限检查 ============
        # 检查视频是否属于某个视频库
        if video.library_id:
            # 获取用户ID和角色
            user_id = None
            user_role = 0

            # 方式1: 从 Authorization header 获取 token
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                try:
                    from authlib.jose import jwt as _jwt
                    _secret = 'dplayer-jwt-secret-key-change-in-production-2024'
                    _payload = _jwt.decode(auth_header[7:], _secret)
                    user_id = _payload.get('user_id')
                    user_role = _payload.get('role', 0)
                except Exception:
                    pass

            # 方式2: 从查询参数 token 获取（用于 <img> 标签）
            if not user_id:
                query_token = request.args.get('token', '')
                if query_token:
                    try:
                        from authlib.jose import jwt as _jwt
                        _secret = 'dplayer-jwt-secret-key-change-in-production-2024'
                        _payload = _jwt.decode(query_token, _secret)
                        user_id = _payload.get('user_id')
                        user_role = _payload.get('role', 0)
                    except Exception:
                        pass

            # 方式3: 从 session 获取
            if not user_id and 'user_id' in session:
                user_id = session['user_id']
                user_role = session.get('role', 0)

            # 管理员和ROOT可以访问所有缩略图
            if user_role not in [UserRole.ADMIN, UserRole.ROOT]:
                # 检查用户权限
                user_perm = LibraryPermission.query.filter_by(
                    library_id=video.library_id, user_id=user_id
                ).first()
                
                # 检查通用权限（user_id=NULL 表示所有人都可以访问）
                general_perm = LibraryPermission.query.filter_by(
                    library_id=video.library_id, user_id=None
                ).first()

                # 检查用户组权限
                has_access = bool(user_perm) or bool(general_perm)
                if not has_access:
                    user_groups = LibraryUserGroupMember.query.filter_by(user_id=user_id).all()
                    for ugm in user_groups:
                        group_perm = LibraryPermission.query.filter_by(
                            library_id=video.library_id, group_id=ugm.group_id
                        ).first()
                        if group_perm:
                            has_access = True
                            break

                if not has_access:
                    abort(403)

        # 调用缩略图服务异步生成（后台线程，不阻塞当前请求）
        if thumbnail_bus:
            video_path = video.local_path
            _hash = video_hash

            def _async_generate(vp, vh):
                try:
                    thumbnail_bus.call_method(
                        service='com.dplayer.thumbnaild',
                        interface='com.dplayer.Thumbnaild',
                        method='Generate',
                        params={'video_path': vp, 'video_hash': vh, 'output_format': 'gif'}
                    )
                except Exception as e:
                    log.debug('ERROR', f"后台封面生成失败: {e}")

            threading.Thread(target=_async_generate, args=(video_path, _hash), daemon=True).start()

        # 服务不可用或生成失败，返回 JSON 状态让前端轮询
        return jsonify({
            'success': False,
            'status': 'generating',
            'message': '缩略图正在生成中',
            'video_hash': video_hash
        }), 202

    except Exception as e:
        log.debug('ERROR', f"缩略图生成失败: {e}")
        return jsonify({
            'success': False,
            'status': 'error',
            'message': str(e),
            'video_hash': video_hash
        }), 202


@app.route('/api/thumbnail/status/<video_hash>', methods=['GET'])
def get_thumbnail_status(video_hash):
    """检查缩略图生成状态，返回进度信息"""
    thumb_dir = os.path.join(_DATA_DIR, 'thumbnails')

    # 检查文件是否存在
    for ext in ['gif', 'jpg', 'png']:
        path = os.path.join(thumb_dir, f'{video_hash}.{ext}')
        if os.path.exists(path):
            # 返回不带扩展名的URL，由前端添加token或后端处理
            return jsonify({
                'success': True,
                'status': 'ready',
                'progress': 100,
                'url': f'/thumbnail/{video_hash}',
                'format': ext
            })

    # 文件不存在，查询缩略图服务任务状态
    if thumbnail_bus:
        try:
            # 查询任务状态
            result = thumbnail_bus.call_method(
                service='com.dplayer.thumbnaild',
                interface='com.dplayer.Thumbnaild',
                method='GetStatus',
                params={'video_hash': video_hash}
            )
            if result and result.get('success'):
                # 缩略图服务返回的数据格式: {success: true, task_id: ..., status: ..., progress: ...}
                task_status = result.get('status', 'unknown')
                progress = result.get('progress', 0)

                # 映射状态
                status_map = {
                    'pending': 'pending',
                    'processing': 'processing',
                    'completed': 'ready',
                    'failed': 'failed'
                }
                mapped_status = status_map.get(task_status, task_status)

                # 如果是已完成，添加URL
                response_data = {
                    'success': True,
                    'status': mapped_status,
                    'progress': progress
                }
                if mapped_status == 'ready':
                    # 从缩略图服务获取格式信息
                    thumb_format = result.get('format', 'gif')
                    response_data['url'] = f'/thumbnail/{video_hash}'
                    response_data['format'] = thumb_format
                else:
                    response_data['message'] = f'缩略图生成中 ({progress}%)'

                return jsonify(response_data)
        except Exception as e:
            log.debug('ERROR', f"查询缩略图任务状态失败: {e}")

    # 没有找到任务，尝试自动触发生成
    try:
        video = Video.query.filter_by(hash=video_hash).first()
        if video and video.local_path and thumbnail_bus:
            # 检查权限
            has_permission = True
            if video.library_id:
                user_id = None
                user_role = 0
                
                # 从 Authorization header 获取 token
                auth_header = request.headers.get('Authorization', '')
                if auth_header.startswith('Bearer '):
                    try:
                        token = auth_header.replace('Bearer ', '')
                        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
                        user_id = payload.get('user_id')
                        user_role = payload.get('role', 0)
                    except:
                        pass
                
                # 从 session 获取
                if user_id is None:
                    user_id = session.get('user_id')
                    user_role = session.get('role', 0)
                
                # 权限检查
                if user_role < 2 and user_id:  # 非管理员
                    from models import LibraryPermission, LibraryUserGroupMember
                    has_perm = LibraryPermission.query.filter_by(
                        library_id=video.library_id, user_id=user_id
                    ).first()
                    if not has_perm:
                        user_groups = LibraryUserGroupMember.query.filter_by(user_id=user_id).all()
                        has_group_perm = False
                        for ugm in user_groups:
                            group_perm = LibraryPermission.query.filter_by(
                                library_id=video.library_id, group_id=ugm.group_id
                            ).first()
                            if group_perm:
                                has_group_perm = True
                                break
                        if not has_group_perm:
                            has_permission = False
            
            if has_permission and thumbnail_bus:
                # 提交生成任务（后台线程，不阻塞请求）
                _vp = video.local_path
                _vh = video_hash

                def _async_gen(vp, vh):
                    try:
                        thumbnail_bus.call_method(
                            service='com.dplayer.thumbnaild',
                            interface='com.dplayer.Thumbnaild',
                            method='Generate',
                            params={'video_path': vp, 'video_hash': vh, 'output_format': 'gif'}
                        )
                    except Exception as e:
                        log.debug('ERROR', f"后台封面生成失败: {e}")

                threading.Thread(target=_async_gen, args=(_vp, _vh), daemon=True).start()

                return jsonify({
                    'success': True,
                    'status': 'pending',
                    'progress': 0,
                    'message': '缩略图生成任务已提交'
                })
    except Exception as e:
        log.debug('ERROR', f"自动触发生成缩略图失败: {e}")
    
    return jsonify({
        'success': False,
        'status': 'not_found',
        'progress': 0,
        'message': '缩略图尚未生成'
    })


@app.route('/api/thumbnail/<video_hash>', methods=['DELETE'])
def delete_thumbnail(video_hash):
    """删除指定视频的缩略图"""
    thumb_dir = os.path.join(_DATA_DIR, 'thumbnails')

    deleted = False
    # 删除所有格式的缩略图文件
    for ext in ['gif', 'jpg', 'png']:
        path = os.path.join(thumb_dir, f'{video_hash}.{ext}')
        if os.path.exists(path):
            try:
                os.remove(path)
                deleted = True
            except Exception as e:
                log.debug('ERROR', f"删除缩略图文件失败: {e}")

    if deleted:
        return jsonify({'success': True, 'message': '缩略图已删除'})
    else:
        return jsonify({'success': False, 'message': '缩略图文件不存在'})


@app.route('/api/thumbnail/regenerate/<video_hash>', methods=['POST'])
def regenerate_thumbnail(video_hash):
    """重新生成指定视频的缩略图"""
    # 先删除旧缩略图
    thumb_dir = os.path.join(_DATA_DIR, 'thumbnails')
    for ext in ['gif', 'jpg', 'png']:
        path = os.path.join(thumb_dir, f'{video_hash}.{ext}')
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                log.debug('ERROR', f"删除旧缩略图失败: {e}")

    # 查找视频
    video = Video.query.filter_by(hash=video_hash).first()
    if not video or not video.local_path:
        return jsonify({'success': False, 'message': '视频不存在或无本地路径'}), 404

    # 调用缩略图服务重新生成
    if thumbnail_bus:
        try:
            result = thumbnail_bus.call_method(
                service='com.dplayer.thumbnaild',
                interface='com.dplayer.Thumbnaild',
                method='Generate',
                params={'video_path': video.local_path, 'video_hash': video_hash, 'output_format': 'gif'}
            )
            if result and result.get('success'):
                return jsonify({
                    'success': True,
                    'message': '缩略图重新生成中',
                    'task_id': result.get('task_id')
                })
            else:
                return jsonify({'success': False, 'message': result.get('error', '生成失败')}), 500
        except Exception as e:
            log.debug('ERROR', f"重新生成缩略图失败: {e}")
            return jsonify({'success': False, 'message': str(e)}), 500
    else:
        return jsonify({'success': False, 'message': '缩略图服务不可用'}), 503

# --- 配置 API ---

@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify({'success': True, 'config': app_config})

@app.route('/api/config', methods=['PUT'])
def update_config():
    try:
        data = request.get_json()
        for k, v in data.items():
            app_config[k] = v
        if save_config(app_config):
            log.maintenance('INFO', f"更新配置文件: {list(data.keys())}")
            return jsonify({'success': True, 'config': app_config})
        return jsonify({'success': False, 'message': '保存失败'}), 500
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# --- 上传 API ---

@app.route('/api/upload', methods=['POST'])
@auth_required
def upload_video():
    """上传视频文件"""
    try:
        if 'video' not in request.files:
            return jsonify({'success': False, 'message': '未找到视频文件'}), 400
        
        file = request.files['video']
        if file.filename == '':
            return jsonify({'success': False, 'message': '未选择文件'}), 400
        
        # 检查文件格式
        allowed_extensions = {'.mp4', '.avi', '.mkv', '.mov', '.webm', '.flv', '.wmv'}
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in allowed_extensions:
            return jsonify({
                'success': False, 
                'message': f'不支持的文件格式，请上传 {", ".join(allowed_extensions)} 格式的视频'
            }), 400
        
        # 创建上传目录
        upload_dir = os.path.join(_DATA_DIR, 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        
        # 生成唯一文件名
        import uuid
        unique_id = str(uuid.uuid4())[:8]
        safe_filename = f"{unique_id}_{file.filename}"
        file_path = os.path.join(upload_dir, safe_filename)
        
        # 保存文件
        file.save(file_path)
        
        # 生成视频hash
        video_hash = Video.generate_hash(file_path)
        
        # 检查是否已存在
        existing = Video.query.filter_by(hash=video_hash).first()
        if existing:
            os.remove(file_path)
            return jsonify({
                'success': False,
                'message': '该视频已存在',
                'video': existing.to_dict()
            }), 409
        
        # 获取文件大小
        file_size = os.path.getsize(file_path)
        
        # 获取表单数据
        title = request.form.get('title', '').strip() or os.path.splitext(file.filename)[0]
        description = request.form.get('description', '').strip()
        library_id = request.form.get('library_id')
        
        # 检查视频集权限（仅管理员可上传到任意视频集）
        if library_id:
            library_id = int(library_id)
            library = VideoLibrary.query.get(library_id)
            if not library:
                os.remove(file_path)
                return jsonify({'success': False, 'message': '视频集不存在'}), 400
            
            # 检查权限 - ROOT 和管理员可以上传到任意视频库
            if g.role not in [UserRole.ADMIN, UserRole.ROOT]:
                # 检查直接权限
                perm = LibraryPermission.query.filter_by(
                    library_id=library_id, user_id=g.user_id
                ).first()
                # 检查用户组权限
                has_permission = False
                if perm and perm.access_level in ['full', 'write']:
                    has_permission = True
                else:
                    members = LibraryUserGroupMember.query.filter_by(user_id=g.user_id).all()
                    for m in members:
                        group_perm = LibraryPermission.query.filter_by(
                            library_id=library_id, group_id=m.group_id
                        ).first()
                        if group_perm and group_perm.access_level in ['full', 'write']:
                            has_permission = True
                            break
                
                if not has_permission:
                    os.remove(file_path)
                    return jsonify({'success': False, 'message': '无权上传到该视频集'}), 403
        else:
            library_id = None
        
        # 创建视频记录
        video = Video(
            hash=video_hash,
            title=title,
            description=description,
            url=f'/local_video/{quote(file_path.replace(chr(92), "/"), safe=":/")}',
            local_path=file_path,
            file_size=file_size,
            duration='00:00',  # 后续可以提取真实时长
            thumbnail=f'/thumbnail/{video_hash}',
            library_id=library_id
        )
        
        db.session.add(video)
        db.session.commit()
        log.maintenance('INFO', f"上传视频: {title} (hash: {video_hash}, 大小: {file_size})")
        
        # 异步生成缩略图（这里简化处理）
        # TODO: 调用缩略图服务生成真实缩略图
        
        return jsonify({
            'success': True,
            'message': '上传成功',
            'video': video.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

# --- 状态 API ---

@app.route('/api/status')
def status():
    try:
        # 获取用户权限过滤后的视频数量
        allowed_library_ids = get_allowed_library_ids()
        
        if allowed_library_ids:
            # 过滤：library_id 为 NULL（主数据库的视频）或在允许的视频库中
            filtered_query = Video.query.filter(
                (Video.library_id == None) |
                (Video.library_id.in_(allowed_library_ids))
            )
            video_count = filtered_query.count()
        else:
            # 未登录或无权限用户只能看到主数据库的视频
            video_count = Video.query.filter(Video.library_id == None).count()
        
        return jsonify({
            'success': True,
            'status': 'running',
            'database': {
                'videos': video_count,
                'tags': Tag.query.count()
            },
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# --- 扫描 API ---

@app.route('/api/scan', methods=['POST'])
def scan_videos():
    try:
        total_added = 0
        for dir_cfg in app_config.get('scan_directories', []):
            if not dir_cfg.get('enabled', True):
                continue
            
            dir_path = dir_cfg.get('path', '')
            if not os.path.exists(dir_path):
                continue
            
            for root, _, files in os.walk(dir_path):
                for f in files:
                    if any(f.lower().endswith(ext) for ext in app_config.get('supported_formats', [])):
                        video_path = os.path.join(root, f)
                        video_hash = Video.generate_hash(video_path)
                        
                        if Video.query.filter_by(hash=video_hash).first():
                            continue
                        
                        title = os.path.splitext(f)[0]
                        video = Video(
                            hash=video_hash,
                            title=title,
                            description=f'本地视频: {f}',
                            url=f'/local_video/{quote(video_path.replace(chr(92), "/"), safe=":/")}',
                            thumbnail=f'/thumbnail/{video_hash}',
                            is_downloaded=True,
                            local_path=video_path
                        )
                        db.session.add(video)
                        db.session.flush()
                        
                        for tag_name in app_config.get('default_tags', ['本地视频']):
                            tag = Tag.query.filter_by(name=tag_name).first()
                            if not tag:
                                tag = Tag(name=tag_name, category='类型')
                                db.session.add(tag)
                                db.session.flush()
                            db.session.add(VideoTag(video_id=video.id, tag_id=tag.id))
                        
                        total_added += 1
        
        db.session.commit()
        return jsonify({'success': True, 'message': f'添加了 {total_added} 个视频', 'total_added': total_added})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

# --- 本地视频服务 ---

@app.route('/local_video/<path:video_path>')
def serve_local_video(video_path):
    try:
        # 解码并规范化路径
        video_path = unquote(video_path)
        # 处理双斜杠、多余斜杠等问题（如 C://Users// -> C:/Users/）
        while '//' in video_path:
            video_path = video_path.replace('//', '/')
        # 将斜杠转换为系统路径分隔符
        video_path = video_path.replace('/', os.sep)

        log.runtime('INFO', f"[serve_local_video] 原始请求: {request.path}, 解析后: {video_path}")

        # 获取扫描目录白名单
        scan_dirs = [cfg['path'].replace('\\', '/') for cfg in app_config.get('scan_directories', [])]

        # 白名单检查：1. 扫描目录 2. 数据库中已有视频的 local_path
        allowed = any(video_path.startswith(d.replace('/', os.sep)) for d in scan_dirs)

        # 如果不在扫描目录，检查是否在数据库中
        if not allowed:
            # 查找最后一个路径分隔符后的文件名，用文件名匹配
            filename = os.path.basename(video_path)
            existing_video = Video.query.filter(Video.local_path.like(f'%{filename}')).first()
            if existing_video:
                # 检查路径是否相同（忽略斜杠方向）
                db_path = existing_video.local_path.replace('/', '\\').replace('\\\\', '\\')
                req_path = video_path.replace('/', '\\').replace('\\\\', '\\')
                if db_path == req_path or db_path.endswith(req_path) or req_path.endswith(db_path):
                    allowed = True
                    log.runtime('INFO', f"[serve_local_video] 路径在数据库中找到: {video_path}")

        if not allowed:
            log.debug('WARN', f"[serve_local_video] 路径未通过白名单: {video_path}")
            abort(403)
        if not os.path.exists(video_path):
            log.debug('WARN', f"[serve_local_video] 文件不存在: {video_path}")
            abort(403)
        return send_file(video_path, mimetype='video/mp4')
    except Exception as e:
        log.debug('ERROR', f"[serve_local_video] 错误: {str(e)}, 路径: {video_path if 'video_path' in dir() else 'unknown'}")
        abort(500)

# ============ 视频库管理 API =================

@app.route('/api/admin/libraries', methods=['GET'])
@admin_required
def get_libraries():
    """获取所有视频库列表"""
    try:
        libraries = VideoLibrary.query.order_by(VideoLibrary.created_at.desc()).all()
        result = []
        for lib in libraries:
            lib_dict = lib.to_dict(include_stats=True)
            try:
                lib_dict['video_count'] = Video.query.filter_by(library_id=lib.id).count()
            except Exception:
                lib_dict['video_count'] = 0
            result.append(lib_dict)
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        log.debug('ERROR', f"获取视频库列表失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/libraries', methods=['POST'])
@admin_required
def create_library():
    """创建新视频库"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        
        # 自动生成数据库文件名：库名拼音或时间戳
        import time
        import re
        if not name:
            return jsonify({'success': False, 'message': '请输入视频库名称'}), 400

        # 检查名称是否重复
        if VideoLibrary.query.filter_by(name=name).first():
            return jsonify({'success': False, 'message': '视频库名称已存在'}), 400

        # 自动生成数据库文件名（使用时间戳确保唯一性）
        safe_name = re.sub(r'[^\w\u4e00-\u9fff]', '_', name)  # 保留中文、字母、数字、下划线
        db_file = f"{safe_name}_{int(time.time())}.db"
        
        # 确保文件名唯一
        while VideoLibrary.query.filter_by(db_file=db_file).first():
            db_file = f"{safe_name}_{int(time.time())}_{random.randint(1000,9999)}.db"

        # 创建视频库
        library = VideoLibrary(
            name=name,
            description=description,
            db_path='libraries',
            db_file=db_file,
            is_active=True,
            config=data.get('config', {})
        )

        # 确保目录存在
        os.makedirs(library.db_path, exist_ok=True)

        # 创建数据库文件（从模板复制或创建空数据库）
        db_full_path = library.full_db_path
        if not os.path.exists(db_full_path):
            # 从现有数据库复制结构
            import shutil
            template_db = os.path.join(_DATA_DIR, 'databases', 'dplayer.db')
            if os.path.exists(template_db):
                shutil.copy2(template_db, db_full_path)
            else:
                # 创建空数据库
                db.create_all()

        db.session.add(library)
        db.session.commit()

        return jsonify({'success': True, 'data': library.to_dict()})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"创建视频库失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/libraries/<int:library_id>', methods=['GET'])
@admin_required
def get_library(library_id):
    """获取视频库详情"""
    try:
        library = VideoLibrary.query.get_or_404(library_id)
        lib_dict = library.to_dict(include_stats=True)
        return jsonify({'success': True, 'data': lib_dict})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/libraries/<int:library_id>', methods=['PUT'])
@admin_required
def update_library(library_id):
    """更新视频库配置"""
    try:
        library = VideoLibrary.query.get_or_404(library_id)
        data = request.get_json()

        if 'name' in data:
            # 检查名称重复
            existing = VideoLibrary.query.filter(VideoLibrary.name == data['name'], VideoLibrary.id != library_id).first()
            if existing:
                return jsonify({'success': False, 'message': '视频库名称已存在'}), 400
            library.name = data['name'].strip()

        if 'description' in data:
            library.description = data['description'].strip()

        if 'is_active' in data:
            library.is_active = bool(data['is_active'])

        if 'config' in data:
            library.config = data['config']

        db.session.commit()
        return jsonify({'success': True, 'data': library.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/libraries/<int:library_id>', methods=['DELETE'])
@admin_required
def delete_library(library_id):
    """删除视频库"""
    try:
        library = VideoLibrary.query.get_or_404(library_id)

        # 可选：删除数据库文件
        # db_file = library.full_db_path
        # if os.path.exists(db_file):
        #     os.remove(db_file)

        db.session.delete(library)
        db.session.commit()
        return jsonify({'success': True, 'message': '视频库已删除'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ 用户权限管理 API =================

@app.route('/api/admin/libraries/<int:library_id>/permissions', methods=['GET'])
@admin_required
def get_library_permissions(library_id):
    """获取视频库的权限列表"""
    try:
        library = VideoLibrary.query.get_or_404(library_id)
        permissions = LibraryPermission.query.filter_by(library_id=library_id).all()
        return jsonify({
            'success': True,
            'data': [p.to_dict() for p in permissions]
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/libraries/<int:library_id>/permissions', methods=['POST'])
@admin_required
def add_library_permission(library_id):
    """添加用户权限"""
    try:
        library = VideoLibrary.query.get_or_404(library_id)
        data = request.get_json()

        user_id = data.get('user_id')
        group_id = data.get('group_id')
        role = data.get('role', 'user')
        access_level = data.get('access_level', 'read')
        permissions = data.get('permissions', [])

        if not user_id and not group_id:
            return jsonify({'success': False, 'message': '请指定用户或用户组'}), 400

        # 检查权限是否已存在
        if user_id:
            existing = LibraryPermission.query.filter_by(library_id=library_id, user_id=user_id).first()
        else:
            existing = LibraryPermission.query.filter_by(library_id=library_id, group_id=group_id).first()

        if existing:
            return jsonify({'success': False, 'message': '权限已存在，请使用更新接口'}), 400

        # 创建权限
        permission = LibraryPermission(
            library_id=library_id,
            user_id=user_id,
            group_id=group_id,
            role=role,
            access_level=access_level,
            permissions=permissions,
            created_by=g.user.id if hasattr(g, 'user') else None
        )

        db.session.add(permission)

        # 记录审计日志
        audit_log = LibraryAuditLog(
            library_id=library_id,
            target_user_id=user_id,
            action='create',
            new_value={'role': role, 'access_level': access_level},
            operator_id=g.user.id if hasattr(g, 'user') else None
        )
        db.session.add(audit_log)

        db.session.commit()
        return jsonify({'success': True, 'data': permission.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/libraries/<int:library_id>/permissions/<int:perm_id>', methods=['PUT'])
@admin_required
def update_library_permission(library_id, perm_id):
    """更新用户权限"""
    try:
        permission = LibraryPermission.query.filter_by(id=perm_id, library_id=library_id).first_or_404()
        data = request.get_json()

        old_value = {
            'role': permission.role,
            'access_level': permission.access_level,
            'permissions': permission.permissions
        }

        if 'role' in data:
            permission.role = data['role']
        if 'access_level' in data:
            permission.access_level = data['access_level']
        if 'permissions' in data:
            permission.permissions = data['permissions']

        # 记录审计日志
        audit_log = LibraryAuditLog(
            library_id=library_id,
            target_user_id=permission.user_id,
            action='update',
            old_value=old_value,
            new_value={'role': permission.role, 'access_level': permission.access_level},
            operator_id=g.user.id if hasattr(g, 'user') else None
        )
        db.session.add(audit_log)

        db.session.commit()
        return jsonify({'success': True, 'data': permission.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/libraries/<int:library_id>/permissions/<int:perm_id>', methods=['DELETE'])
@admin_required
def delete_library_permission(library_id, perm_id):
    """删除用户权限"""
    try:
        permission = LibraryPermission.query.filter_by(id=perm_id, library_id=library_id).first_or_404()

        # 记录审计日志
        audit_log = LibraryAuditLog(
            library_id=library_id,
            target_user_id=permission.user_id,
            action='delete',
            old_value={'role': permission.role, 'access_level': permission.access_level},
            operator_id=g.user.id if hasattr(g, 'user') else None
        )
        db.session.add(audit_log)

        db.session.delete(permission)
        db.session.commit()
        return jsonify({'success': True, 'message': '权限已删除'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ 批量导入视频 API =================

@app.route('/api/admin/scan-folder', methods=['POST'])
@admin_required
def scan_folder():
    """扫描指定文件夹，预览视频文件
    
    请求参数:
    - folder_path: 要扫描的文件夹路径
    - recursive: 是否递归扫描子文件夹（默认true）
    - supported_formats: 支持的视频格式（可选，默认使用配置文件中的格式）
    
    返回:
    - videos: 发现的视频文件列表
    - total: 总数
    """
    try:
        data = request.get_json()
        folder_path = data.get('folder_path', '').strip()
        recursive = data.get('recursive', True)
        supported_formats = data.get('supported_formats', app_config.get('supported_formats', []))
        
        if not folder_path:
            return jsonify({'success': False, 'message': '请指定要扫描的文件夹路径'}), 400
        
        if not os.path.exists(folder_path):
            return jsonify({'success': False, 'message': '指定的文件夹不存在'}), 400
        
        if not os.path.isdir(folder_path):
            return jsonify({'success': False, 'message': '指定的路径不是文件夹'}), 400
        
        # 扫描视频文件
        videos = []
        if recursive:
            for root, _, files in os.walk(folder_path):
                for f in files:
                    if any(f.lower().endswith(ext) for ext in supported_formats):
                        video_path = os.path.join(root, f)
                        file_size = os.path.getsize(video_path)
                        video_hash = Video.generate_hash(video_path)
                        
                        # 检查是否已存在
                        existing = Video.query.filter_by(hash=video_hash).first()
                        
                        videos.append({
                            'path': video_path,
                            'filename': f,
                            'title': os.path.splitext(f)[0],
                            'size': file_size,
                            'size_mb': round(file_size / (1024 * 1024), 2),
                            'hash': video_hash,
                            'exists': existing is not None,
                            'existing_id': existing.id if existing else None
                        })
        else:
            for f in os.listdir(folder_path):
                file_path = os.path.join(folder_path, f)
                if os.path.isfile(file_path) and any(f.lower().endswith(ext) for ext in supported_formats):
                    file_size = os.path.getsize(file_path)
                    video_hash = Video.generate_hash(file_path)
                    
                    existing = Video.query.filter_by(hash=video_hash).first()
                    
                    videos.append({
                        'path': file_path,
                        'filename': f,
                        'title': os.path.splitext(f)[0],
                        'size': file_size,
                        'size_mb': round(file_size / (1024 * 1024), 2),
                        'hash': video_hash,
                        'exists': existing is not None,
                        'existing_id': existing.id if existing else None
                    })
        
        # 按文件名排序
        videos.sort(key=lambda x: x['filename'])
        
        return jsonify({
            'success': True,
            'data': {
                'videos': videos,
                'total': len(videos),
                'new_count': len([v for v in videos if not v['exists']]),
                'existing_count': len([v for v in videos if v['exists']])
            }
        })
        
    except Exception as e:
        log.debug('ERROR', f"扫描文件夹失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/import-videos', methods=['POST'])
@admin_required
def import_videos():
    """批量导入视频到指定视频库
    
    请求参数:
    - library_id: 目标视频库ID（可选，默认导入到主数据库）
    - videos: 视频列表，每个视频包含:
        - path: 视频文件路径
        - title: 标题（可选，默认使用文件名）
        - description: 描述（可选）
        - tags: 标签列表（可选）
    - skip_existing: 是否跳过已存在的视频（默认true）
    - default_tags: 默认标签（可选）
    
    返回:
    - imported: 成功导入的数量
    - skipped: 跳过的数量
    - failed: 失败的数量
    - errors: 错误信息列表
    """
    try:
        data = request.get_json()
        library_id = data.get('library_id')  # 必须指定有效的视频库ID
        videos = data.get('videos', [])
        skip_existing = data.get('skip_existing', True)
        default_tags = data.get('default_tags', app_config.get('default_tags', ['本地视频']))

        if not videos:
            return jsonify({'success': False, 'message': '请选择要导入的视频'}), 400

        # 验证视频库：必须指定有效的激活视频库
        if not library_id:
            return jsonify({'success': False, 'message': '请选择目标视频库'}), 400

        # 检查视频库是否存在且已激活
        library = VideoLibrary.query.get(library_id)
        if not library:
            return jsonify({'success': False, 'message': '视频库不存在'}), 400

        if not library.is_active:
            return jsonify({'success': False, 'message': '该视频库已被禁用，无法导入'}), 400
        
        imported = 0
        skipped = 0
        failed = 0
        errors = []
        
        for video_data in videos:
            try:
                video_path = video_data.get('path')
                if not video_path or not os.path.exists(video_path):
                    errors.append(f"文件不存在: {video_path}")
                    failed += 1
                    continue
                
                # 生成hash
                video_hash = Video.generate_hash(video_path)
                
                # 检查是否已存在
                existing = Video.query.filter_by(hash=video_hash).first()
                if existing:
                    if skip_existing:
                        skipped += 1
                        continue
                    else:
                        # 删除已存在的记录
                        db.session.delete(existing)
                        db.session.flush()
                
                # 获取视频信息
                title = video_data.get('title', os.path.splitext(os.path.basename(video_path))[0])
                description = video_data.get('description', f'本地视频: {os.path.basename(video_path)}')
                file_size = os.path.getsize(video_path)
                
                # 创建视频记录（必须指定 library_id）
                video = Video(
                    hash=video_hash,
                    title=title,
                    description=description,
                    url=f'/local_video/{quote(video_path.replace(chr(92), "/"), safe=":/")}',
                    thumbnail=f'/thumbnail/{video_hash}',
                    file_size=file_size,
                    is_downloaded=True,
                    local_path=video_path,
                    priority=app_config.get('default_priority', 0),
                    library_id=library_id  # 绑定到指定的视频库
                )
                db.session.add(video)
                db.session.flush()
                
                # 添加标签
                tags = video_data.get('tags', default_tags)
                for tag_name in tags:
                    tag = Tag.query.filter_by(name=tag_name).first()
                    if not tag:
                        tag = Tag(name=tag_name, category='类型')
                        db.session.add(tag)
                        db.session.flush()
                    db.session.add(VideoTag(video_id=video.id, tag_id=tag.id))
                
                imported += 1
                
            except Exception as e:
                errors.append(f"导入失败 {video_data.get('path', 'unknown')}: {str(e)}")
                failed += 1
                log.debug('ERROR', f"导入视频失败: {e}")
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'data': {
                'imported': imported,
                'skipped': skipped,
                'failed': failed,
                'errors': errors[:10]  # 只返回前10个错误
            },
            'message': f'成功导入 {imported} 个视频，跳过 {skipped} 个，失败 {failed} 个'
        })
        
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"批量导入视频失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/browse-folders', methods=['GET'])
@admin_required
def browse_folders():
    """浏览服务器文件夹结构
    
    查询参数:
    - path: 要浏览的路径（可选，默认为根目录或用户主目录）
    - show_files: 是否显示文件（默认false，只显示文件夹）
    
    返回:
    - current_path: 当前路径
    - parent_path: 父目录路径
    - folders: 文件夹列表
    - drives: 驱动器列表（Windows）或根目录（Unix）
    """
    try:
        path = request.args.get('path', '')
        show_files = request.args.get('show_files', 'false').lower() == 'true'
        
        # 如果没有指定路径，返回根目录或驱动器列表
        if not path:
            if os.name == 'nt':  # Windows
                # 获取所有驱动器
                import string
                drives = []
                for letter in string.ascii_uppercase:
                    drive = f"{letter}:\\"
                    if os.path.exists(drive):
                        try:
                            drives.append({
                                'name': drive,
                                'path': drive,
                                'type': 'drive',
                                'display': f"{letter}: 驱动器"
                            })
                        except:
                            pass
                return jsonify({
                    'success': True,
                    'data': {
                        'current_path': '',
                        'parent_path': None,
                        'folders': drives,
                        'is_root': True
                    }
                })
            else:  # Unix/Linux/macOS
                path = '/'
        
        # 规范化路径
        path = os.path.normpath(path)
        
        if not os.path.exists(path):
            return jsonify({'success': False, 'message': '路径不存在'}), 404
        
        if not os.path.isdir(path):
            return jsonify({'success': False, 'message': '不是有效的文件夹'}), 400
        
        # 获取文件夹列表
        folders = []
        files = []
        
        try:
            items = os.listdir(path)
        except PermissionError:
            return jsonify({'success': False, 'message': '没有权限访问此文件夹'}), 403
        except Exception as e:
            return jsonify({'success': False, 'message': f'读取文件夹失败: {str(e)}'}), 500
        
        for item in items:
            item_path = os.path.join(path, item)
            try:
                is_dir = os.path.isdir(item_path)
                if is_dir:
                    # 跳过隐藏文件夹和系统文件夹
                    if not item.startswith('.') and item not in ['$RECYCLE.BIN', 'System Volume Information']:
                        folders.append({
                            'name': item,
                            'path': item_path,
                            'type': 'folder'
                        })
                elif show_files:
                    # 获取文件信息
                    stat = os.stat(item_path)
                    files.append({
                        'name': item,
                        'path': item_path,
                        'type': 'file',
                        'size': stat.st_size,
                        'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })
            except (PermissionError, OSError):
                # 跳过无法访问的文件/文件夹
                continue
        
        # 排序：文件夹按名称排序
        folders.sort(key=lambda x: x['name'].lower())
        files.sort(key=lambda x: x['name'].lower())
        
        # 合并结果
        result = folders + files
        
        # 获取父目录
        parent_path = os.path.dirname(path) if path not in ['/', '\\'] else None
        
        return jsonify({
            'success': True,
            'data': {
                'current_path': path,
                'parent_path': parent_path,
                'folders': result,
                'is_root': False
            }
        })
        
    except Exception as e:
        log.debug('ERROR', f"浏览文件夹失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ 用户可访问视频库 API =================

@app.route('/api/user/libraries', methods=['GET'])
def get_user_libraries():
    """获取当前用户可访问的视频库列表"""
    try:
        user_id = None
        user_role = 0
        
        # 方式1: 从 JWT Token 获取用户信息（前端使用）
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            try:
                from authlib.jose import jwt as _jwt
                _secret = 'dplayer-jwt-secret-key-change-in-production-2024'
                _payload = _jwt.decode(auth_header[7:], _secret)
                user_id = _payload.get('user_id')
                user_role = _payload.get('role', 0)
            except Exception:
                pass
        
        # 方式2: 从 g.user 获取（如果存在）
        if not user_id and hasattr(g, 'user') and g.user:
            user_id = g.user.id
            user_role = g.user.role
        
        # 方式3: 从 session 获取（传统方式）
        if not user_id and 'user_id' in session:
            user_id = session['user_id']
            user_role = session.get('role', 0)

        # 获取所有激活的视频库
        libraries = VideoLibrary.query.filter_by(is_active=True).all()

        if not user_id:
            # 未登录用户，只能看到公开的（暂时返回空）
            return jsonify({'success': True, 'data': [], 'current_library': None})

        # 获取用户权限
        result = []
        for lib in libraries:
            # 检查用户是否有权限
            user_perm = LibraryPermission.query.filter_by(library_id=lib.id, user_id=user_id).first()

            # 检查用户所属用户组的权限
            group_perms = []
            user_groups = LibraryUserGroupMember.query.filter_by(user_id=user_id).all()
            for ugm in user_groups:
                gp = LibraryPermission.query.filter_by(library_id=lib.id, group_id=ugm.group_id).first()
                if gp:
                    group_perms.append(gp)

            # 合并权限（用户权限 > 用户组权限）
            perm = user_perm or (group_perms[0] if group_perms else None)

            # 管理员和 ROOT 可以访问所有视频库
            if perm or user_role in [UserRole.ADMIN, UserRole.ROOT]:
                lib_dict = lib.to_dict()
                lib_dict['access_level'] = perm.access_level if perm else 'full'
                lib_dict['role'] = perm.role if perm else 'admin'

                # 解析详细权限
                if perm and perm.permissions:
                    lib_dict['permissions'] = perm.permissions
                else:
                    # 根据 access_level 设置默认权限
                    if lib_dict['access_level'] == 'full':
                        lib_dict['permissions'] = ['browse', 'play', 'download', 'upload', 'edit', 'delete']
                    elif lib_dict['access_level'] == 'write':
                        lib_dict['permissions'] = ['browse', 'play', 'download', 'upload', 'edit']
                    elif lib_dict['access_level'] == 'read':
                        lib_dict['permissions'] = ['browse', 'play']
                    else:
                        lib_dict['permissions'] = []

                result.append(lib_dict)

        # 获取当前选中的视频库
        current_library_id = session.get('current_library_id')
        if not current_library_id and result:
            current_library_id = result[0]['id']

        return jsonify({
            'success': True,
            'data': result,
            'current_library': current_library_id
        })
    except Exception as e:
        log.debug('ERROR', f"获取用户视频库失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/user/libraries/switch', methods=['POST'])
def switch_user_library():
    """切换当前视频库"""
    try:
        data = request.get_json()
        library_id = data.get('library_id')

        if not library_id:
            return jsonify({'success': False, 'message': '请指定视频库'}), 400

        # 验证用户身份：优先 JWT token，其次 session
        user_id = None
        user_role = 0
        # 尝试 JWT token
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            try:
                from authlib.jose import jwt as _jwt
                _secret = 'dplayer-jwt-secret-key-change-in-production-2024'
                payload = _jwt.decode(auth_header[7:], _secret)
                user_id = payload.get('user_id')
                user_role = payload.get('role', 0)
            except Exception:
                pass
        # 无 token 时使用 session
        if not user_id:
            user_id = session.get('user_id')
            user_role = session.get('role', 0)

        if not user_id:
            return jsonify({'success': False, 'message': '请先登录'}), 401

        library = VideoLibrary.query.get_or_404(library_id)

        # 检查视频库是否被禁用
        if not library.is_active:
            return jsonify({'success': False, 'message': '该视频库已被禁用'}), 403

        # 管理员/ROOT 可以访问所有库；普通用户检查权限
        if user_role not in [UserRole.ADMIN, UserRole.ROOT]:
            user_perm = LibraryPermission.query.filter_by(library_id=library_id, user_id=user_id).first()
            group_perms = LibraryUserGroupMember.query.filter_by(user_id=user_id).all()
            has_access = bool(user_perm or any(
                LibraryPermission.query.filter_by(library_id=library_id, group_id=ugm.group_id).first()
                for ugm in group_perms
            ))
            if not has_access:
                return jsonify({'success': False, 'message': '无权访问该视频库'}), 403

        session['current_library_id'] = library_id
        return jsonify({
            'success': True,
            'message': f'已切换到视频库: {library.name}',
            'current_library': library_id
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ 用户组管理 API =================

@app.route('/api/admin/user-groups', methods=['GET'])
@admin_required
def get_user_groups():
    """获取所有用户组"""
    try:
        groups = LibraryUserGroup.query.all()
        return jsonify({
            'success': True,
            'data': [g.to_dict(include_members=True) for g in groups]
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/user-groups', methods=['POST'])
@admin_required
def create_user_group():
    """创建用户组"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()

        if not name:
            return jsonify({'success': False, 'message': '请输入用户组名称'}), 400

        if LibraryUserGroup.query.filter_by(name=name).first():
            return jsonify({'success': False, 'message': '用户组名称已存在'}), 400

        group = LibraryUserGroup(name=name, description=description)
        db.session.add(group)
        db.session.commit()

        return jsonify({'success': True, 'data': group.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/user-groups/<int:group_id>', methods=['DELETE'])
@admin_required
def delete_user_group(group_id):
    """删除用户组"""
    try:
        group = LibraryUserGroup.query.get_or_404(group_id)
        db.session.delete(group)
        db.session.commit()
        return jsonify({'success': True, 'message': '用户组已删除'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/user-groups/<int:group_id>/members', methods=['POST'])
@admin_required
def add_user_to_group(group_id):
    """添加用户到用户组"""
    try:
        group = LibraryUserGroup.query.get_or_404(group_id)
        data = request.get_json()
        user_id = data.get('user_id')

        if not user_id:
            return jsonify({'success': False, 'message': '请指定用户'}), 400

        # 检查用户是否存在
        user = User.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

        # 检查是否已是成员
        existing = LibraryUserGroupMember.query.filter_by(group_id=group_id, user_id=user_id).first()
        if existing:
            return jsonify({'success': False, 'message': '用户已是成员'}), 400

        member = LibraryUserGroupMember(group_id=group_id, user_id=user_id)
        db.session.add(member)
        db.session.commit()

        return jsonify({'success': True, 'data': group.to_dict(include_members=True)})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/user-groups/<int:group_id>/members/<int:user_id>', methods=['DELETE'])
@admin_required
def remove_user_from_group(group_id, user_id):
    """从用户组移除用户"""
    try:
        member = LibraryUserGroupMember.query.filter_by(group_id=group_id, user_id=user_id).first_or_404()
        db.session.delete(member)
        db.session.commit()
        return jsonify({'success': True, 'message': '用户已从用户组移除'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ 审计日志 API =================

@app.route('/api/admin/libraries/<int:library_id>/audit-logs', methods=['GET'])
@admin_required
def get_library_audit_logs(library_id):
    """获取视频库权限变更日志"""
    try:
        logs = LibraryAuditLog.query.filter_by(library_id=library_id).order_by(
            LibraryAuditLog.created_at.desc()
        ).limit(100).all()
        return jsonify({
            'success': True,
            'data': [log.to_dict() for log in logs]
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ 系统日志查询 API =================

@app.route('/api/admin/logs', methods=['GET'])
@admin_required
def get_system_logs():
    """
    获取系统日志（从 liblog 日志文件读取）
    
    参数:
    - type: 日志类型 (maintenance/runtime/debug/operation)，默认 maintenance
    - page: 页码，默认 1
    - limit: 每页条数，默认 20
    """
    log_type = request.args.get('type', 'maintenance').strip().lower()
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 20, type=int)
    
    # 验证日志类型
    valid_types = ['maintenance', 'runtime', 'debug', 'operation']
    if log_type not in valid_types:
        return jsonify({'success': False, 'message': f'无效的日志类型，可选: {", ".join(valid_types)}'}), 400
    
    # 限制每页条数范围
    limit = max(1, min(limit, 200))
    page = max(1, page)
    
    # 日志文件路径
    log_dir = os.path.join(_DATA_DIR, 'logs')
    log_file = os.path.join(log_dir, f'{log_type}.log')
    
    if not os.path.exists(log_file):
        return jsonify({
            'success': True,
            'logs': [],
            'total': 0,
            'page': page,
            'limit': limit,
            'total_pages': 0,
            'type': log_type
        })
    
    # 读取并解析日志文件
    try:
        # 尝试 UTF-8 读取，失败则尝试 GBK
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            with open(log_file, 'r', encoding='gbk', errors='replace') as f:
                lines = f.readlines()
        
        # 解析日志行
        parsed_logs = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            parsed = parse_log_line(line, log_type)
            if parsed:
                parsed_logs.append(parsed)
        
        # 倒序排列（最新在前）
        parsed_logs.reverse()
        
        # 计算分页
        total = len(parsed_logs)
        total_pages = (total + limit - 1) // limit if total > 0 else 0
        start = (page - 1) * limit
        end = start + limit
        page_logs = parsed_logs[start:end]
        
        return jsonify({
            'success': True,
            'logs': page_logs,
            'total': total,
            'page': page,
            'limit': limit,
            'total_pages': total_pages,
            'type': log_type
        })
    
    except Exception as e:
        log.debug('ERROR', f'读取日志文件失败: {e}')
        return jsonify({'success': False, 'message': f'读取日志失败: {str(e)}'}), 500


def parse_log_line(line: str, log_type: str) -> dict | None:
    """
    解析单行日志
    
    格式:
    - maintenance/runtime/debug: [时间] | [等级] | [模块] | [内容]
    - operation: [时间] | [IP] | [模块] | [内容]
    """
    import re
    
    # 匹配格式: [xxx] | [xxx] | [xxx] | [xxx]
    match = re.match(r'^\[([^\]]+)\]\s*\|\s*\[([^\]]+)\]\s*\|\s*\[([^\]]+)\]\s*\|\s*\[(.+)\]$', line)
    if not match:
        return None
    
    timestamp = match.group(1).strip()
    field2 = match.group(2).strip()  # 等级（或 IP）
    module = match.group(3).strip()
    content = match.group(4).strip()
    
    return {
        'timestamp': timestamp,
        'level': field2 if log_type != 'operation' else '',
        'source': field2 if log_type == 'operation' else '',
        'module': module,
        'content': content,
        'type': log_type
    }


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


@app.route('/api/admin/thumbnail/config', methods=['GET'])
@admin_required
def get_thumbnail_config():
    """获取缩略图管理配置"""
    try:
        config = _load_thumb_config()

        # 获取缩略图统计信息
        thumb_dir = os.path.join(_DATA_DIR, 'thumbnails')
        total_thumbnails = 0
        if os.path.exists(thumb_dir):
            total_thumbnails = len([f for f in os.listdir(thumb_dir)
                                     if f.lower().endswith(('.gif', '.jpg', '.png'))])

        # 获取无缩略图的视频数量
        from core.models import Video
        db_videos = Video.query.all()
        no_thumb_count = 0
        for v in db_videos:
            if v.hash:
                has_thumb = any(
                    os.path.exists(os.path.join(thumb_dir, f'{v.hash}.{ext}'))
                    for ext in ['gif', 'jpg', 'png']
                )
                if not has_thumb:
                    no_thumb_count += 1

        # 获取缩略图服务状态
        thumb_service_status = 'unknown'
        thumb_service_stats = None
        if thumbnail_bus:
            try:
                thumb_service_stats = thumbnail_bus.call_method(
                    service='com.dplayer.thumbnaild',
                    interface='com.dplayer.Thumbnaild',
                    method='GetMetrics',
                    params={}
                )
                if thumb_service_stats:
                    thumb_service_status = 'running'
                else:
                    thumb_service_status = 'error'
            except Exception:
                thumb_service_status = 'offline'

        # 获取自动生成线程状态
        is_auto_running = _thumb_auto_thread is not None and _thumb_auto_thread.is_alive()

        return jsonify({
            'success': True,
            'config': config,
            'stats': {
                'total_videos': len(db_videos),
                'total_thumbnails': total_thumbnails,
                'no_thumbnail_count': no_thumb_count,
                'thumb_service_status': thumb_service_status,
                'thumb_service_stats': thumb_service_stats,
                'is_auto_generating': is_auto_running
            }
        })
    except Exception as e:
        log.debug('ERROR', f'获取缩略图配置失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/thumbnail/config', methods=['POST'])
@admin_required
def update_thumbnail_config():
    """更新缩略图管理配置"""
    try:
        data = request.get_json()
        config = _load_thumb_config()

        # 只允许更新指定字段
        allowed_fields = ['auto_generate', 'max_workers', 'task_interval', 'auto_generate_interval']
        for field in allowed_fields:
            if field in data:
                # 参数校验
                if field == 'max_workers':
                    config[field] = max(1, min(int(data[field]), 8))
                elif field == 'task_interval':
                    config[field] = max(1, min(int(data[field]), 60))
                elif field == 'auto_generate_interval':
                    config[field] = max(300, min(int(data[field]), 86400))  # 5分钟 ~ 24小时
                elif field == 'auto_generate':
                    config[field] = bool(data[field])

        if _save_thumb_config(config):
            log.maintenance('INFO', f'缩略图配置已更新: {config}')

            # 如果开启了自动生成，启动后台线程
            if config['auto_generate'] and (_thumb_auto_thread is None or not _thumb_auto_thread.is_alive()):
                _start_auto_generate(config)
            # 如果关闭了自动生成，停止后台线程
            elif not config['auto_generate'] and _thumb_auto_thread is not None:
                _thumb_auto_stop_event.set()

            return jsonify({'success': True, 'message': '配置已保存', 'config': config})
        else:
            return jsonify({'success': False, 'message': '保存配置失败'}), 500
    except Exception as e:
        log.debug('ERROR', f'更新缩略图配置失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500


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


@app.route('/api/admin/thumbnail/generate-missing', methods=['POST'])
@admin_required
def generate_missing_thumbnails():
    """手动触发一次批量生成缺失缩略图（不开启自动模式）"""
    try:
        config = _load_thumb_config()
        result = _generate_missing_thumbnails(config)
        return jsonify({
            'success': True,
            'message': f'已提交生成任务',
            'submitted': result.get('submitted', 0) if result else 0
        })
    except Exception as e:
        log.debug('ERROR', f'批量生成缩略图失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/thumbnail/auto-generate/status', methods=['GET'])
@admin_required
def get_auto_generate_status():
    """获取自动生成线程状态"""
    is_running = _thumb_auto_thread is not None and _thumb_auto_thread.is_alive()
    return jsonify({
        'success': True,
        'is_running': is_running
    })


@app.route('/api/admin/thumbnail/auto-generate/stop', methods=['POST'])
@admin_required
def stop_auto_generate():
    """停止自动生成线程"""
    global _thumb_auto_thread

    if _thumb_auto_thread is not None and _thumb_auto_thread.is_alive():
        _thumb_auto_stop_event.set()
        # 更新配置文件
        config = _load_thumb_config()
        config['auto_generate'] = False
        _save_thumb_config(config)
        log.maintenance('INFO', '缩略图自动生成已手动停止')
        return jsonify({'success': True, 'message': '自动生成已停止'})
    else:
        return jsonify({'success': True, 'message': '自动生成已停止'})


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
    扫描 dplayer- 前缀的 Windows 服务（通过 win32service API）
    """
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
        log.debug('DEBUG', f'[服务管理] 扫描服务异常: {type(e).__name__}: {e}')
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
                info['cpu_percent'] = proc.cpu_percent(interval=0.5)
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
        resp = requests.get(health_url, timeout=3)
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
        result['detail'] = '超时（>3s）'
    except requests.exceptions.ConnectionError:
        result['status'] = 'unhealthy'
        result['detail'] = '连接失败'
    except Exception as e:
        result['status'] = 'unknown'
        result['detail'] = str(e)[:100]

    return result


@app.route('/api/admin/services', methods=['GET'])
@admin_required
def get_services():
    """获取所有 dplayer 服务的状态（通过 servicemgrd 总线查询）"""
    import time
    total_start = time.time()
    try:
        # 优先通过总线查询（异步获取，不阻塞）
        if svc_mgr_bus:
            bus_start = time.time()
            try:
                result = svc_mgr_bus.call_method(
                    'com.dplayer.servicemgr',
                    'com.dplayer.ServiceMgr',
                    'ListServices',
                    {},
                    timeout=3000  # 3秒超时
                )
                bus_elapsed = (time.time() - bus_start) * 1000
                log.debug('INFO', f'总线调用耗时: {bus_elapsed:.0f}ms, result={result is not None}')
                if result and 'services' in result:
                    # 转换总线返回的字段名以匹配前端期望
                    services = []
                    for svc in result['services']:
                        services.append({
                            'service_name': svc.get('name', ''),
                            'display_name': svc.get('display_name', svc.get('name', '')),
                            'description': svc.get('description', ''),
                            'port': svc.get('port'),
                            'system_status': svc.get('status', 'unknown'),
                            'pid': svc.get('pid'),
                            'memory_mb': svc.get('memory_mb'),
                            'cpu_percent': svc.get('cpu_percent'),
                            'health_status': svc.get('health_status', 'unknown'),
                            'health_latency_ms': svc.get('latency_ms'),
                            'health_detail': svc.get('description', ''),
                        })
                    return jsonify({
                        'success': True,
                        'services': services,
                        'source': 'bus',
                        'bus_time_ms': bus_elapsed,
                    })
            except Exception as e:
                bus_elapsed = (time.time() - bus_start) * 1000
                log.debug('WARN', f'总线查询失败 ({bus_elapsed:.0f}ms): {e}')

        # 降级：直接扫描（如果 servicemgrd 不可用）
        nssm_services = _scan_services()
        services = []

        for svc_name in nssm_services:
            sys_status = _get_service_status(svc_name)
            svc_health = _check_service_health(svc_name) if sys_status['status'] in ('RUNNING', 'PAUSED') else {
                'status': 'unknown', 'latency_ms': None, 'detail': '服务未运行'
            }

            meta = _SERVICE_META.get(svc_name, {})
            services.append({
                'service_name': svc_name,
                'display_name': meta.get('display_name', svc_name),
                'description': meta.get('description', ''),
                'port': meta.get('port'),
                'system_status': sys_status['status'],
                'pid': sys_status['pid'],
                'memory_mb': sys_status['memory_mb'],
                'cpu_percent': sys_status['cpu_percent'],
                'health_status': svc_health['status'],
                'health_latency_ms': svc_health['latency_ms'],
                'health_detail': svc_health['detail'],
            })

        return jsonify({
            'success': True,
            'services': services,
            'source': 'direct',
        })
    except Exception as e:
        log.debug('ERROR', f'获取服务列表失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/admin/services/<service_name>/control', methods=['POST'])
@admin_required
def control_service(service_name):
    """控制服务：start / stop / restart（通过 servicemgrd 总线）"""
    try:
        data = request.get_json()
        action = data.get('action', '').lower()

        if action not in ('start', 'stop', 'restart'):
            return jsonify({'success': False, 'message': f'无效操作: {action}'}), 400

        # 安全检查：只允许操作 dplayer- 前缀的服务
        if not service_name.startswith('dplayer-'):
            return jsonify({'success': False, 'message': '只允许操作 dplayer- 前缀的服务'}), 403

        # 防并发锁
        if service_name not in _svc_control_locks:
            _svc_control_locks[service_name] = threading.Lock()

        if not _svc_control_locks[service_name].acquire(blocking=False):
            return jsonify({'success': False, 'message': '该服务正在操作中，请稍后再试'}), 409

        try:
            display_name = _SERVICE_META.get(service_name, {}).get('display_name', service_name)
            action_text = {'start': '启动', 'stop': '停止', 'restart': '重启'}

            # 优先通过总线调用 servicemgrd
            if svc_mgr_bus:
                try:
                    method_name = f'{action.capitalize()}Service'
                    result = svc_mgr_bus.call_method(
                        'com.dplayer.servicemgr',
                        'com.dplayer.ServiceMgr',
                        method_name,
                        {'name': service_name}
                    )
                    if result:
                        log.maintenance('INFO', f'服务 {service_name} {action} via bus: {result}')
                        return jsonify({
                            'success': result.get('success', False),
                            'message': result.get('message', ''),
                            'action': action,
                        })
                except Exception as bus_err:
                    log.debug('WARN', f'总线控制服务失败，降级到直接调用: {bus_err}')

            # 降级：直接调用 win32service
            import win32service

            scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
            svc = win32service.OpenService(scm, service_name, win32service.SERVICE_ALL_ACCESS)

            try:
                if action == 'start':
                    win32service.StartService(svc, None)
                elif action == 'stop':
                    win32service.ControlService(svc, win32service.SERVICE_CONTROL_STOP)
                elif action == 'restart':
                    status = win32service.QueryServiceStatus(svc)
                    if status[1] == win32service.SERVICE_RUNNING:
                        win32service.ControlService(svc, win32service.SERVICE_CONTROL_STOP)
                        for _ in range(30):
                            time.sleep(1)
                            status = win32service.QueryServiceStatus(svc)
                            if status[1] == win32service.SERVICE_STOPPED:
                                break
                            elif status[1] == win32service.SERVICE_STOP_PENDING:
                                continue
                            else:
                                break
                        else:
                            raise RuntimeError('停止服务超时（30秒）')
                    win32service.StartService(svc, None)
            finally:
                win32service.CloseServiceHandle(svc)
                win32service.CloseServiceHandle(scm)

            log.maintenance('INFO', f'服务 {service_name} {action} 成功（直接调用）')
            return jsonify({
                'success': True,
                'message': f'{display_name} {action_text[action]}成功',
                'action': action,
            })
        except Exception as e:
            error_msg = str(e)
            log.debug('ERROR', f'服务 {service_name} {action} 失败: {error_msg}')
            return jsonify({'success': False, 'message': error_msg}), 500
        finally:
            _svc_control_locks[service_name].release()

    except Exception as e:
        log.debug('ERROR', f'控制服务失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ 主入口 ============
if __name__ == '__main__':
    # 检查是否为开发模式
    is_dev_mode = os.environ.get('DPLAYER_DEV_MODE') == '1'
    
    port = app_config.get('ports', {}).get('web', 8080)
    
    if is_dev_mode:
        print(f"[DEV MODE] Starting DPlayer Web service on port {port} with hot reload")
        print(f"[DEV MODE] Access at: http://localhost:{port}")
        log.runtime('INFO', f'DPlayer Web 服务（开发模式）启动于端口 {port}')
        # 开发模式：启用 debug 和 use_reloader
        app.run(host='0.0.0.0', port=port, debug=True, use_reloader=True, threaded=True)
    else:
        print(f"[PRODUCTION] Starting DPlayer Web service on port {port}")
        log.runtime('INFO', f'DPlayer Web 服务启动于端口 {port}')
        # 生产模式：不启用 debug
        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
