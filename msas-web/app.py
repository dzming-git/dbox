import os
import sys

# 检测是否在命令行直接运行（非nssm服务模式）
def check_direct_command_line_execution():
    """
    检测是否在命令行直接运行Python文件，如果是则打印提示并退出。
    这个应用应该通过nssm服务启动，而不是直接在命令行运行。
    """
    # 检查是否在交互式终端中运行
    if sys.stdin.isatty() and sys.stdout.isatty():
        # 检查是否作为Windows服务运行（nssm会设置特定的环境变量）
        is_service = 'windows_service' in os.environ.get('RUN_MODE', '').lower()
        
        # 检查是否在Flask reloader模式下运行
        is_reloader = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
        
        # 如果不是服务模式也不是reloader，说明是直接命令行运行
        if not is_service and not is_reloader:
            print("\n" + "="*60)
            print("⚠️  警告：请勿在命令行直接运行此应用")
            print("="*60)
            print("")
            print("此应用应通过Windows服务(nssm)启动，否则会卡住命令行。")
            print("")
            print("如需继续运行，请按 Ctrl+C 终止，然后：")
            print("1. 设置环境变量: set RUN_MODE=windows_service")
            print("2. 再运行: python app.py")
            print("")
            print("="*60)
            print("")
            sys.exit(1)

# 注入共享模块路径（兼容直接运行和 nssm 服务两种方式）
_THIS_DIR       = os.path.dirname(os.path.abspath(__file__))             # msas-web/src
_DPLAYER_SOURCE = os.path.normpath(os.path.join(_THIS_DIR, '..', '..')) # dplayer-source
for _p in [
    _THIS_DIR,
    os.path.join(_DPLAYER_SOURCE, 'msas-thumb', 'src'),  # thumbnail_service_client
    os.path.join(_DPLAYER_SOURCE, 'libs'),                # libweb
]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file, abort, g
from werkzeug.utils import secure_filename
from core.models import db, Video, Tag, VideoTag, UserInteraction, UserPreference, User, UserSession, UserRole, ROLE_NAMES
from thumbnail_service_client import get_thumbnail_client, reset_thumbnail_client
from auth_service import AuthService, init_root_user
from api.auth_api import auth_bp

# ========== Vue3前端分离 - 认证API ==========
from backend.api.auth_api_v2 import auth_v2_bp
# from backend.middleware.cors import setup_cors  # 暂时注释掉
from backend.middleware.error_handler import setup_error_handlers

# LibWeb集成
from libweb import NodeManager, FlaskAdapter
from libweb.nodes import register_all_routes
from datetime import datetime, timedelta
import random
import asyncio
import os
import sys
import hashlib
import json
import glob
import sqlite3
from urllib.parse import quote
import threading
import time
import logging
from logging.handlers import RotatingFileHandler
import traceback
import psutil
import socket
from utils.network_optimize import optimize_flask_app
from utils.system_optimizer import optimize_system

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here-change-in-production'
# 使用绝对路径确保数据库文件位置正确
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'instance', 'dplayer.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB 最大上传
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)  # 会话有效期7天

# ========== Vue3前后端分离 - JWT配置 ==========
app.config['JWT_SECRET_KEY'] = 'your-jwt-secret-key-change-in-production'
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)  # Access Token 24小时
app.config['JWT_REFRESH_TOKEN_EXPIRES'] = timedelta(days=7)   # Refresh Token 7天

# ========== Cookie/Session 配置（解决局域网 HTTP 环境下无痕模式/多浏览器访问失败） ==========
# 局域网 HTTP 场景下必须设置 SameSite=Lax（不能用 None，None 要求 Secure/HTTPS）
# Lax 允许同站导航携带 Cookie，且对 HTTP 无痕模式最友好
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False       # HTTP 环境必须 False，否则 Cookie 不会被发送
app.config['SESSION_COOKIE_HTTPONLY'] = True       # 防 XSS
app.config['SESSION_COOKIE_NAME'] = 'dplayer_session'  # 自定义名称，避免与其他应用冲突

# 注册认证蓝图
app.register_blueprint(auth_bp)

# ========== Vue3前后端分离 - 初始化中间件 ==========
# 初始化CORS中间件
from backend.middleware.cors import setup_cors
setup_cors(app)

# 初始化全局路由鉴权中间件（JWT before_request 拦截）
from backend.middleware.auth_middleware import setup_auth_middleware
setup_auth_middleware(app)

# 初始化错误处理中间件
setup_error_handlers(app)

# ========== NodeManager集成 ==========
# 创建NodeManager实例并注册所有API路由
print("[*] 初始化NodeManager...")
node_manager = NodeManager()
register_all_routes(node_manager)

# 创建Flask适配器
flask_adapter = FlaskAdapter(node_manager)

# 将NodeManager路由注册到Flask应用
# 使用catch-all路由处理所有API请求
@app.route('/api/<path:fallback>')
@app.route('/api/health')
@app.route('/api/status')
@app.route('/api/dependencies/check')
def node_manager_handler(fallback=None):
    """NodeManager统一请求处理"""
    return asyncio.run(handle_node_request())

# ========== Vue3前后端分离 - 注册新认证API v2 ==========
# 注册auth_v2_bp蓝图（用于前后端分离的JWT认证）
# 注意：这个必须在通配符路由之后注册，以确保优先级更高
app.register_blueprint(auth_v2_bp, url_prefix='/api/v2/auth')

# ========== Vue3前后端分离 - 注册前端API ==========
from backend.api.frontend_api import frontend_bp
app.register_blueprint(frontend_bp)

# 简单的健康检查端点（不使用NodeManager，直接返回）
@app.route('/health', methods=['GET'])
def simple_health():
    """简单的健康检查端点"""
    try:
        return jsonify({
            'status': 'healthy'
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

async def handle_node_request():
    """异步处理NodeManager请求"""
    from flask import request, g
    from node_manager.core import ContextPool

    # 创建临时上下文池
    context_pool = ContextPool(max_concurrent=1)

    # 获取请求信息
    method = request.method
    path = request.path
    headers = dict(request.headers)
    body = request.get_json(silent=True) if request.is_json else None
    params = request.args.to_dict()

    # 获取上下文
    context = context_pool.acquire(method, path, headers, body, params)
    g.task_context = context

    try:
        # 查找Node
        node, route_params = node_manager.find_node(method, path)

        if node:
            if route_params:
                context.params.update(route_params)
            await node.handle(context)
        else:
            context.set_response(404, body={'error': 'Not Found'})

        # 转换响应
        from flask import jsonify, Response
        status = context.response_status or 200
        response_headers = context.response_headers or {}

        if context.response_body is not None:
            if isinstance(context.response_body, dict):
                response = jsonify(context.response_body)
            else:
                response = Response(str(context.response_body))
        else:
            response = Response('')

        response.status_code = status
        for key, value in response_headers.items():
            response.headers[key] = value

        return response

    finally:
        context_pool.release(context)

print(f"[*] NodeManager已初始化，注册了 {len(node_manager.get_registered_routes())} 个路由")

# 优化网络连接配置，解决局域网访问偶现失败问题
# try:
#     optimize_flask_app(app)
#     print('[*] 网络连接优化已启用')
# except Exception as e:
#     print(f'[警告] 网络优化失败: {e}')




# 配置文件路径（统一在项目根目录 config/ 下）
_PROJECT_ROOT = os.path.normpath(os.path.join(_THIS_DIR, '..', '..', '..'))  # Dplayer/
CONFIG_FILE = os.path.join(_PROJECT_ROOT, 'config', 'config.json')

# ========== 端口管理函数 ==========

def is_port_in_use(port):
    """检查指定端口是否被占用"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(('localhost', port))
            return result == 0
    except Exception as e:
        logger.error(f"Failed to check port {port} status: {e}")
        return False


def find_process_using_port(port, exclude_self=False):
    """查找占用指定端口的进程
    
    Args:
        port: 端口号
        exclude_self: 是否排除当前进程
    """
    processes = []
    current_pid = os.getpid() if exclude_self else None
    try:
        for conn in psutil.net_connections():
            if conn.laddr.port == port and conn.status == 'LISTEN':
                # 如果需要排除当前进程，则跳过
                if exclude_self and conn.pid == current_pid:
                    continue
                try:
                    proc = psutil.Process(conn.pid)
                    processes.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    logger.warning(f"Cannot access process {conn.pid}")
    except Exception as e:
        logger.error(f"Failed to find process using port {port}: {e}")
    return processes


def kill_process(process):
    """强制终止指定进程"""
    try:
        pid = process.pid
        name = process.name()
        process.terminate()  # 先尝试正常终止
        try:
            process.wait(timeout=5)
            logger.info(f"Successfully terminated process {name} (PID: {pid})")
            return True
        except psutil.TimeoutExpired:
            # Normal termination timeout, force kill
            process.kill()
            process.wait(timeout=2)
            logger.info(f"Force killed process {name} (PID: {pid})")
            return True
    except psutil.NoSuchProcess:
        logger.warning(f"Process does not exist")
        return True
    except psutil.AccessDenied:
        logger.error(f"No permission to terminate process (PID: {process.pid})")
        return False
    except Exception as e:
        logger.error(f"Failed to terminate process: {e}")
        return False


def kill_all_processes_using_port(port, exclude_self=False):
    """强制终止占用指定端口的所有进程
    
    Args:
        port: 端口号
        exclude_self: 是否排除当前进程（避免在debug模式下杀死自己）
    """
    result = {
        'success': True,
        'killed_count': 0,
        'processes': []
    }
    processes = find_process_using_port(port, exclude_self=exclude_self)
    if not processes:
        logger.info(f"Port {port} is not in use")
        return result
    logger.warning(f"Port {port} is occupied by {len(processes)} processes")
    for proc in processes:
        proc_info = {
            'pid': proc.pid,
            'name': proc.name(),
            'status': 'failed'
        }
        if kill_process(proc):
            result['killed_count'] += 1
            proc_info['status'] = 'killed'
        result['processes'].append(proc_info)
    # Verify if port is released
    if is_port_in_use(port):
        result['success'] = False
        logger.error(f"Port {port} is still in use, new process may have started")
    else:
        logger.info(f"Port {port} has been successfully released")
    return result


def ensure_port_available(port, exclude_self=False):
    """确保端口可用，如果被占用则强制释放
    
    Args:
        port: 端口号
        exclude_self: 是否排除当前进程（避免在debug模式下杀死自己）
    """
    if not is_port_in_use(port):
        logger.info(f"Port {port} is available")
        return {
            'success': True,
            'action': 'none',
            'message': f'Port {port} is available'
        }
    logger.warning(f"Port {port} is in use, forcefully releasing...")
    result = kill_all_processes_using_port(port, exclude_self=exclude_self)
    result['action'] = 'killed'
    result['message'] = f'Terminated {result["killed_count"]} processes to release port {port}'
    return result


# 读取配置
def load_config():
    """读取配置文件"""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            return {}
    except Exception as e:
        logger.error(f"Failed to read config file: {e}")
        return {}

# 全局配置
config = load_config()
PORT = config.get('ports', {}).get('main_app', 8081)  # 改为8081避免需要管理员权限
HOST = config.get('host', '0.0.0.0')

# 全局进度字典
progress_store = {}

# 缩略图生成锁（防止并发生成同一个缩略图）
thumbnail_locks = {}
thumbnail_locks_lock = threading.Lock()

# ========== 日志配置 ==========

# 自定义日志级别
CRITICAL_LEVEL = 60  # 致命
ERROR_LEVEL = 50     # 错误
INFO_LEVEL = 20      # 信息
NOTICE_LEVEL = 30    # 通知（介于INFO和WARNING之间）
DEBUG_LEVEL = 10     # 调试

# 为Python logging模块添加自定义级别
logging.addLevelName(CRITICAL_LEVEL, 'CRITICAL')
logging.addLevelName(INFO_LEVEL, 'INFO')
logging.addLevelName(NOTICE_LEVEL, 'NOTICE')

# 定义日志类型和文件
LOG_DIR = 'logs'
LOG_TYPES = {
    'maintenance': '维护日志',
    'runtime': '运行日志',
    'operation': '操作日志',
    'debug': '调试日志'
}

LOG_FILES = {
    'maintenance': os.path.join(LOG_DIR, 'maintenance.log'),
    'runtime': os.path.join(LOG_DIR, 'runtime.log'),
    'operation': os.path.join(LOG_DIR, 'operation.log'),
    'debug': os.path.join(LOG_DIR, 'debug.log')
}

LOG_BACKUP_COUNT = 5  # 保留5个备份
LOG_MAX_SIZE = 10 * 1024 * 1024  # 每个日志文件最大10MB

# 确保日志目录存在
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# 定义自定义日志记录器类
class TypedLogger:
    """带类型的日志记录器"""
    def __init__(self, log_type, name):
        self.log_type = log_type
        self.logger = logging.getLogger(log_type)  # 使用log_type作为logger名称，确保与setup_logging()中的配置一致

    def _log(self, level, msg, *args, **kwargs):
        """内部日志方法"""
        self.logger.log(level, msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        """致命日志"""
        self._log(CRITICAL_LEVEL, msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        """错误日志"""
        self._log(ERROR_LEVEL, msg, *args, **kwargs)

    def notice(self, msg, *args, **kwargs):
        """通知日志"""
        self._log(NOTICE_LEVEL, msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        """信息日志"""
        self._log(INFO_LEVEL, msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        """警告日志"""
        self._log(logging.WARNING, msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        """调试日志"""
        self._log(DEBUG_LEVEL, msg, *args, **kwargs)

# 配置日志系统
def setup_logging():
    """配置日志系统"""
    # 创建日志格式
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s [%(filename)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 为每种日志类型创建独立的处理器
    loggers = {}

    for log_type, log_file in LOG_FILES.items():
        # 创建RotatingFileHandler（自动轮转）
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=LOG_MAX_SIZE,
            backupCount=LOG_BACKUP_COUNT,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)  # 接收所有级别的日志

        # 创建该类型的日志记录器
        type_logger = logging.getLogger(log_type)
        type_logger.setLevel(logging.DEBUG)
        type_logger.addHandler(file_handler)

        # 防止传播到根日志记录器
        type_logger.propagate = False

        # 创建控制台处理器（只在运行日志中使用）
        if log_type == 'runtime':
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            console_handler.setLevel(logging.DEBUG)
            type_logger.addHandler(console_handler)

        loggers[log_type] = type_logger

    # Flask专用日志记录器
    flask_logger = logging.getLogger('werkzeug')
    flask_logger.setLevel(logging.WARNING)  # 只记录WARNING及以上级别的请求

    return loggers

# 初始化日志系统
loggers = setup_logging()

# 创建各个类型的日志记录器实例
maint_log = TypedLogger('maintenance', 'app')      # 维护日志
runtime_log = TypedLogger('runtime', 'app')        # 运行日志
operation_log = TypedLogger('operation', 'app')    # 操作日志
debug_log = TypedLogger('debug', 'app')            # 调试日志

# 向后兼容：保留logger变量指向运行日志
logger = runtime_log

# ========== 日志轮转管理 ==========
def get_log_files():
    """获取所有日志文件列表，按类型分组"""
    if not os.path.exists(LOG_DIR):
        return {}

    log_groups = {}

    # 获取所有日志文件
    all_files = []
    for filename in os.listdir(LOG_DIR):
        filepath = os.path.join(LOG_DIR, filename)
        if os.path.isfile(filepath):
            stat = os.stat(filepath)
            all_files.append({
                'filename': filename,
                'filepath': filepath,
                'size': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
            })

    # 按日志类型分组
    for log_type, log_file in LOG_FILES.items():
        base_filename = os.path.basename(log_file)

        # 找到该类型的所有日志文件（包括备份）
        type_files = []
        for file_info in all_files:
            if file_info['filename'].startswith(base_filename):
                type_files.append(file_info)

        # 按修改时间倒序排序
        type_files.sort(key=lambda x: x['modified'], reverse=True)

        if type_files:
            log_groups[log_type] = {
                'type': log_type,
                'name': LOG_TYPES[log_type],
                'files': type_files,
                'count': len(type_files),
                'total_size': sum(f['size'] for f in type_files)
            }

    return log_groups

def get_log_lines(log_file, line_count=100, search=None, level=None):
    """
    读取日志文件的最后N行，支持搜索和过滤

    Args:
        log_file: 日志文件路径
        line_count: 读取的行数
        search: 搜索关键词
        level: 日志级别过滤（INFO, WARNING, ERROR等）
    """
    try:
        lines = []
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()

        # 从后往前读取，实现倒序显示（最新的日志在最上面）
        for line in reversed(all_lines):
            # 搜索过滤
            if search and search.lower() not in line.lower():
                continue

            # 级别过滤
            if level and f'[{level}]' not in line:
                continue

            lines.append(line.strip())
            if len(lines) >= line_count:
                break

        # 不再反转，直接返回倒序的结果
        return lines
    except Exception as e:
        logger.error(f"Failed to read log file: {e}")
        return []

def parse_log_line(line):
    """解析单行日志，提取结构化信息"""
    import re
    try:
        # 日志格式1 (Python logging): [2025-03-12 14:30:45] CRITICAL [app.py:123] message
        # 日志格式2 (自定义): [2025-03-12 14:30:45] | [LEVEL] | [module] | [content]
        # 操作日志格式: [2025-03-12 14:30:45] | [IP] | [module] | [content]
        if not line.startswith('['):
            return {'raw': line}

        # 提取时间戳
        end_time = line.find(']')
        if end_time == -1:
            return {'raw': line}
        timestamp = line[1:end_time]

        # 判断格式：查找下一个 [ 来区分格式1和格式2
        # 格式1: [时间戳] 级别 [文件:行号] 消息 -> 级别后面是 [
        # 格式2: [时间戳] | [级别] | [模块] | [内容] -> 时间戳后是 |
        remaining = line[end_time+1:].strip()
        if remaining.startswith('|'):
            # 格式2: 自定义格式 [时间戳] | [LEVEL] | [module] | [content]
            # 提取级别
            level_match = re.match(r'^\|\s*\[(\w+)\]', remaining)
            if not level_match:
                return {'raw': line}
            level = level_match.group(1)

            # 提取模块
            module_match = re.match(r'^\|\s*\[\w+\]\s*\|\s*\[(\w+)\]', remaining)
            if not module_match:
                return {'raw': line}
            module = module_match.group(1)

            # 提取消息（剩余内容）
            msg_start = remaining.find('|', remaining.find('|') + 1)
            message = remaining[msg_start+1:].strip() if msg_start != -1 else ''

            # 标准化级别名称
            level_map = {
                'CRITICAL': '致命',
                'ERROR': '错误',
                'NOTICE': '通知',
                'DEBUG': '调试',
                'INFO': '通知',
                'WARNING': '警告'
            }
            normalized_level = level_map.get(level, level)

            return {
                'timestamp': timestamp,
                'level': normalized_level,
                'level_code': level,
                'filename': module,
                'lineno': '0',
                'message': message,
                'raw': line
            }
        else:
            # 格式1: Python logging格式 [时间戳] LEVEL [file:line] message
            # 提取级别
            space_idx = remaining.find(' ')
            if space_idx == -1:
                return {'raw': line}
            level = remaining[:space_idx]

            # 提取文件位置
            start_file = remaining.find('[', space_idx)
            end_file = remaining.find(']', start_file)
            if start_file == -1 or end_file == -1:
                return {'raw': line}
            location = remaining[start_file+1:end_file]  # app.py:123

            # 分离文件名和行号
            if ':' in location:
                filename, lineno = location.rsplit(':', 1)
            else:
                filename = location
                lineno = '0'

            # 提取消息
            message = remaining[end_file+1:].strip()

            # 标准化级别名称
            level_map = {
                'CRITICAL': '致命',
                'ERROR': '错误',
                'NOTICE': '通知',
                'DEBUG': '调试',
                'INFO': '通知',
                'WARNING': '警告'
            }

            normalized_level = level_map.get(level, level)

            return {
                'timestamp': timestamp,
                'level': normalized_level,
                'level_code': level,
                'filename': filename,
                'lineno': lineno,
                'message': message,
                'raw': line
            }
    except Exception as e:
        return {'raw': line}

# 缩略图生成队列和信号量（限制并发生成数量）
MAX_CONCURRENT_THUMBNAIL_GENERATION = 2  # 最多同时生成2个缩略图
thumbnail_semaphore = threading.Semaphore(MAX_CONCURRENT_THUMBNAIL_GENERATION)
thumbnail_generation_queue = {}
# ========== 缩略图微服务集成 ==========

# 缩略图服务配置
THUMBNAIL_SERVICE_ENABLED = os.getenv('THUMBNAIL_SERVICE_ENABLED', 'true').lower() == 'true'
THUMBNAIL_SERVICE_URL = os.getenv('THUMBNAIL_SERVICE_URL', 'http://localhost:5001')
THUMBNAIL_FALLBACK_ENABLED = os.getenv('THUMBNAIL_FALLBACK_ENABLED', 'true').lower() == 'true'

# 缩略图服务客户端
thumbnail_client = None

# 本地缩略图生成状态（降级模式使用）
thumbnail_generation_status = {}  # 记录缩略图生成状态: 'pending', 'generating', 'ready', 'failed'
thumbnail_locks = {}  # 缩略图生成锁
thumbnail_locks_lock = threading.Lock()

def get_thumbnail_lock(video_hash):
    """获取视频的缩略图生成锁"""
    with thumbnail_locks_lock:
        if video_hash not in thumbnail_locks:
            thumbnail_locks[video_hash] = threading.Lock()
        return thumbnail_locks[video_hash]

def initialize_thumbnail_service():
    """初始化缩略图服务"""
    global thumbnail_client
    
    if THUMBNAIL_SERVICE_ENABLED:
        try:
            thumbnail_client = get_thumbnail_client()
            
            # 检查服务健康状态
            if thumbnail_client.check_health():
                logger.info(f"Thumbnail microservice connected: {THUMBNAIL_SERVICE_URL}")
            else:
                logger.warning(f"Thumbnail microservice unavailable, will use fallback mode: {THUMBNAIL_SERVICE_URL}")
                if THUMBNAIL_FALLBACK_ENABLED:
                    logger.info("Fallback mode enabled")
                else:
                    logger.error("Fallback mode not enabled, thumbnail feature will be unavailable")
        except Exception as e:
            logger.error(f"Failed to initialize thumbnail service: {str(e)}")
            if THUMBNAIL_FALLBACK_ENABLED:
                logger.info("Will use fallback mode (local generation)")
            else:
                logger.error("Fallback mode not enabled, thumbnail feature will be unavailable")
    else:
        logger.info("Thumbnail microservice not enabled, using local generation mode")

# 初始化数据库
db.init_app(app)

# 注册模板过滤器
@app.template_filter('format_number')
def format_number(num):
    """格式化数字显示"""
    if num >= 10000:
        return f"{num / 10000:.1f}万"
    return str(num)

@app.template_filter('format_duration')
def format_duration(seconds):
    """格式化视频时长显示"""
    if not seconds or seconds <= 0:
        return "00:00"
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"

# 添加本地视频文件路由
@app.route('/local_video/<path:video_path>')
def serve_local_video(video_path):
    """提供本地视频文件"""
    # 解码URL编码的路径
    try:
        print(f'[DEBUG] 原始video_path: {video_path}')
        from urllib.parse import unquote
        import html

        video_path = unquote(video_path)
        print(f'[DEBUG] URL解码后: {video_path}')

        # 如果包含HTML实体（如 &amp;），也需要解码
        if '&amp;' in video_path or '&lt;' in video_path or '&gt;' in video_path:
            video_path = html.unescape(video_path)
            print(f'[DEBUG] HTML实体解码后: {video_path}')

        # 规范化路径
        video_path = os.path.normpath(video_path).replace('\\', '/')
        print(f'[DEBUG] 规范化后: {video_path}')
        print(f'[DEBUG] 文件存在: {os.path.exists(video_path)}')

        # 检查路径是否允许访问
        scan_dirs = config.get('scan_directories', [])
        allowed = False
        for dir_config in scan_dirs:
            scan_path = dir_config.get('path', '').replace('\\', '/').replace('//', '/')
            if video_path.startswith(scan_path.replace('\\', '/')):
                allowed = True
                break

        if not allowed:
            abort(403, "路径不允许访问")

        # 检查文件是否存在
        if not os.path.exists(video_path):
            abort(404, "文件不存在")

        # 检查是否是文件
        if not os.path.isfile(video_path):
            abort(400, "不是有效的文件")

        # 发送文件
        return send_file(
            video_path,
            mimetype='video/mp4',
            as_attachment=False
        )
    except Exception as e:
        print(f'视频服务错误: {e}')
        abort(500, str(e))

# 懒加载缩略图路由
@app.route('/thumbnail/<video_hash>')
def serve_lazy_thumbnail(video_hash):
    """
    懒加载缩略图：如果不存在则触发异步生成并返回202
    
    优先使用缩略图微服务，如果微服务不可用则降级到本地生成
    """
    request_time = datetime.now()

    # 调试日志：记录请求开始
    debug_log.debug(f"[缩略图请求] 开始处理: video_hash={video_hash}, time={request_time.strftime('%H:%M:%S.%f')}")
    runtime_log.debug(f"[缩略图请求] video_hash={video_hash}")
    service_used = "microservice" if thumbnail_client and thumbnail_client.is_available() else "local"
    debug_log.debug(f"[缩略图服务] 使用服务: {service_used}")
    runtime_log.debug(f"[缩略图请求] video_hash={video_hash}")

    try:
        # 缩略图文件路径（使用视频hash作为文件名）
        thumbnail_dir = os.path.join('static', 'thumbnails')
        gif_path = os.path.join(thumbnail_dir, f'{video_hash}.gif')
        jpg_path = os.path.join(thumbnail_dir, f'{video_hash}.jpg')

        # 调试日志：检查缩略图文件
        gif_exists = os.path.exists(gif_path)
        jpg_exists = os.path.exists(jpg_path)
        debug_log.debug(f"[缩略图检查] gif_exists={gif_exists}, jpg_exists={jpg_exists}")

        # 如果缩略图已存在，直接返回
        if gif_exists:
            debug_log.debug(f"[缩略图快速返回] 使用GIF: {video_hash}")
            runtime_log.debug(f"[缩略图] 快速返回GIF: {video_hash}")
            response = send_file(gif_path, mimetype='image/gif')
            response.cache_control.max_age = 3600  # 缓存1小时
            return response
        elif jpg_exists:
            debug_log.debug(f"[缩略图快速返回] 使用JPG: {video_hash}")
            runtime_log.debug(f"[缩略图] 快速返回JPG: {video_hash}")
            response = send_file(jpg_path, mimetype='image/jpeg')
            response.cache_control.max_age = 3600  # 缓存1小时
            return response

        # 缩略图不存在，检查是否正在生成
        current_status = thumbnail_generation_status.get(video_hash, 'pending')

        if current_status == 'generating':
            debug_log.debug(f"[缩略图生成中] 缩略图正在生成: {video_hash}")
            # 返回202，告诉客户端正在生成
            response = jsonify({
                'status': 'generating',
                'message': '缩略图正在生成中，请稍后重试'
            })
            response.status_code = 202
            response.headers['Retry-After'] = '2'  # 建议2秒后重试
            return response

        # 缩略图不存在且没有在生成，触发异步生成
        trigger_time = datetime.now()
        debug_log.debug(f"[缩略图触发] 触发异步生成: video_hash={video_hash}, time={trigger_time.strftime('%H:%M:%S.%f')}")
        runtime_log.info(f"[缩略图触发] 触发缩略图生成: video_hash={video_hash}")

        # 更新状态为pending
        thumbnail_generation_status[video_hash] = 'pending'

        # 在后台线程中生成缩略图
        def generate_thumbnail_async():
            start_time = datetime.now()
            try:
                debug_log.debug(f"[缩略图异步] 开始异步生成: video_hash={video_hash}, time={start_time.strftime('%H:%M:%S.%f')}")

                # 查询视频
                video = Video.query.filter_by(hash=video_hash).first()
                if not video:
                    error_time = datetime.now()
                    debug_log.error(f"[缩略图异步] 视频不存在: video_hash={video_hash}, 耗时={(error_time - start_time).total_seconds():.3f}s")
                    thumbnail_generation_status[video_hash] = 'failed'
                    runtime_log.warning(f"[Thumbnail generation failed] Video does not exist: video_hash={video_hash}")
                    return

                # 更新状态为generating
                generating_time = datetime.now()
                thumbnail_generation_status[video_hash] = 'generating'
                runtime_log.info(f"[Thumbnail generation started] video_title={video.title}, video_hash={video_hash}, local_path={video.local_path}")
                debug_log.debug(f"[缩略图异步] 状态更新为generating: video_hash={video_hash}, 耗时={(generating_time - start_time).total_seconds():.3f}s")

                # 确保目录存在
                os.makedirs(thumbnail_dir, exist_ok=True)

                # 检查视频文件是否存在
                if not video.local_path:
                    debug_log.error(f"[缩略图异步] 视频local_path为空: {video_hash}")
                    thumbnail_generation_status[video_hash] = 'failed'
                    return

                if not os.path.exists(video.local_path):
                    debug_log.error(f"[缩略图异步] 视频文件不存在: {video.local_path}")
                    thumbnail_generation_status[video_hash] = 'failed'
                    return

                # 获取信号量
                with thumbnail_semaphore:
                    # 生成静态缩略图
                    jpg_start = datetime.now()
                    debug_log.debug(f"[缩略图异步] 开始生成静态缩略图: video_hash={video_hash}, time={jpg_start.strftime('%H:%M:%S.%f')}")
                    jpg_success = generate_video_thumbnail(video.local_path, jpg_path)

                    if jpg_success:
                        jpg_end = datetime.now()
                        debug_log.debug(f"[缩略图异步] 静态缩略图生成成功: video_hash={video_hash}, 耗时={(jpg_end - jpg_start).total_seconds():.3f}s")
                        thumbnail_generation_status[video_hash] = 'ready'
                        total_time = (datetime.now() - start_time).total_seconds()
                        runtime_log.info(f"[Thumbnail generation successful] Format=JPG, video_title={video.title}, video_hash={video_hash}, total_time={total_time:.3f}s, path={jpg_path}")
                        return

                    # 如果静态图失败，尝试生成GIF
                    gif_start = datetime.now()
                    debug_log.warning(f"[缩略图异步] 静态图生成失败，尝试GIF: video_hash={video_hash}")
                    gif_success = generate_video_gif(video.local_path, gif_path, num_frames=6, duration=500)

                    if gif_success:
                        gif_end = datetime.now()
                        debug_log.debug(f"[缩略图异步] GIF生成成功: video_hash={video_hash}, 耗时={(gif_end - gif_start).total_seconds():.3f}s")
                        thumbnail_generation_status[video_hash] = 'ready'
                        total_time = (datetime.now() - start_time).total_seconds()
                        runtime_log.info(f"[Thumbnail generation successful] Format=GIF, video_title={video.title}, video_hash={video_hash}, total_time={total_time:.3f}s, path={gif_path}")
                        return

                    # 两种格式都失败
                    total_time = (datetime.now() - start_time).total_seconds()
                    debug_log.error(f"[缩略图异步] 所有格式生成失败: video_hash={video_hash}, 耗时={total_time:.3f}s")
                    thumbnail_generation_status[video_hash] = 'failed'
                    runtime_log.error(f"[Thumbnail generation failed] video_title={video.title}, video_hash={video_hash}, local_path={video.local_path}, time_spent={total_time:.3f}s")

            except Exception as e:
                error_time = datetime.now()
                total_time = (error_time - start_time).total_seconds()
                debug_log.error(f"[缩略图异步] 生成异常: video_hash={video_hash}, error={e}, 耗时={total_time:.3f}s")
                import traceback
                debug_log.error(f"[缩略图异步] 堆栈跟踪:\n{traceback.format_exc()}")
                thumbnail_generation_status[video_hash] = 'failed'
                runtime_log.error(f"[Thumbnail generation exception] video_hash={video_hash}, error={str(e)}, time_spent={total_time:.3f}s")

        # 启动异步生成线程
        thread_start = datetime.now()
        thread = threading.Thread(target=generate_thumbnail_async, daemon=True)
        thread.start()
        debug_log.debug(f"[缩略图异步] 异步生成线程已启动: video_hash={video_hash}, time={thread_start.strftime('%H:%M:%S.%f')}")
        runtime_log.debug(f"[缩略图线程] 线程已启动: video_hash={video_hash}")

        # 返回202，告诉客户端缩略图正在生成
        response = jsonify({
            'status': 'pending',
            'message': '缩略图生成任务已启动，请稍后重试'
        })
        response.status_code = 202
        response.headers['Retry-After'] = '2'  # 建议2秒后重试
        return response

    except Exception as e:
        error_time = datetime.now()
        debug_log.error(f"[缩略图异常] 缩略图服务错误: video_hash={video_hash}, error={str(e)}, 耗时={(error_time - request_time).total_seconds():.3f}s")
        runtime_log.error(f"[Thumbnail exception] {video_hash}: {str(e)}")
        import traceback
        debug_log.error(f"[缩略图异常] 堆栈跟踪:\n{traceback.format_exc()}")
        # 返回错误和默认缩略图
        return serve_default_thumbnail()

def serve_default_thumbnail():
    """返回默认缩略图"""
    default_thumbnail = os.path.join('static', 'thumbnails', 'default.png')
    if os.path.exists(default_thumbnail):
        response = send_file(default_thumbnail, mimetype='image/png')
        # 设置较短的缓存时间，让浏览器能够重新请求
        response.cache_control.max_age = 5  # 5秒后过期
        return response
    abort(404, "缩略图不可用")

# 视频上传目录
UPLOAD_FOLDER = 'static/uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# 缩略图上传目录
THUMBNAIL_FOLDER = 'static/thumbnails'
if not os.path.exists(THUMBNAIL_FOLDER):
    os.makedirs(THUMBNAIL_FOLDER)
app.config['THUMBNAIL_FOLDER'] = THUMBNAIL_FOLDER

# 允许的文件扩展名
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'webm', 'mov', 'avi'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}


def allowed_file(filename, allowed_extensions):
    """检查文件扩展名是否允许"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

# 配置加载和保存函数
def load_config():
    """加载配置文件"""
    default_config = {
        "scan_directories": [
            {
                "path": "M:/<媒体库>",
                "recursive": True,
                "enabled": True
            }
        ],
        "auto_scan_on_startup": True,
        "scan_interval_minutes": 60,
        "supported_formats": [".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"],
        "default_tags": ["本地视频"],
        "default_priority": 0
    }

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 合并默认配置
                for key, value in default_config.items():
                    if key not in config:
                        config[key] = value
                return config
        except Exception as e:
            print(f'加载配置文件失败: {e}，使用默认配置')
    return default_config


def save_config(config):
    """保存配置文件"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f'保存配置文件失败: {e}')
        return False


# 加载配置
config = load_config()


def scan_directory(directory_path, recursive=True, supported_formats=None):
    """
    扫描目录查找视频文件

    Args:
        directory_path: 目录路径
        recursive: 是否递归扫描子目录
        supported_formats: 支持的视频格式列表

    Returns:
        视频文件路径列表
    """
    if supported_formats is None:
        supported_formats = config.get('supported_formats', ['.mp4', '.avi', '.mkv'])

    video_files = []

    # 检查目录是否存在
    if not os.path.exists(directory_path):
        print(f'目录不存在: {directory_path}')
        return video_files

    if not os.path.isdir(directory_path):
        print(f'路径不是目录: {directory_path}')
        return video_files

    # 扫描目录
    if recursive:
        # 递归扫描
        for root, dirs, files in os.walk(directory_path):
            for file in files:
                file_lower = file.lower()
                if any(file_lower.endswith(ext) for ext in supported_formats):
                    video_files.append(os.path.join(root, file))
    else:
        # 只扫描当前目录
        for file in os.listdir(directory_path):
            file_lower = file.lower()
            file_path = os.path.join(directory_path, file)
            if os.path.isfile(file_path) and any(file_lower.endswith(ext) for ext in supported_formats):
                video_files.append(file_path)

    return video_files


def get_video_duration(video_path):
    """
    获取视频时长（秒）

    Args:
        video_path: 视频文件路径

    Returns:
        视频时长（秒），失败返回None
    """
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        if cap.isOpened():
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
            if fps > 0:
                return int(frame_count / fps)
    except Exception as e:
        print(f'获取视频时长失败 {video_path}: {str(e)}')
    return None


def generate_video_frames(video_path, num_frames=6, size=(320, 180)):
    """
    从视频中平均截取多个关键帧

    Args:
        video_path: 视频文件路径
        num_frames: 截取帧数，默认6帧
        size: 图片尺寸，默认320x180

    Returns:
        帧列表，失败返回None
    """
    import cv2
    import numpy as np

    cap = None
    try:
        print(f'[DEBUG] 开始处理视频: {video_path}')
        print(f'[DEBUG] 文件是否存在: {os.path.exists(video_path)}')

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f'[ERROR] 无法打开视频文件: {video_path}')
            return None

        # 获取视频信息
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)

        print(f'[DEBUG] 总帧数: {total_frames}, FPS: {fps}')

        if total_frames == 0:
            print(f'[ERROR] 视频帧数为0: {video_path}')
            return None

        # 计算要截取的帧位置（均匀分布）
        frame_interval = max(1, total_frames // num_frames)
        frame_positions = [min(i * frame_interval, total_frames - 1) for i in range(num_frames)]

        print(f'[DEBUG] 帧间隔: {frame_interval}, 帧位置: {frame_positions}')

        frames = []
        for i, frame_pos in enumerate(frame_positions):
            # 跳转到指定帧
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_pos)

            # 读取帧
            ret, frame = cap.read()
            if ret:
                # 调整大小
                frame = cv2.resize(frame, size)
                frames.append(frame)
                print(f'[DEBUG] 成功读取第 {i+1} 帧 (位置: {frame_pos})')
            else:
                print(f'[WARNING] 读取第 {i+1} 帧失败 (位置: {frame_pos})')

        print(f'[DEBUG] 成功提取 {len(frames)} 帧')
        return frames if frames else None
    except ImportError as e:
        print(f'[ERROR] OpenCV 未安装: {str(e)}')
        print('[HINT] 请运行: pip install opencv-python')
        return None
    except Exception as e:
        print(f'[ERROR] 生成视频帧失败 {video_path}: {str(e)}')
        import traceback
        traceback.print_exc()
        return None
    finally:
        # 确保释放资源
        if cap is not None:
            cap.release()
            print(f'[DEBUG] 已释放视频捕获器')


def generate_video_gif(video_path, output_path, num_frames=6, size=(320, 180), duration=500):
    """
    生成视频预览GIF动图

    Args:
        video_path: 视频文件路径
        output_path: 输出GIF路径
        num_frames: 截取帧数，默认6帧
        size: 图片尺寸，默认320x180
        duration: 每帧持续时间（毫秒），默认500ms

    Returns:
        是否成功
    """
    start_time = datetime.now()

    debug_log.debug(f"[GIF generation] Start generating: video_path={video_path}, output={output_path}, num_frames={num_frames}, size={size}, duration={duration}ms")
    print(f'[DEBUG] 开始生成GIF: {output_path}')

    try:
        from PIL import Image

        # 生成帧
        debug_log.debug(f"[GIF生成] 调用generate_video_frames提取帧: num_frames={num_frames}")
        frames = generate_video_frames(video_path, num_frames, size)

        if not frames or len(frames) == 0:
            debug_log.error(f"[GIF生成] 无法提取视频帧: {video_path}")
            print(f'[ERROR] 无法提取视频帧')
            return False

        debug_log.debug(f"[GIF生成] 成功提取{len(frames)}帧")

        # 将OpenCV BGR格式转换为PIL RGB格式
        pil_frames = []
        import cv2
        convert_start = datetime.now()

        for i, frame in enumerate(frames):
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(rgb_frame)
            pil_frames.append(pil_image)
            debug_log.debug(f"[GIF生成] 转换第{i+1}/{len(frames)}帧为RGB格式")
            print(f'[DEBUG] 转换第 {i+1} 帧为RGB格式')

        convert_time = (datetime.now() - convert_start).total_seconds()
        debug_log.debug(f"[GIF生成] 帧格式转换完成: {len(pil_frames)}帧, 耗时={convert_time:.3f}s")

        # 确保输出目录存在
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # 保存为GIF
        debug_log.debug(f"[GIF生成] 开始保存GIF: {output_path}, frames={len(pil_frames)}, duration={duration}ms")
        print(f'[DEBUG] 保存GIF到: {output_path}')

        save_start = datetime.now()
        pil_frames[0].save(
            output_path,
            format='GIF',
            save_all=True,
            append_images=pil_frames[1:],
            duration=duration,
            loop=0,
            optimize=True
        )
        save_time = (datetime.now() - save_start).total_seconds()

        total_time = (datetime.now() - start_time).total_seconds()
        output_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0

        debug_log.debug(f"[GIF生成] 保存成功: output={output_path}, size={output_size}B, 耗时={save_time:.3f}s, 总耗时={total_time:.3f}s")
        print(f'[DEBUG] GIF生成成功: {output_path}')
        return True
    except ImportError as e:
        debug_log.error(f"[GIF生成] Pillow未安装: {str(e)}")
        print(f'[ERROR] Pillow 未安装: {str(e)}')
        print('[HINT] 请运行: pip install Pillow')
        return False
    except Exception as e:
        total_time = (datetime.now() - start_time).total_seconds()
        error_msg = f'生成GIF失败 {video_path}: {str(e)}'
        debug_log.error(f"[GIF生成] 异常: {error_msg}, 耗时={total_time:.3f}s\n{traceback.format_exc()}")
        print(f'[ERROR] {error_msg}')
        import traceback
        traceback.print_exc()
        return False


def generate_video_thumbnail(video_path, output_path, time_offset=5, size=(320, 180)):
    """
    生成视频缩略图（单帧静态图）

    Args:
        video_path: 视频文件路径
        output_path: 输出图片路径
        time_offset: 截取时间点（秒），默认5秒
        size: 图片尺寸，默认320x180

    Returns:
        是否成功
    """
    import cv2
    start_time = datetime.now()
    cap = None

    debug_log.debug(f"[缩略图生成函数] 开始生成: video_path={video_path}, output={output_path}, time_offset={time_offset}, size={size}")

    try:
        debug_log.debug(f"[缩略图生成函数] 检查视频文件: exists={os.path.exists(video_path)}, size={os.path.getsize(video_path)/(1024*1024):.2f}MB" if os.path.exists(video_path) else f"[缩略图生成函数] 视频文件不存在: {video_path}")

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            debug_log.error(f"[缩略图生成函数] 无法打开视频: {video_path}")
            print(f'[缩略图] 无法打开视频: {video_path}')
            return False

        # 获取视频总时长
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration = total_frames / fps if fps > 0 else 0

        debug_log.debug(f"[缩略图生成函数] 视频信息: fps={fps}, total_frames={total_frames}, resolution={width}x{height}, duration={duration:.2f}s")

        # 计算截取的帧数
        if fps > 0:
            frame_num = min(int(time_offset * fps), total_frames - 1)
        else:
            frame_num = min(10, total_frames - 1)

        debug_log.debug(f"[缩略图生成函数] 计算目标帧: time_offset={time_offset}s, target_frame={frame_num}/{total_frames}")

        # 跳转到指定帧
        set_result = cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        debug_log.debug(f"[缩略图生成函数] 跳转帧: frame_num={frame_num}, success={set_result}")

        # 读取帧
        read_start = datetime.now()
        ret, frame = cap.read()
        read_time = (datetime.now() - read_start).total_seconds()

        debug_log.debug(f"[缩略图生成函数] 读取帧: success={ret}, 耗时={read_time:.3f}s")

        if not ret:
            debug_log.error(f"[缩略图生成函数] 读取帧失败: {video_path}")
            print(f'[缩略图] 读取帧失败: {video_path}')
            return False

        # 调整大小
        resize_start = datetime.now()
        frame = cv2.resize(frame, size)
        resize_time = (datetime.now() - resize_start).total_seconds()

        debug_log.debug(f"[缩略图生成函数] 调整大小: {width}x{height} -> {size[0]}x{size[1]}, 耗时={resize_time:.3f}s")

        # 保存图片
        write_start = datetime.now()
        save_success = cv2.imwrite(output_path, frame)
        write_time = (datetime.now() - write_start).total_seconds()

        total_time = (datetime.now() - start_time).total_seconds()

        if save_success:
            output_size = os.path.getsize(output_path)
            debug_log.debug(f"[缩略图生成函数] 保存成功: output={output_path}, size={output_size}B, 耗时={write_time:.3f}s, 总耗时={total_time:.3f}s")
        else:
            debug_log.error(f"[缩略图生成函数] 保存失败: output={output_path}")
            print(f'[缩略图] 保存失败: {output_path}')

        return save_success
    except Exception as e:
        total_time = (datetime.now() - start_time).total_seconds()
        error_msg = f'生成缩略图失败 {video_path}: {str(e)}'
        debug_log.error(f"[缩略图生成函数] 异常: {error_msg}, 耗时={total_time:.3f}s\n{traceback.format_exc()}")
        print(error_msg)
        return False
    finally:
        # 确保释放资源
        if cap is not None:
            cap.release()
            debug_log.debug(f"[缩略图生成函数] 释放VideoCapture资源")


def add_local_videos(video_files, default_tags=None, default_priority=0):
    """
    将本地视频文件添加到数据库

    Args:
        video_files: 视频文件路径列表
        default_tags: 默认标签列表
        default_priority: 默认优先级

    Returns:
        添加的视频数量
    """
    if default_tags is None:
        default_tags = config.get('default_tags', ['本地视频'])

    added_count = 0

    try:
        for video_file in video_files:
            try:
                # 获取文件名作为标题（不带扩展名）
                file_name = os.path.basename(video_file)
                title = os.path.splitext(file_name)[0]

                # 生成视频hash（使用文件路径）
                video_hash = Video.generate_hash(video_file)

                # 检查是否已存在
                existing_video = Video.query.filter_by(hash=video_hash).first()
                if existing_video:
                    # 更新本地路径
                    if not existing_video.is_downloaded:
                        existing_video.is_downloaded = True
                        existing_video.local_path = video_file
                        normalized_path = video_file.replace('\\', '/')
                        existing_video.url = f'/local_video/{quote(normalized_path, safe=":/")}'  # 更新为本地服务URL
                        db.session.commit()
                    continue

                # 生成本地视频的URL（用于播放）
                # 将反斜杠转换为正斜杠，并进行URL编码以处理特殊字符
                normalized_path = video_file.replace('\\', '/')
                video_url = f'/local_video/{quote(normalized_path, safe=":/")}'

                # 获取视频时长
                video_duration = get_video_duration(video_file)

                # 懒加载缩略图：使用视频hash作为缩略图路径，但不立即生成
                # 缩略图会在首次访问时按需生成
                thumbnail_path = f'/thumbnail/{video_hash}'

                # 创建视频记录
                video = Video(
                    hash=video_hash,
                    title=title,
                    description=f'本地视频: {file_name}',
                    url=video_url,  # 使用本地服务URL
                    thumbnail=thumbnail_path,  # 使用懒加载路径
                    duration=video_duration,
                    priority=default_priority,
                    is_downloaded=True,
                    local_path=video_file
                )

                db.session.add(video)
                db.session.flush()  # 获取video.id

                # 添加标签
                for tag_name in default_tags:
                    tag = Tag.query.filter_by(name=tag_name).first()
                    if not tag:
                        category = '类型'
                        tag = Tag(name=tag_name, category=category)
                        db.session.add(tag)
                        db.session.flush()

                    # 创建视频-标签关联
                    video_tag = VideoTag(video_id=video.id, tag_id=tag.id)
                    db.session.add(video_tag)

                added_count += 1
            except Exception as e:
                print(f'添加视频 {video_file} 时出错: {str(e)}')
                continue

        db.session.commit()
    except Exception as e:
        print(f'批量添加视频时出错: {str(e)}')
        db.session.rollback()
    return added_count


def init_db():
    """初始化数据库"""
    with app.app_context():
        db.create_all()
        # 更新所有NULL的priority值
        videos = Video.query.filter(Video.priority.is_(None)).all()
        for video in videos:
            video.priority = 0
        if videos:
            db.session.commit()
            print(f'已更新 {len(videos)} 个视频的priority值')

        # 清理无效的视频标签关联
        orphan_video_tags = VideoTag.query.filter(
            ~VideoTag.video_id.in_(db.session.query(Video.id))
        ).all()
        for vt in orphan_video_tags:
            db.session.delete(vt)
        if orphan_video_tags:
            db.session.commit()
            print(f'已清理 {len(orphan_video_tags)} 个无效的视频标签关联')

        # 清理无效的用户交互记录
        orphan_interactions = UserInteraction.query.filter(
            ~UserInteraction.video_id.in_(db.session.query(Video.id))
        ).all()
        for ui in orphan_interactions:
            db.session.delete(ui)
        if orphan_interactions:
            db.session.commit()
            print(f'已清理 {len(orphan_interactions)} 个无效的用户交互记录')

        print('数据库初始化完成！')


def get_user_session():
    """获取或创建用户会话ID"""
    if 'user_session' not in session:
        session['user_session'] = str(random.randint(100000, 999999))
    return session['user_session']


@app.route('/')
def index():
    """首页 - 显示推荐视频"""
    user_session = get_user_session()
    recommended_videos = get_recommended_videos(user_session, limit=12)

    # 自动更新缺失的视频时长
    for video in recommended_videos:
        if video.duration is None and video.local_path and os.path.exists(video.local_path):
            try:
                duration = get_video_duration(video.local_path)
                if duration:
                    video.duration = duration
                    db.session.commit()
                    debug_log.debug(f"[时长更新] 自动更新时长: {video.title} = {duration}秒")
            except Exception as e:
                debug_log.warning(f"[Duration update] Update failed: {video.title}, error={e}")

    popular_tags = get_popular_tags(limit=10)

    # 对首页视频的标签按关联视频数排序
    for video in recommended_videos:
        valid_tags = []
        for vt in video.tags:
            if vt.tag:
                valid_tags.append({
                    'vt': vt,
                    'tag': vt.tag,
                    'video_count': vt.tag.video_count()
                })
        # 按视频数降序排序（视频数相同时按名称升序）
        valid_tags.sort(key=lambda x: (-x['video_count'], x['tag'].name))
        video._sorted_tags = [item['vt'] for item in valid_tags]

    return render_template('index.html',
                         videos=recommended_videos,
                         tags=popular_tags,
                         current_tag=None)


@app.route('/tag/<int:tag_id>')
def tag_page(tag_id):
    """标签页面 - 显示特定标签的视频"""
    tag = Tag.query.get_or_404(tag_id)
    
    # 获取当前用户角色
    current_role = AuthService.get_current_role()
    
    # 获取视频并进行权限过滤
    all_videos = [vt.video for vt in tag.videos if vt.video is not None]
    videos = [v for v in all_videos if current_role >= v.min_role]
    
    # 按优先级和播放量排序（处理None值）
    videos = sorted(videos, key=lambda v: (v.priority or 0, v.view_count or 0), reverse=True)
    popular_tags = get_popular_tags(limit=10)
    return render_template('index.html',
                         videos=videos,
                         tags=popular_tags,
                         current_tag=tag)


@app.route('/video/<video_hash>')
def video_page(video_hash):
    """视频播放页面"""
    video = Video.query.filter_by(hash=video_hash).first_or_404()

    # 检查权限
    current_role = AuthService.get_current_role()
    if current_role < video.min_role:
        # 权限不足
        required_role_name = ROLE_NAMES.get(video.min_role, '未知')
        return render_template('error.html', 
                             error_title='权限不足',
                             error_message=f'观看此视频需要{required_role_name}权限',
                             current_role=current_role,
                             required_role=video.min_role), 403

    # 记录播放
    user_session = get_user_session()
    record_interaction(video.id, user_session, 'view', score=1.0)

    # 增加播放计数
    video.view_count += 1
    db.session.commit()

    # 获取相关推荐（已自动过滤权限）
    recommended_videos = get_recommended_videos(user_session, limit=6, exclude_video_id=video.id)

    # 对视频的标签按关联视频数排序
    valid_tags = []
    for vt in video.tags:
        if vt.tag:
            valid_tags.append({
                'vt': vt,
                'tag': vt.tag,
                'video_count': vt.tag.video_count()
            })
    # 按视频数降序排序（视频数相同时按名称升序）
    valid_tags.sort(key=lambda x: (-x['video_count'], x['tag'].name))
    video._sorted_tags = [item['vt'] for item in valid_tags]

    return render_template('video.html',
                         video=video,
                         recommended_videos=recommended_videos)


@app.route('/search')
def search():
    """搜索功能"""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'videos': []})

    # 搜索标题和描述
    videos = Video.query.filter(
        (Video.title.contains(query)) |
        (Video.description.contains(query))
    ).all()

    # 搜索标签
    tag = Tag.query.filter(Tag.name.contains(query)).first()
    if tag:
        tag_videos = [vt.video for vt in tag.videos if vt.video is not None]
        # 合并结果去重
        video_ids = {v.id for v in videos}
        for v in tag_videos:
            if v.id not in video_ids:
                videos.append(v)

    return jsonify({
        'videos': [v.to_dict() for v in videos[:20]]
    })


@app.route('/ranking')
def ranking_page():
    """排行榜页面"""
    return render_template('index.html', is_ranking_page=True)


@app.route('/api/ranking', methods=['GET'])
def api_get_ranking():
    """获取排行榜数据"""
    ranking_type = request.args.get('type', 'view')  # view, like, download, duration
    limit = request.args.get('limit', 50, type=int)
    
    # 根据不同排序方式获取视频
    if ranking_type == 'like':
        videos = Video.query.order_by(Video.like_count.desc()).limit(limit).all()
        type_name = '点赞排行'
    elif ranking_type == 'download':
        videos = Video.query.order_by(Video.download_count.desc()).limit(limit).all()
        type_name = '下载排行'
    elif ranking_type == 'duration':
        videos = Video.query.filter(Video.duration.isnot(None)).order_by(Video.duration.desc()).limit(limit).all()
        type_name = '时长排行'
    else:  # view
        videos = Video.query.order_by(Video.view_count.desc()).limit(limit).all()
        type_name = '播放排行'
    
    return jsonify({
        'success': True,
        'videos': [v.to_dict() for v in videos],
        'type': ranking_type,
        'type_name': type_name,
        'total': len(videos)
    })


@app.route('/api/videos', methods=['GET'])
def api_get_videos():
    """获取视频列表API"""
    limit = request.args.get('limit', 20, type=int)
    offset = request.args.get('offset', 0, type=int)
    tag_id = request.args.get('tag_id', type=int)

    if tag_id:
        tag = Tag.query.get(tag_id)
        if tag:
            videos = [vt.video for vt in tag.videos if vt.video is not None]
            videos = sorted(videos, key=lambda v: (v.priority or 0, v.view_count or 0), reverse=True)
        else:
            videos = []
    else:
        videos = Video.query.all()
        videos = sorted(videos, key=lambda v: (v.priority or 0, v.view_count or 0), reverse=True)

    videos = videos[offset:offset + limit]

    return jsonify({
        'videos': [v.to_dict() for v in videos],
        'total': len(videos)
    })


@app.route('/api/videos/recommend', methods=['GET'])
def api_get_recommended_videos():
    """获取推荐视频列表API - 支持换一批功能"""
    limit = request.args.get('limit', 12, type=int)
    user_session = get_user_session()

    # 检查是否需要排除已显示的视频
    exclude_ids = request.args.get('exclude_ids', '')
    exclude_ids_list = [int(id_str) for id_str in exclude_ids.split(',') if id_str.strip()] if exclude_ids else []

    # 获取推荐视频
    recommended_videos = get_recommended_videos(user_session, limit=limit * 2)  # 获取更多候选视频

    # 过滤掉已显示的视频
    if exclude_ids_list:
        recommended_videos = [v for v in recommended_videos if v.id not in exclude_ids_list]

    # 如果过滤后不够，获取更多视频补充
    if len(recommended_videos) < limit:
        all_video_ids = [v.id for v in recommended_videos] + exclude_ids_list
        additional_videos = Video.query.filter(~Video.id.in_(all_video_ids)).all()
        random.shuffle(additional_videos)
        recommended_videos.extend(additional_videos[:limit - len(recommended_videos)])

    # 只返回需要的数量
    recommended_videos = recommended_videos[:limit]

    # 自动更新缺失的视频时长
    for video in recommended_videos:
        if video.duration is None and video.local_path and os.path.exists(video.local_path):
            try:
                duration = get_video_duration(video.local_path)
                if duration:
                    video.duration = duration
                    db.session.commit()
                    debug_log.debug(f"[时长更新] 自动更新时长: {video.title} = {duration}秒")
            except Exception as e:
                debug_log.warning(f"[Duration update] Update failed: {video.title}, error={e}")

    return jsonify({
        'videos': [v.to_dict() for v in recommended_videos],
        'total': len(recommended_videos),
        'excluded_count': len(exclude_ids_list)
    })


@app.route('/api/thumbnail/<video_hash>/status', methods=['GET'])
def check_thumbnail_status(video_hash):
    """
    检查缩略图是否已生成
    
    优先查询缩略图微服务，如果微服务不可用则检查本地文件
    """
    try:
        # 如果微服务可用，使用微服务查询
        if thumbnail_client and thumbnail_client.is_available():
            debug_log.debug(f"[缩略图状态] 使用微服务查询: video_hash={video_hash}")
            result = thumbnail_client.get_task_status_by_hash(video_hash)
            
            if result:
                status = result.get('status')
                thumbnail_format = result.get('format')
                
                return jsonify({
                    'success': True,
                    'status': status,
                    'format': thumbnail_format,
                    'thumbnail_url': f'/thumbnail/{video_hash}' if status == 'ready' else None,
                    'service': 'microservice'
                })
            else:
                debug_log.warning(f"[缩略图状态] 微服务查询失败，降级到本地: video_hash={video_hash}")
        
        # 降级到本地检查
        debug_log.debug(f"[缩略图状态] 使用本地检查: video_hash={video_hash}")
        thumbnail_dir = os.path.join('static', 'thumbnails')
        gif_path = os.path.join(thumbnail_dir, f'{video_hash}.gif')
        jpg_path = os.path.join(thumbnail_dir, f'{video_hash}.jpg')

        # 检查生成状态
        generation_status = thumbnail_generation_status.get(video_hash)

        # 检查文件是否已存在
        if os.path.exists(gif_path):
            status = 'ready'
            thumbnail_format = 'gif'
        elif os.path.exists(jpg_path):
            status = 'ready'
            thumbnail_format = 'jpg'
        elif generation_status in ['generating', 'pending']:
            # 正在生成或等待生成
            status = generation_status
            thumbnail_format = None
        else:
            # 未触发生成
            status = 'pending'
            thumbnail_format = None

        return jsonify({
            'success': True,
            'status': status,
            'format': thumbnail_format,
            'thumbnail_url': f'/thumbnail/{video_hash}' if status == 'ready' else None,
            'service': 'local'
        })
    except Exception as e:
        debug_log.error(f"[Thumbnail status] Query exception: video_hash={video_hash}, error={str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/video/<video_hash>', methods=['GET'])
def api_get_video(video_hash):
    """获取单个视频详情API"""
    video = Video.query.filter_by(hash=video_hash).first_or_404()
    return jsonify(video.to_dict())


@app.route('/api/video/<video_hash>/like', methods=['POST'])
def like_video(video_hash):
    """点赞视频"""
    video = Video.query.filter_by(hash=video_hash).first_or_404()
    user_session = get_user_session()

    video.like_count += 1
    record_interaction(video.id, user_session, 'like', score=2.0)
    db.session.commit()

    return jsonify({
        'success': True,
        'like_count': video.like_count
    })


@app.route('/api/video/<video_hash>/download', methods=['POST', 'GET'])
def download_video(video_hash):
    """下载视频（模拟）"""
    video = Video.query.filter_by(hash=video_hash).first_or_404()
    user_session = get_user_session()

    video.download_count += 1
    record_interaction(video.id, user_session, 'download', score=3.0)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': '下载已开始',
        'download_url': video.url,
        'download_count': video.download_count
    })


@app.route('/api/video/<video_hash>/priority', methods=['POST'])
def update_priority(video_hash):
    """更新视频优先级"""
    data = request.get_json()
    priority = data.get('priority', 0)

    video = Video.query.filter_by(hash=video_hash).first_or_404()
    video.priority = priority
    db.session.commit()

    return jsonify({
        'success': True,
        'message': '优先级已更新'
    })


@app.route('/api/video/<video_hash>/regenerate', methods=['POST'])
def regenerate_thumbnail(video_hash):
    """重新生成视频缩略图和更新时长"""
    video = Video.query.filter_by(hash=video_hash).first_or_404()

    if not video.local_path or not os.path.exists(video.local_path):
        return jsonify({
            'success': False,
            'message': '本地视频文件不存在'
        }), 400

    try:
        # 删除旧的缩略图文件
        for ext in ['.jpg', '.gif']:
            old_path = os.path.join('static', 'thumbnails', f'{video_hash}{ext}')
            if os.path.exists(old_path):
                os.remove(old_path)

        # 生成GIF预览图（循环播放的多帧）
        gif_path = os.path.join('static', 'thumbnails', f'{video_hash}.gif')
        gif_success = generate_video_gif(video.local_path, gif_path, num_frames=6, duration=500)

        # 如果GIF生成失败，生成静态缩略图
        thumbnail_path = os.path.join('static', 'thumbnails', f'{video_hash}.jpg')
        thumbnail_success = False

        if not gif_success:
            thumbnail_success = generate_video_thumbnail(video.local_path, thumbnail_path)

        # 懒加载机制：数据库中始终使用懒加载路径，不更新为静态路径
        # video.thumbnail 保持为 f'/thumbnail/{video_hash}'

        # 更新时长
        video_duration = get_video_duration(video.local_path)
        if video_duration:
            video.duration = video_duration

        db.session.commit()

        return jsonify({
            'success': True,
            'message': '缩略图和时长已更新',
            'thumbnail': f'/thumbnail/{video_hash}',  # 返回懒加载路径
            'duration': video.duration,
            'is_gif': gif_success
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'更新失败: {str(e)}'
        }), 500


@app.route('/api/tags', methods=['GET'])
def api_get_tags():
    """获取所有标签（按关联视频数降序排序）"""
    # 获取所有标签并关联视频数
    tags = Tag.query.all()
    # 按关联视频数降序排序（视频数相同时按名称升序）
    tags.sort(key=lambda t: (len(t.videos), t.name), reverse=False)
    tags.sort(key=lambda t: len(t.videos), reverse=True)
    return jsonify({
        'success': True,
        'tags': [tag.to_dict() for tag in tags]
    })


@app.route('/tags')
def tags_page():
    """标签管理页面"""
    return render_template('tags.html')


@app.route('/api/tags/add', methods=['POST'])
def api_add_tag():
    """添加新标签"""
    data = request.get_json()
    name = data.get('name', '').strip()
    category = data.get('category', '类型')

    if not name:
        return jsonify({
            'success': False,
            'message': '标签名称不能为空'
        }), 400

    # 检查标签是否已存在
    existing_tag = Tag.query.filter_by(name=name).first()
    if existing_tag:
        return jsonify({
            'success': False,
            'message': f'标签"{name}"已存在'
        }), 400

    # 创建新标签
    try:
        tag = Tag(name=name, category=category)
        db.session.add(tag)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'标签"{name}"添加成功',
            'tag': tag.to_dict()
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'添加失败: {str(e)}'
        }), 500


@app.route('/api/tags/<int:tag_id>', methods=['GET', 'PUT', 'DELETE'])
def api_manage_tag(tag_id):
    """管理单个标签(获取/更新/删除)"""
    tag = Tag.query.get_or_404(tag_id)

    if request.method == 'GET':
        return jsonify({
            'success': True,
            'tag': tag.to_dict()
        })

    elif request.method == 'PUT':
        data = request.get_json()
        name = data.get('name', '').strip()
        category = data.get('category', '类型')

        if not name:
            return jsonify({
                'success': False,
                'message': '标签名称不能为空'
            }), 400

        # 检查名称是否与其他标签冲突
        existing_tag = Tag.query.filter(
            Tag.name == name,
            Tag.id != tag_id
        ).first()
        if existing_tag:
            return jsonify({
                'success': False,
                'message': f'标签名称"{name}"已被使用'
            }), 400

        try:
            tag.name = name
            tag.category = category
            db.session.commit()

            return jsonify({
                'success': True,
                'message': f'标签"{name}"更新成功',
                'tag': tag.to_dict()
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({
                'success': False,
                'message': f'更新失败: {str(e)}'
            }), 500

    elif request.method == 'DELETE':
        # 检查关联的视频数量
        video_count = tag.video_count()
        tag_name = tag.name

        try:
            # 删除所有视频-标签关联
            VideoTag.query.filter_by(tag_id=tag_id).delete()

            # 删除标签
            db.session.delete(tag)
            db.session.commit()

            message = f'标签"{tag_name}"删除成功'
            if video_count > 0:
                message += f'，同时删除了 {video_count} 个视频关联'

            return jsonify({
                'success': True,
                'message': message
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({
                'success': False,
                'message': f'删除失败: {str(e)}'
            }), 500


@app.route('/api/tags/<int:tag_id>/videos', methods=['GET'])
def api_get_tag_videos(tag_id):
    """获取标签关联的所有视频"""
    tag = Tag.query.get_or_404(tag_id)

    videos = []
    for vt in tag.videos:
        if vt.video:
            # 获取视频的所有标签（包括当前标签）
            video_tags = []
            for video_vt in vt.video.tags:
                if video_vt.tag:
                    video_tags.append({
                        'tag_id': video_vt.tag_id,
                        'tag_name': video_vt.tag.name
                    })

            videos.append({
                'id': vt.video.id,
                'title': vt.video.title,
                'hash': vt.video.hash,
                'tags': video_tags
            })

    return jsonify({
        'success': True,
        'tag_id': tag_id,
        'tag_name': tag.name,
        'videos': videos
    })


@app.route('/api/video/<video_hash>/tags', methods=['GET', 'PUT'])
def manage_video_tags(video_hash):
    """获取或更新视频标签"""
    video = Video.query.filter_by(hash=video_hash).first_or_404()

    if request.method == 'GET':
        # 获取视频标签并排序
        valid_tags = []
        for vt in video.tags:
            if vt.tag:
                valid_tags.append({
                    'vt': vt,
                    'tag': vt.tag,
                    'video_count': vt.tag.video_count()
                })
        # 按视频数降序排序（视频数相同时按名称升序）
        valid_tags.sort(key=lambda x: (-x['video_count'], x['tag'].name))
        sorted_vts = [item['vt'] for item in valid_tags]

        return jsonify({
            'tags': [vt.tag.to_dict() for vt in sorted_vts],
            'tag_names': [vt.tag.name for vt in sorted_vts]
        })
    else:
        # 更新视频标签
        data = request.get_json()
        tag_names = data.get('tags', [])

        # 删除现有标签关联
        VideoTag.query.filter_by(video_id=video.id).delete()

        # 添加新标签
        for tag_name in tag_names:
            if not tag_name.strip():
                continue

            tag = Tag.query.filter_by(name=tag_name.strip()).first()
            if not tag:
                # 创建新标签
                category = '类型'
                tag = Tag(name=tag_name.strip(), category=category)
                db.session.add(tag)
                db.session.flush()

            # 创建关联
            video_tag = VideoTag(video_id=video.id, tag_id=tag.id)
            db.session.add(video_tag)

        db.session.commit()

        # 重新加载视频并排序标签
        db.session.refresh(video)
        valid_tags = []
        for vt in video.tags:
            if vt.tag:
                valid_tags.append({
                    'vt': vt,
                    'tag': vt.tag,
                    'video_count': vt.tag.video_count()
                })
        # 按视频数降序排序（视频数相同时按名称升序）
        valid_tags.sort(key=lambda x: (-x['video_count'], x['tag'].name))
        sorted_vts = [item['vt'] for item in valid_tags]

        return jsonify({
            'success': True,
            'message': '标签已更新',
            'tags': [vt.tag.to_dict() for vt in sorted_vts]
        })


@app.route('/api/video/<video_hash>/favorite', methods=['POST'])
def toggle_favorite(video_hash):
    """切换视频收藏状态"""
    video = Video.query.filter_by(hash=video_hash).first_or_404()
    user_session = get_user_session()

    # 查找是否已收藏
    interaction = UserInteraction.query.filter_by(
        video_id=video.id,
        user_session=user_session,
        interaction_type='favorite'
    ).first()

    if interaction:
        # 已收藏，取消收藏
        db.session.delete(interaction)
        favorited = False
    else:
        # 未收藏，添加收藏
        interaction = UserInteraction(
            video_id=video.id,
            user_session=user_session,
            interaction_type='favorite',
            interaction_score=5.0
        )
        db.session.add(interaction)
        favorited = True

    db.session.commit()

    return jsonify({
        'success': True,
        'favorited': favorited,
        'message': '已收藏' if favorited else '已取消收藏'
    })


@app.route('/api/video/<video_hash>/is-favorite', methods=['GET'])
def is_favorite(video_hash):
    """检查视频是否已收藏"""
    video = Video.query.filter_by(hash=video_hash).first_or_404()
    user_session = get_user_session()

    interaction = UserInteraction.query.filter_by(
        video_id=video.id,
        user_session=user_session,
        interaction_type='favorite'
    ).first()

    return jsonify({
        'is_favorite': interaction is not None
    })


@app.route('/api/favorites', methods=['GET'])
def api_get_favorites():
    """获取收藏列表API"""
    user_session = get_user_session()
    
    # 获取用户收藏的视频
    favorite_interactions = UserInteraction.query.filter_by(
        user_session=user_session,
        interaction_type='favorite'
    ).order_by(UserInteraction.created_at.desc()).all()
    
    favorite_videos = []
    for interaction in favorite_interactions:
        if interaction.video:
            favorite_videos.append(interaction.video)
    
    return jsonify({
        'success': True,
        'videos': [v.to_dict() for v in favorite_videos],
        'total': len(favorite_videos)
    })


@app.route('/favorites')
def favorites_page():
    """收藏页面"""
    user_session = get_user_session()

    # 获取用户收藏的视频
    favorite_interactions = UserInteraction.query.filter_by(
        user_session=user_session,
        interaction_type='favorite'
    ).order_by(UserInteraction.created_at.desc()).all()

    favorite_videos = []
    for interaction in favorite_interactions:
        if interaction.video:
            favorite_videos.append(interaction.video)

    popular_tags = get_popular_tags(limit=10)

    # 对视频的标签按关联视频数排序
    for video in favorite_videos:
        valid_tags = []
        for vt in video.tags:
            if vt.tag:
                valid_tags.append({
                    'vt': vt,
                    'tag': vt.tag,
                    'video_count': vt.tag.video_count()
                })
        # 按视频数降序排序（视频数相同时按名称升序）
        valid_tags.sort(key=lambda x: (-x['video_count'], x['tag'].name))
        video._sorted_tags = [item['vt'] for item in valid_tags]

    return render_template('index.html',
                         videos=favorite_videos,
                         tags=popular_tags,
                         current_tag=None,
                         is_favorites_page=True)


@app.route('/api/config', methods=['GET'])
def get_config():
    """获取配置"""
    return jsonify({
        'success': True,
        'config': config
    })


@app.route('/api/config', methods=['PUT'])
def update_config():
    """更新配置"""
    data = request.get_json()

    # 更新配置
    for key, value in data.items():
        config[key] = value

    # 保存到文件
    if save_config(config):
        return jsonify({
            'success': True,
            'message': '配置已更新',
            'config': config
        })
    else:
        return jsonify({
            'success': False,
            'message': '保存配置失败'
        }), 500


@app.route('/api/videos/clear', methods=['POST'])
def clear_videos():
    """清空所有视频数据"""
    data = request.get_json() or {}
    confirm_text = data.get('confirm_text', '')

    if confirm_text != 'CLEAR_ALL_VIDEOS':
        return jsonify({
            'success': False,
            'message': '请输入确认文本: CLEAR_ALL_VIDEOS'
        }), 400

    try:
        # 删除所有视频记录（包括关联的标签关系）
        Video.query.delete()
        # 删除视频标签关联表
        VideoTag.query.delete()
        db.session.commit()

        return jsonify({
            'success': True,
            'message': '所有视频数据已清空'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'清空失败: {str(e)}'
        }), 500


@app.route('/manage')
def manage_page():
    """视频管理页面 - 支持分页"""
    debug_log.debug(f"[管理页面] 开始加载管理页面")
    runtime_log.debug(f"[管理页面] 访问管理页面")

    # 获取分页参数
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    debug_log.debug(f"[管理页面] 分页参数: page={page}, per_page={per_page}")

    # 限制每页数量范围
    per_page = max(10, min(100, per_page))

    # 分页查询
    debug_log.debug(f"[管理页面] 开始查询数据库")
    pagination = Video.query.order_by(Video.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    debug_log.debug(f"[管理页面] 查询完成: total={pagination.total}, pages={pagination.pages}, current_page={pagination.page}, items={len(pagination.items)}")

    # 检查视频的缩略图状态
    thumbnail_dir = os.path.join('static', 'thumbnails')
    thumbnails_info = []

    for video in pagination.items:
        video_hash = video.hash
        gif_exists = os.path.exists(os.path.join(thumbnail_dir, f'{video_hash}.gif'))
        jpg_exists = os.path.exists(os.path.join(thumbnail_dir, f'{video_hash}.jpg'))
        has_thumbnail = gif_exists or jpg_exists

        thumbnails_info.append({
            'video_id': video.id,
            'video_hash': video_hash[:8] + '...',
            'title': video.title,
            'has_thumbnail': has_thumbnail,
            'gif_exists': gif_exists,
            'jpg_exists': jpg_exists,
            'is_downloaded': video.is_downloaded,
            'local_path': video.local_path
        })

        debug_log.debug(f"[管理页面] 视频缩略图状态: id={video.id}, hash={video_hash[:8]}..., has_thumbnail={has_thumbnail}, gif={gif_exists}, jpg={jpg_exists}")

    # 统计缩略图状态
    with_thumbnails = sum(1 for info in thumbnails_info if info['has_thumbnail'])
    without_thumbnails = sum(1 for info in thumbnails_info if not info['has_thumbnail'])

    debug_log.debug(f"[管理页面] 缩略图统计: 有缩略图={with_thumbnails}, 无缩略图={without_thumbnails}, 总计={len(thumbnails_info)}")
    runtime_log.info(f"[管理页面] 第{page}页: 总数={len(pagination.items)}, 有缩略图={with_thumbnails}, 无缩略图={without_thumbnails}")

    return render_template('manage.html',
                         videos=pagination.items,
                         page=page,
                         per_page=per_page,
                         total=pagination.total,
                         pages=pagination.pages)


@app.route('/logs')
def logs_page():
    """日志管理页面"""
    return render_template('logs.html')


@app.route('/api/video/upload', methods=['POST'])
def upload_video():
    """上传视频"""
    if 'video' not in request.files:
        return jsonify({'success': False, 'message': '没有选择视频文件'}), 400

    video_file = request.files['video']
    if video_file.filename == '':
        return jsonify({'success': False, 'message': '没有选择视频文件'}), 400

    if not allowed_file(video_file.filename, ALLOWED_VIDEO_EXTENSIONS):
        return jsonify({'success': False, 'message': '不支持的文件格式'}), 400

    # 保存视频文件
    video_filename = secure_filename(video_file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    video_filename = f"{timestamp}_{video_filename}"
    video_path = os.path.join(app.config['UPLOAD_FOLDER'], video_filename)
    video_file.save(video_path)

    # 处理缩略图
    thumbnail_url = None
    if 'thumbnail' in request.files:
        thumbnail_file = request.files['thumbnail']
        if thumbnail_file and allowed_file(thumbnail_file.filename, ALLOWED_IMAGE_EXTENSIONS):
            thumb_filename = secure_filename(thumbnail_file.filename)
            thumb_filename = f"{timestamp}_{thumb_filename}"
            thumb_path = os.path.join(app.config['THUMBNAIL_FOLDER'], thumb_filename)
            thumbnail_file.save(thumb_path)
            thumbnail_url = f"/static/thumbnails/{thumb_filename}"

    # 获取其他表单数据
    title = request.form.get('title', video_filename)
    description = request.form.get('description', '')
    tags_str = request.form.get('tags', '')
    priority = int(request.form.get('priority', 0))

    # 生成视频hash
    video_url = f"/static/uploads/{video_filename}"
    video_hash = hashlib.sha256(video_url.encode('utf-8')).hexdigest()

    # 创建视频记录
    video = Video(
        hash=video_hash,
        title=title,
        description=description,
        url=video_url,
        thumbnail=thumbnail_url or '/static/thumbnails/default.png',
        priority=priority,
        is_downloaded=True,
        local_path=video_path
    )

    # 处理标签
    if tags_str:
        tag_names = [t.strip() for t in tags_str.split(',') if t.strip()]
        for tag_name in tag_names:
            tag = Tag.query.filter_by(name=tag_name).first()
            if not tag:
                category = '类型'
                tag = Tag(name=tag_name, category=category)
                db.session.add(tag)
                db.session.flush()

            video.tags.append(tag)

    db.session.add(video)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': '视频上传成功',
        'video': video.to_dict()
    })


@app.route('/api/video/<video_hash>', methods=['DELETE'])
def delete_video(video_hash):
    """删除视频"""
    video = Video.query.filter_by(hash=video_hash).first_or_404()

    # 删除本地文件
    if video.local_path and os.path.exists(video.local_path):
        os.remove(video.local_path)

    db.session.delete(video)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': '视频已删除'
    })


@app.route('/api/check-file', methods=['POST'])
def check_file():
    """检查文件是否存在"""
    data = request.get_json()
    file_path = data.get('path')

    if not file_path:
        return jsonify({
            'success': False,
            'message': '缺少文件路径'
        })

    try:
        exists = os.path.exists(file_path)

        if exists:
            size = os.path.getsize(file_path)
        else:
            size = 0

        return jsonify({
            'success': True,
            'exists': exists,
            'size': size
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'检查文件失败: {str(e)}'
        })


@app.route('/api/scan', methods=['POST'])
def scan_videos():
    """扫描配置的目录并添加视频"""
    data = request.get_json() or {}
    scan_directories = data.get('scan_directories', None)
    force_rescan = data.get('force_rescan', False)

    # 使用传入的目录或配置文件中的目录
    if scan_directories is None:
        scan_directories = config.get('scan_directories', [])

    total_added = 0
    results = []

    for dir_config in scan_directories:
        if not dir_config.get('enabled', True):
            continue

        dir_path = dir_config.get('path', '')
        recursive = dir_config.get('recursive', True)

        print(f'正在扫描目录: {dir_path} (递归: {recursive})')

        try:
            # 扫描目录
            video_files = scan_directory(dir_path, recursive, config.get('supported_formats'))

            if force_rescan:
                # 强制重新扫描：删除所有此目录的视频并重新添加
                dir_prefix = dir_path.replace('\\', '/').rstrip('/')
                existing_videos = Video.query.filter(Video.url.like(f'{dir_prefix}%')).all()
                for video in existing_videos:
                    db.session.delete(video)
                db.session.commit()

            # 添加到数据库
            added = add_local_videos(
                video_files,
                default_tags=config.get('default_tags', ['本地视频']),
                default_priority=config.get('default_priority', 0)
            )

            total_added += added
            results.append({
                'directory': dir_path,
                'found': len(video_files),
                'added': added,
                'error': None
            })

            print(f'目录 {dir_path}: 找到 {len(video_files)} 个视频，添加 {added} 个')
        except Exception as e:
            print(f'扫描目录 {dir_path} 时出错: {str(e)}')
            results.append({
                'directory': dir_path,
                'found': 0,
                'added': 0,
                'error': str(e)
            })

    return jsonify({
        'success': True,
        'message': f'扫描完成，共添加 {total_added} 个视频',
        'total_added': total_added,
        'results': results
    })


@app.route('/api/thumbnails/regenerate', methods=['POST'])
def regenerate_all_thumbnails():
    """批量重新生成所有视频的缩略图和时长"""
    print("\n" + "="*60)
    print('[INFO] 开始批量重新生成缩略图...')
    print("="*60)

    videos = Video.query.filter(Video.local_path.isnot(None)).all()
    total = len(videos)

    print(f'[INFO] 找到 {total} 个有本地路径的视频')

    if total == 0:
        return jsonify({'success': False, 'message': '没有本地视频需要处理'})

    # 生成唯一的任务ID
    task_id = f'thumb_{datetime.now().strftime("%Y%m%d%H%M%S")}'

    print(f'[INFO] 创建任务ID: {task_id}')

    # 初始化进度
    progress_store[task_id] = {
        'current': 0,
        'total': total,
        'status': 'running',
        'message': '准备开始...'
    }

    print(f'[INFO] 初始化进度: {progress_store[task_id]}')

    # 在后台线程中执行缩略图生成
    def generate_in_background():
        print(f"\n[线程] 后台任务线程开始: {task_id}")

        success_count = 0
        gif_count = 0
        no_path_count = 0
        not_exist_count = 0
        errors = []

        try:
            for i, video in enumerate(videos, 1):
                try:
                    # 更新进度
                    progress_store[task_id]['current'] = i
                    progress_store[task_id]['message'] = f'正在处理: {video.title}'
                    print(f"\n[进度 {i}/{total}] {video.title}")

                    if not video.local_path:
                        no_path_count += 1
                        print(f"  [跳过] 没有本地路径")
                        continue

                    if not os.path.exists(video.local_path):
                        not_exist_count += 1
                        print(f"  [跳过] 文件不存在")
                        continue

                    print(f"  [路径] {video.local_path}")

                    # 删除旧的缩略图文件
                    for ext in ['.jpg', '.gif']:
                        old_path = os.path.join('static', 'thumbnails', f'{video.hash}{ext}')
                        if os.path.exists(old_path):
                            os.remove(old_path)
                            print(f"  [删除] {old_path}")

                    # 生成GIF预览图
                    gif_path = os.path.join('static', 'thumbnails', f'{video.hash}.gif')
                    print(f"  [开始] 生成GIF预览...")
                    gif_success = generate_video_gif(video.local_path, gif_path, num_frames=6, duration=500)

                    # 如果GIF生成失败，生成静态缩略图
                    thumbnail_path = os.path.join('static', 'thumbnails', f'{video.hash}.jpg')
                    thumbnail_success = False

                    if not gif_success:
                        print(f"  [降级] GIF失败,生成静态图...")
                        thumbnail_success = generate_video_thumbnail(video.local_path, thumbnail_path)

                    if gif_success:
                        # 懒加载机制：不更新数据库中的 thumbnail 字段
                        gif_count += 1
                        print(f"  [成功] GIF生成成功")
                    elif thumbnail_success:
                        # 懒加载机制：不更新数据库中的 thumbnail 字段
                        print(f"  [成功] JPG生成成功")
                    else:
                        print(f"  [失败] 预览图生成失败")
                        errors.append(f'{video.title}: 预览图生成失败')

                    # 更新时长
                    video_duration = get_video_duration(video.local_path)
                    if video_duration:
                        video.duration = video_duration

                    success_count += 1

                    # 更新进度信息
                    progress = (i / total) * 100
                    progress_store[task_id]['progress'] = progress
                    print(f"  [进度条] {progress:.1f}%")

                    # 每处理完一个视频后短暂休息，避免CPU和磁盘I/O占用过高
                    # 每处理5个视频后稍长的休息
                    if i % 5 == 0:
                        time.sleep(0.5)  # 每5个视频休息0.5秒
                    else:
                        time.sleep(0.1)  # 每个视频休息0.1秒

                except Exception as e:
                    error_msg = f'{video.title}: {str(e)}'
                    errors.append(error_msg)
                    print(f"\n[错误] 处理视频失败:")
                    print(f"  异常: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    continue

            db.session.commit()

            # 完成
            progress_store[task_id]['status'] = 'completed'
            progress_store[task_id]['message'] = f'完成! 成功生成 {success_count}/{total} 个缩略图 ({gif_count} 个GIF)'
            progress_store[task_id]['success_count'] = success_count

            print(f"\n[完成] 任务完成: {success_count}/{total} 个缩略图, {gif_count} 个GIF")
            print(f"[统计] 成功={success_count}, GIF={gif_count}, 无路径={no_path_count}, 文件不存在={not_exist_count}")
            print("="*60 + "\n")

        except Exception as e:
            progress_store[task_id]['status'] = 'error'
            progress_store[task_id]['message'] = f'出错: {str(e)}'
            print(f"\n[严重错误] {str(e)}")
            import traceback
            traceback.print_exc()
            print("="*60 + "\n")

    # 启动后台线程
    thread = threading.Thread(target=generate_in_background, daemon=False)
    thread.start()
    print(f"[线程] 后台线程已启动\n")

    # 立即返回,不等待线程完成
    return jsonify({
        'success': True,
        'task_id': task_id,
        'total': total,
        'message': f'开始处理 {total} 个视频...'
    })


@app.route('/api/thumbnails/progress/<task_id>')
def get_thumbnail_progress(task_id):
    """获取缩略图生成进度"""
    print(f"[进度查询] task_id={task_id}")

    if task_id in progress_store:
        progress = progress_store[task_id]
        print(f"[进度数据] {progress}")
        return jsonify({
            'success': True,
            'data': progress
        })

    print(f"[警告] 任务 {task_id} 不存在于进度存储中")
    return jsonify({
        'success': False,
        'message': '任务不存在'
    })


@app.route('/api/video/add', methods=['POST'])
def add_video_url():
    """通过URL添加视频"""
    data = request.get_json()
    video_url = data.get('url', '').strip()

    if not video_url:
        return jsonify({'success': False, 'message': '请输入视频URL'}), 400

    if not video_url.startswith('http://') and not video_url.startswith('https://'):
        return jsonify({'success': False, 'message': '请输入有效的URL'}), 400

    # 检查是否已存在
    video_hash = Video.generate_hash(video_url)
    existing_video = Video.query.filter_by(hash=video_hash).first()
    if existing_video:
        return jsonify({'success': False, 'message': '该视频已存在'}), 400

    # 创建视频记录
    title = data.get('title', '未命名视频')
    description = data.get('description', '')
    thumbnail = data.get('thumbnail', '/static/thumbnails/default.png')
    duration = data.get('duration', 0)
    tags_str = data.get('tags', '')
    priority = int(data.get('priority', 0))

    video = Video(
        hash=video_hash,
        title=title,
        description=description,
        url=video_url,
        thumbnail=thumbnail,
        duration=duration,
        priority=priority
    )

    # 处理标签
    if tags_str:
        tag_names = [t.strip() for t in tags_str.split(',') if t.strip()]
        for tag_name in tag_names:
            tag = Tag.query.filter_by(name=tag_name).first()
            if not tag:
                category = '类型'
                tag = Tag(name=tag_name, category=category)
                db.session.add(tag)
                db.session.flush()

            video.tags.append(tag)

    db.session.add(video)
    db.session.commit()

    return jsonify({
        'success': True,
        'message': '视频添加成功',
        'video': video.to_dict()
    })


def get_recommended_videos(user_session, limit=10, exclude_video_id=None):
    """获取推荐视频 - 优先推荐已有缩略图的视频
    
    Args:
        user_session: 用户会话ID
        limit: 返回视频数量限制
        exclude_video_id: 需要排除的视频ID
    """
    debug_log.debug(f"[推荐系统] 开始获取推荐视频: user_session={user_session}, limit={limit}, exclude_video_id={exclude_video_id}")
    runtime_log.debug(f"[推荐] 开始获取推荐: limit={limit}")

    # 获取当前用户角色
    current_role = AuthService.get_current_role()
    debug_log.debug(f"[推荐系统] 当前用户角色: {current_role} ({ROLE_NAMES.get(current_role, '未知')})")

    # 获取用户偏好的标签
    user_preferences = UserPreference.query.filter_by(user_session=user_session).order_by(
        UserPreference.preference_score.desc()
    ).limit(5).all()

    debug_log.debug(f"[推荐系统] 用户偏好标签数量: {len(user_preferences)}")
    if user_preferences:
        for i, pref in enumerate(user_preferences):
            debug_log.debug(f"[推荐系统] 偏好{i+1}: tag_id={pref.tag_id}, score={pref.preference_score}")

    # 获取所有视频，并进行权限过滤
    all_videos = Video.query.all()
    debug_log.debug(f"[推荐系统] 数据库总视频数: {len(all_videos)}")
    
    # 权限过滤：只显示当前用户有权限观看的视频
    videos = [v for v in all_videos if current_role >= v.min_role]
    debug_log.debug(f"[推荐系统] 权限过滤后视频数: {len(videos)} (已过滤{len(all_videos) - len(videos)}个无权限视频)")

    # 预先检查哪些视频有缩略图
    thumbnail_dir = os.path.join('static', 'thumbnails')
    videos_with_thumbnails = []
    videos_without_thumbnails = []

    for video in videos:
        if exclude_video_id and video.id == exclude_video_id:
            continue

        video_hash = video.hash
        gif_path = os.path.join(thumbnail_dir, f'{video_hash}.gif')
        jpg_path = os.path.join(thumbnail_dir, f'{video_hash}.jpg')
        has_thumbnail = os.path.exists(gif_path) or os.path.exists(jpg_path)

        if has_thumbnail:
            videos_with_thumbnails.append(video)
            debug_log.debug(f"[推荐系统] 有缩略图: video_id={video.id}, hash={video_hash[:8]}..., title={video.title}")
        else:
            videos_without_thumbnails.append(video)
            debug_log.debug(f"[推荐系统] 无缩略图: video_id={video.id}, hash={video_hash[:8]}..., title={video.title}")

    debug_log.debug(f"[推荐系统] 缩略图统计: 有缩略图={len(videos_with_thumbnails)}, 无缩略图={len(videos_without_thumbnails)}")

    # 如果有缩略图的视频数量足够，只从有缩略图的视频中选择
    if len(videos_with_thumbnails) >= limit:
        debug_log.debug(f"[推荐系统] 只推荐有缩略图的视频")
        video_scores = []
        for video in videos_with_thumbnails:
            # 基础分数：优先级和播放量
            score = (video.priority or 0) * 0.3 + (video.view_count or 0) * 0.0001

            # 添加随机因子
            random_factor = random.random() * 5
            score += random_factor

            # 根据用户偏好加分
            if user_preferences:
                for pref in user_preferences:
                    if any(tag.tag_id == pref.tag_id for tag in video.tags):
                        score += pref.preference_score * 5
                        debug_log.debug(f"[推荐系统] 偏好加分: video_id={video.id}, tag_id={pref.tag_id}, score_added={pref.preference_score * 5}")

            video_scores.append((video, score))

        # 排序并取推荐
        video_scores.sort(key=lambda x: x[1], reverse=True)
        recommended = [v for v, s in video_scores[:limit]]
        debug_log.debug(f"[推荐系统] 推荐完成: 推荐了{len(recommended)}个视频，都有缩略图")
    else:
        # 有缩略图的视频不够，混合推荐
        debug_log.debug(f"[推荐系统] 有缩略图的视频不够，混合推荐")
        # 先取出所有有缩略图的视频
        recommended = videos_with_thumbnails.copy()

        # 需要补充的数量
        additional_needed = limit - len(recommended)

        # 从没有缩略图的视频中选择（尽量少选）
        if additional_needed > 0 and len(videos_without_thumbnails) > 0:
            debug_log.debug(f"[推荐系统] 需要从无缩略图视频补充{additional_needed}个")
            additional_scores = []
            for video in videos_without_thumbnails:
                # 基础分数
                score = (video.priority or 0) * 0.3 + (video.view_count or 0) * 0.0001

                # 添加随机因子
                random_factor = random.random() * 15
                score += random_factor

                # 根据用户偏好加分
                if user_preferences:
                    for pref in user_preferences:
                        if any(tag.tag_id == pref.tag_id for tag in video.tags):
                            score += pref.preference_score * 5

                additional_scores.append((video, score))

            # 排序并补充
            additional_scores.sort(key=lambda x: x[1], reverse=True)
            recommended.extend([v for v, s in additional_scores[:additional_needed]])
            debug_log.debug(f"[推荐系统] 补充完成: 补充了{additional_needed}个无缩略图视频")

    debug_log.debug(f"[推荐系统] 最终推荐: 总数={len(recommended)}, 有缩略图={len(videos_with_thumbnails) if recommended == videos_with_thumbnails else len([v for v in recommended if v in videos_with_thumbnails])}")
    runtime_log.debug(f"[推荐] 完成推荐: 总数={len(recommended)}, 需要生成缩略图={len([v for v in recommended if v not in videos_with_thumbnails])}")

    return recommended


def record_interaction(video_id, user_session, interaction_type, score=1.0):
    """记录用户交互并更新用户偏好"""
    # 记录交互
    interaction = UserInteraction(
        video_id=video_id,
        user_session=user_session,
        interaction_type=interaction_type,
        interaction_score=score
    )
    db.session.add(interaction)

    # 更新用户偏好
    video_tags = VideoTag.query.filter_by(video_id=video_id).all()
    for vt in video_tags:
        preference = UserPreference.query.filter_by(
            user_session=user_session,
            tag_id=vt.tag_id
        ).first()

        if preference:
            preference.preference_score += score * 0.1
            preference.interaction_count += 1
            preference.updated_at = datetime.utcnow()
        else:
            preference = UserPreference(
                user_session=user_session,
                tag_id=vt.tag_id,
                preference_score=1.0 + score * 0.1,
                interaction_count=1
            )
            db.session.add(preference)

    db.session.commit()


def get_popular_tags(limit=10):
    """获取热门标签"""
    tags = Tag.query.all()
    tags.sort(key=lambda t: len(t.videos), reverse=True)
    return tags[:limit]


@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy'
    })


@app.route('/api/dependencies/check', methods=['GET'])
def check_dependencies():
    """检查依赖是否正确安装"""
    dependencies = {
        'opencv': {'name': 'opencv-python', 'installed': False, 'version': None},
        'pillow': {'name': 'Pillow', 'installed': False, 'version': None},
        'flask': {'name': 'Flask', 'installed': False, 'version': None},
    }

    # 检查 OpenCV
    try:
        import cv2
        dependencies['opencv']['installed'] = True
        dependencies['opencv']['version'] = cv2.__version__
    except ImportError:
        pass

    # 检查 Pillow
    try:
        from PIL import Image
        dependencies['pillow']['installed'] = True
        dependencies['pillow']['version'] = Image.__version__
    except ImportError:
        pass

    # 检查 Flask
    try:
        import flask
        dependencies['flask']['installed'] = True
        dependencies['flask']['version'] = flask.__version__
    except ImportError:
        pass

    all_installed = all(dep['installed'] for dep in dependencies.values())

    return jsonify({
        'success': all_installed,
        'dependencies': dependencies,
        'message': '所有依赖已安装' if all_installed else '部分依赖未安装'
    })


def generate_missing_thumbnails_async():
    """后台任务：预生成缺失的缩略图"""
    print('[缩略图预生成] 后台任务启动')

    try:
        # 等待一段时间，避免影响应用启动
        time.sleep(10)

        thumbnail_dir = os.path.join('static', 'thumbnails')
        # 使用 app_context，兼容 Waitress 等非 Werkzeug 服务器（线程中无自动上下文）
        with app.app_context():
            videos = Video.query.filter(Video.local_path.isnot(None)).all()

            for i, video in enumerate(videos, 1):
                # 检查是否已有缩略图
                video_hash = video.hash
                gif_path = os.path.join(thumbnail_dir, f'{video_hash}.gif')
                jpg_path = os.path.join(thumbnail_dir, f'{video_hash}.jpg')

                if os.path.exists(gif_path) or os.path.exists(jpg_path):
                    continue

                # 检查视频文件是否存在
                if not video.local_path or not os.path.exists(video.local_path):
                    continue

                # 生成缩略图
                try:
                    print(f'[缩略图预生成] {i}/{len(videos)}: {video.title}')

                    # 优先生成静态缩略图
                    jpg_success = generate_video_thumbnail(video.local_path, jpg_path)

                    if not jpg_success:
                        # 静态图失败则尝试GIF
                        gif_success = generate_video_gif(video.local_path, gif_path, num_frames=6, duration=500)

                    # 每生成一个缩略图后休息一下，避免占用过多资源
                    time.sleep(0.1)

                except Exception as e:
                    print(f'[缩略图预生成] 失败: {video.title}, 错误: {e}')
                    continue

        print('[缩略图预生成] 后台任务完成')

    except Exception as e:
        print(f'[缩略图预生成] 后台任务异常: {e}')

# ========== 日志管理API ==========

@app.route('/api/logs', methods=['GET'])
def api_get_logs():
    """获取日志文件列表，按类型分组"""
    try:
        log_groups = get_log_files()
        return jsonify({
            'success': True,
            'log_groups': log_groups,
            'log_types': LOG_TYPES,
            'total_types': len(LOG_TYPES)
        })
    except Exception as e:
        runtime_log.error(f"获取日志列表失败: {e}")
        return jsonify({
            'success': False,
            'message': f'获取日志列表失败: {str(e)}'
        }), 500

@app.route('/api/logs/<path:filepath>', methods=['GET'])
def api_get_log_content(filepath):
    """获取指定日志文件的内容"""
    try:
        # 安全检查：只允许读取logs目录下的文件
        if '..' in filepath or filepath.startswith('/'):
            return jsonify({
                'success': False,
                'message': '无效的文件路径'
            }), 400

        full_path = os.path.join(LOG_DIR, filepath)

        # 检查文件是否存在
        if not os.path.exists(full_path) or not os.path.isfile(full_path):
            return jsonify({
                'success': False,
                'message': '文件不存在'
            }), 404

        # 获取参数
        lines = request.args.get('lines', 100, type=int)
        search = request.args.get('search', '')
        level = request.args.get('level', '')

        # 标准化级别名称
        level_map_reverse = {
            '致命': 'CRITICAL',
            '错误': 'ERROR',
            '通知': 'NOTICE',
            '调试': 'DEBUG'
        }
        level_code = level_map_reverse.get(level, level) if level else ''

        # 读取日志行
        log_lines = get_log_lines(full_path, line_count=lines, search=search, level=level_code)

        # 解析日志
        parsed_logs = [parse_log_line(line) for line in log_lines]

        response = jsonify({
            'success': True,
            'filename': filepath,
            'lines': len(parsed_logs),
            'logs': parsed_logs
        })

        # 添加缓存控制头，防止浏览器缓存
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'

        return response
    except Exception as e:
        runtime_log.error(f"读取日志内容失败: {e}")
        traceback.print_exc()
        return jsonify({
            'success': False,
            'message': f'读取日志失败: {str(e)}'
        }), 500

@app.route('/api/logs/download/<path:filepath>', methods=['GET'])
def api_download_log(filepath):
    """下载日志文件"""
    try:
        # 安全检查
        if '..' in filepath or filepath.startswith('/'):
            return jsonify({
                'success': False,
                'message': '无效的文件路径'
            }), 400

        full_path = os.path.join(LOG_DIR, filepath)

        if not os.path.exists(full_path) or not os.path.isfile(full_path):
            return jsonify({
                'success': False,
                'message': '文件不存在'
            }), 404

        return send_file(
            full_path,
            as_attachment=True,
            download_name=os.path.basename(filepath),
            mimetype='text/plain'
        )
    except Exception as e:
        runtime_log.error(f"下载日志失败: {e}")
        return jsonify({
            'success': False,
            'message': f'下载失败: {str(e)}'
        }), 500

@app.route('/api/logs/clear', methods=['POST'])
def api_clear_logs():
    """清空所有日志文件"""
    try:
        if not os.path.exists(LOG_DIR):
            return jsonify({
                'success': True,
                'message': '日志目录不存在'
            })

        # 删除所有日志文件
        deleted_count = 0
        for log_type, log_file in LOG_FILES.items():
            base_filename = os.path.basename(log_file)

            for filename in os.listdir(LOG_DIR):
                if filename.startswith(base_filename):
                    filepath = os.path.join(LOG_DIR, filename)
                    try:
                        os.remove(filepath)
                        deleted_count += 1
                    except Exception as e:
                        runtime_log.error(f"删除日志文件失败 {filename}: {e}")

        runtime_log.notice(f"清空了 {deleted_count} 个日志文件")

        return jsonify({
            'success': True,
            'message': f'成功清空 {deleted_count} 个日志文件',
            'deleted_count': deleted_count
        })
    except Exception as e:
        runtime_log.error(f"清空日志失败: {e}")
        return jsonify({
            'success': False,
            'message': f'清空失败: {str(e)}'
        }), 500

@app.route('/api/logs/clear/<log_type>', methods=['POST'])
def api_clear_log_by_type(log_type):
    """清空指定类型的日志文件"""
    try:
        if log_type not in LOG_TYPES:
            return jsonify({
                'success': False,
                'message': f'无效的日志类型: {log_type}'
            }), 400

        if not os.path.exists(LOG_DIR):
            return jsonify({
                'success': True,
                'message': '日志目录不存在'
            })

        log_file = LOG_FILES[log_type]
        base_filename = os.path.basename(log_file)  # 例如: debug.log
        runtime_log.info(f"[日志清空] log_type={log_type}, base_filename={base_filename}")

        # 获取logger并刷新所有文件处理器以释放缓冲
        logger = logging.getLogger(log_type)
        handlers_to_flush = []
        for handler in logger.handlers[:]:  # 遍历所有处理器
            if isinstance(handler, logging.FileHandler):
                handlers_to_flush.append(handler)
                handler.flush()  # 刷新缓冲区

        # 清空该类型的所有日志文件（包括轮转备份）
        cleared_count = 0
        for filename in os.listdir(LOG_DIR):
            # 匹配主日志文件和所有轮转文件 (debug.log, debug.log.1, debug.log.2, etc.)
            if filename == base_filename or filename.startswith(base_filename + '.'):
                filepath = os.path.join(LOG_DIR, filename)
                try:
                    # 打开文件并清空内容
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.truncate(0)
                    cleared_count += 1
                    runtime_log.info(f"[日志清空] 清空日志文件: {filename}")
                except Exception as e:
                    runtime_log.error(f"清空日志文件失败 {filename}: {e}")

        runtime_log.notice(f"清空了 {LOG_TYPES[log_type]} 的 {cleared_count} 个日志文件")

        return jsonify({
            'success': True,
            'message': f'成功清空 {LOG_TYPES[log_type]} 的 {cleared_count} 个日志文件',
            'cleared_count': cleared_count,
            'log_type': log_type
        })
    except Exception as e:
        runtime_log.error(f"清空日志失败: {e}")
        return jsonify({
            'success': False,
            'message': f'清空失败: {str(e)}'
        }), 500

@app.route('/api/logs/size', methods=['GET'])
def api_get_logs_size():
    """获取日志目录总大小"""
    try:
        if not os.path.exists(LOG_DIR):
            return jsonify({
                'success': True,
                'total_size': 0,
                'total_size_mb': 0,
                'file_count': 0,
                'by_type': {}
            })

        total_size = 0
        file_count = 0
        by_type = {}

        for log_type, log_file in LOG_FILES.items():
            base_filename = os.path.basename(log_file)
            type_size = 0
            type_count = 0

            for filename in os.listdir(LOG_DIR):
                if filename.startswith(base_filename):
                    filepath = os.path.join(LOG_DIR, filename)
                    if os.path.isfile(filepath):
                        size = os.path.getsize(filepath)
                        type_size += size
                        total_size += size
                        type_count += 1
                        file_count += 1

            by_type[log_type] = {
                'name': LOG_TYPES[log_type],
                'size': type_size,
                'size_mb': round(type_size / (1024 * 1024), 2),
                'count': type_count
            }

        return jsonify({
            'success': True,
            'total_size': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'file_count': file_count,
            'by_type': by_type
        })
    except Exception as e:
        runtime_log.error(f"获取日志大小失败: {e}")
        return jsonify({
            'success': False,
            'message': f'获取日志大小失败: {str(e)}'
        }), 500

        return jsonify({
            'success': True,
            'total_size': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'file_count': file_count
        })
    except Exception as e:
        logger.error(f"获取日志大小失败: {e}")
        return jsonify({
            'success': False,
            'message': f'获取失败: {str(e)}'
        }), 500

@app.route('/api/status')
def api_status():
    """获取应用状态"""
    try:
        # 检查数据库连接
        conn = sqlite3.connect('instance/dplayer.db')
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM videos')
        video_count = cursor.fetchone()[0]
        cursor.execute('SELECT COUNT(*) FROM tags')
        tag_count = cursor.fetchone()[0]
        conn.close()

        return jsonify({
            'success': True,
            'status': 'running',
            'database': {
                'videos': video_count,
                'tags': tag_count
            },
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        logger.error(f"获取状态失败: {e}")
        return jsonify({
            'success': False,
            'message': str(e)
        }), 500

if __name__ == '__main__':
    import os
    
    # 检查是否在命令行直接运行
    check_direct_command_line_execution()

    # ========== Windows 服务模式支持 ==========
    # 确保在作为 Windows 服务运行时工作目录正确
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.getcwd() != script_dir:
        os.chdir(script_dir)
        logger.info(f"工作目录已设置为: {os.getcwd()}")

    # 检测是否在 Flask reloader 模式下运行
    # Werkzeug reloader 会设置 WERKZEUG_RUN_MAIN=true
    is_reloader = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    
    # 检测是否作为 Windows 服务运行
    is_service = 'windows_service' in os.environ.get('RUN_MODE', '').lower()
    
    # 重新加载配置（确保获取最新的端口配置）
    config = load_config()
    PORT = config.get('ports', {}).get('main_app', 80)

    # 只在非服务模式下检查端口
    if not is_service and not is_reloader:
        print(f'[*] 正在检查端口 {PORT}...')
        port_result = ensure_port_available(PORT, exclude_self=True)

        if port_result['action'] == 'killed':
            print(f'[!] {port_result["message"]}')
            time.sleep(1)  # 等待端口完全释放

        if is_port_in_use(PORT):
            # 再次检查时排除自己
            processes = find_process_using_port(PORT, exclude_self=True)
            if processes:
                print(f'[!] 错误: 端口 {PORT} 仍然被占用，无法启动应用')
                print(f'[!] 请手动检查并终止占用该端口的进程:')
                for proc in processes:
                    print(f'    - PID: {proc.pid}, Name: {proc.name()}')
                sys.exit(1)

    # 保存进程ID（使用绝对路径，确保 admin_app.py 能正确读取）
    pid_file = os.path.join(script_dir, 'instance', 'main_app.pid')
    os.makedirs(os.path.dirname(pid_file), exist_ok=True)
    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))

    print(f'[*] Starting Flask server on {HOST}:{PORT}')
    print(f'[*] Process ID: {os.getpid()}')
    if is_service:
        logger.info("以 Windows 服务模式运行")
    init_db()  # 初始化数据库
    
    # 创建用户表（如果不存在）
    with app.app_context():
        try:
            # 导入用户模型确保表被创建
            from core.models import User, UserSession
            db.create_all()
            
            # 初始化root用户
            init_root_user()
            
            logger.info("用户系统初始化完成")
        except Exception as e:
            logger.error(f"用户系统初始化失败: {e}")
    
    # 初始化缩略图服务
    print(f'[*] Initializing thumbnail service...')
    initialize_thumbnail_service()

    # 执行系统网络优化（防火墙、TCP、DNS等）
    # print(f'[*] 执行系统网络优化...')
    # try:
    #     optimize_system(
    #         ports=[PORT],
    #         service_names=['主应用']
    #     )
    # except Exception as e:
    #     print(f'[警告] 系统优化失败: {e}')

    
    # 启动缩略图预生成后台任务（只启动一次）
    if THUMBNAIL_FALLBACK_ENABLED:
        print(f'[*] Starting thumbnail pre-generation task...')
        threading.Thread(target=generate_missing_thumbnails_async, daemon=True).start()
        print('[*] 缩略图预生成后台任务已启动')

    # 使用 Waitress 生产服务器（多线程，局域网稳定，Windows 原生支持）
    # 比 Werkzeug 开发服务器更稳定，解决局域网偶发访问失败问题
    try:
        from waitress import serve
        print(f'[*] 使用 Waitress 生产服务器启动 (threads=8)')
        serve(app, host=HOST, port=PORT, threads=8,
              channel_timeout=120,       # 连接超时120秒
              cleanup_interval=30,       # 每30秒清理过期连接
              connection_limit=200)      # 最大200并发连接
    except ImportError:
        print('[警告] waitress 未安装，回退到 Werkzeug 开发服务器')
        print('[提示] 运行: pip install waitress  以获得更稳定的局域网访问')
        app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
