"""Auto-split blueprint: serve_api (moved from main.py)."""
from urllib.parse import quote, unquote
from core.models import Video
from core.models import ResourceIndex
from datetime import datetime, timedelta
from backend.runtime import runtime
import os
from flask import Blueprint, request, jsonify, send_file, send_from_directory, session, g, abort, Response, current_app
from liblog import get_service_logger
log = get_service_logger('dbox-web')

bp = Blueprint('serve_api', __name__)

@bp.route('/local_video/<path:video_path>')
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
        scan_dirs = [cfg['path'].replace('\\', '/') for cfg in runtime.app_config.get('scan_directories', [])]

        # 白名单检查：1. 扫描目录 2. 数据库中已有视频的 local_path（精确匹配，绝不用文件名）
        allowed = any(video_path.startswith(d.replace('/', os.sep)) for d in scan_dirs)

        # 如果不在扫描目录，检查是否在数据库中（基于完整 local_path 精确匹配，文件名不作为身份）
        if not allowed:
            existing_video = Video.query.join(ResourceIndex).filter(
                ResourceIndex.location == video_path).first()
            if not existing_video:
                # 兜底：统一分隔符与大小写后比较，仍基于完整路径而非文件名
                norm_req = os.path.normcase(os.path.abspath(video_path))
                for ev in Video.query.join(ResourceIndex).filter(
                        ResourceIndex.location.isnot(None)).all():
                    if os.path.normcase(os.path.abspath(ev.local_path)) == norm_req:
                        existing_video = ev
                        break
            if existing_video:
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

@bp.route('/health')
def health():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})
