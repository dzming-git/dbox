"""Auto-split blueprint: serve_api (moved from main.py)."""
from urllib.parse import quote, unquote
from core.models import Video
from core.models import ResourceIndex
from backend.access import guard_location
from datetime import datetime, timedelta
from backend.runtime import runtime
import os
from flask import Blueprint, request, jsonify, send_file, send_from_directory, session, g, abort, Response, current_app
from werkzeug.exceptions import HTTPException
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

        # 权限收敛：一律回源资源索引校验所属资源库是否激活。
        # 原先「路径落在扫描目录内即放行」的白名单会绕过资源库管控，
        # 使未激活资源库的视频仍可被直接串流，故不再作为放行依据。
        guard_location(video_path)

        if not os.path.exists(video_path):
            # 不区分「文件缺失」与「无权访问」，统一按不存在处理
            abort(404)
        return send_file(video_path, mimetype='video/mp4')
    except HTTPException:
        # abort(404) 抛出的是 HTTPException，不能被下面的兜底吞成 500，
        # 否则「无权访问」与「服务异常」状态码不同，可被用于探测资源存在性。
        raise
    except Exception as e:
        log.debug('ERROR', f"[serve_local_video] 错误: {str(e)}, 路径: {video_path if 'video_path' in dir() else 'unknown'}")
        abort(404)

@bp.route('/health')
def health():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})
