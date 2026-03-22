"""
DPlayer - 开发模式启动脚本
绕过服务守卫，用于开发和测试
"""
import os
import sys

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# 添加模块路径
for p in [PROJECT_ROOT,
          os.path.join(PROJECT_ROOT, 'msas-web'),
          os.path.join(PROJECT_ROOT, 'msas-thumb'),
          os.path.join(PROJECT_ROOT, 'libs'),
          os.path.join(PROJECT_ROOT, 'services')]:
    if p not in sys.path:
        sys.path.insert(0, p)

print(f"[DEV] Starting web.py in development mode...")
print(f"[DEV] PROJECT_ROOT: {PROJECT_ROOT}")

# 设置环境变量标记为开发模式
os.environ['DPLAYER_DEV_MODE'] = '1'
os.environ['DPLAYER_SKIP_GUARD'] = '1'

# 导入并运行 web.py 的内容（跳过守卫检查）
from flask import Flask, jsonify, request, send_file, abort, Response, g, session
from flask_cors import CORS
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from urllib.parse import quote, unquote
import json
import logging
import logging.handlers
import threading
import time
import hashlib
import random
import re
from functools import wraps

# 导入核心模块
from core.models import db, Video, Tag, VideoTag, UserInteraction, UserPreference, User, UserSession, UserRole, ROLE_NAMES
from auth_service import AuthService, init_root_user

# 导入API蓝图
from api.auth_api import auth_bp
from api.playlist_api import playlist_bp
from api.system_api import system_bp

# 导入配置
from config import path_config

print("[DEBUG] web.py loading from:", os.path.abspath(__file__))
print("[DEBUG] PROJECT_ROOT:", PROJECT_ROOT)

# 创建Flask应用
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# 从环境变量读取数据库路径，默认使用项目目录下的 dev_runtime
runtime_dir = os.environ.get('DPLAYER_RUNTIME_DIR', os.path.join(PROJECT_ROOT, 'dev_runtime'))
os.makedirs(runtime_dir, exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(runtime_dir, 'dplayer.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# 启用CORS
CORS(app, supports_credentials=True, resources={
    r"/api/*": {
        "origins": ["http://localhost:5173", "http://127.0.0.1:5173", "http://0.0.0.0:5173"],
        "supports_credentials": True
    }
})

# 设置日志
log_dir = os.path.join(runtime_dir, 'logs')
os.makedirs(log_dir, exist_ok=True)

file_handler = logging.handlers.RotatingFileHandler(
    os.path.join(log_dir, 'web.log'),
    maxBytes=10*1024*1024,
    backupCount=5,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s'
))

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s'
))

app.logger.addHandler(file_handler)
app.logger.addHandler(console_handler)
app.logger.setLevel(logging.INFO)

# 初始化数据库
db.init_app(app)

# ============ 注册蓝图 ============
print("[DEBUG] Registering blueprints...")
app.register_blueprint(auth_bp)
app.register_blueprint(playlist_bp)
app.register_blueprint(system_bp)

# ============ 全局错误处理 ============
@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return jsonify({'success': False, 'error': 'Internal server error'}), 500

# ============ 启动服务 ============
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        init_root_user()
    
    print("[DEV] DPlayer Web Service starting on http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
