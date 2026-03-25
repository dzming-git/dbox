# 前端API适配层 - 统一API接口
from flask import Blueprint, request, jsonify, g
from core.models import db, Video, Tag, VideoTag
from liblog import get_module_logger
from functools import wraps
import os
from datetime import datetime
from werkzeug.utils import secure_filename

log = get_module_logger()

frontend_bp = Blueprint('frontend', __name__, url_prefix='/api')

# 允许的文件扩展名
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'flv', 'wmv'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# 文件夹配置
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads', 'videos')
THUMBNAIL_FOLDER = os.path.join(BASE_DIR, 'uploads', 'thumbnails')

# 确保文件夹存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(THUMBNAIL_FOLDER, exist_ok=True)

# 认证装饰器（简化版）
def frontend_auth_required(f):
    """前端API认证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 从请求头获取token
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({
                'success': False,
                'message': '未授权，请重新登录',
                'code': 401
            }), 401

        token = auth_header.split(' ')[1]

        # 验证token
        from backend.utils.jwt_authlib import verify_token
        payload = verify_token(token)

        if not payload or payload.get('type') != 'access':
            return jsonify({
                'success': False,
                'message': 'Token无效或已过期',
                'code': 401
            }), 401

        # 将用户信息存入g对象
        g.user_id = payload.get('user_id')
        g.role = payload.get('role')
        g.username = payload.get('username')

        return f(*args, **kwargs)
    return decorated_function


# Root权限检查装饰器
def frontend_root_required(f):
    """前端API Root权限检查装饰器（需要role >= 3）
    
    注意：此装饰器应该在 frontend_auth_required 之后使用，以确保 g.role 被正确设置
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 首先进行认证（从请求头获取token并验证）
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({
                'success': False,
                'message': '未授权，请重新登录',
                'code': 401
            }), 401

        token = auth_header.split(' ')[1]
        
        # 验证token并提取用户信息
        from backend.utils.jwt_authlib import verify_token
        payload = verify_token(token)
        
        if not payload or payload.get('type') != 'access':
            return jsonify({
                'success': False,
                'message': 'Token无效或已过期',
                'code': 401
            }), 401
        
        # 将用户信息存入g对象（确保后续检查能获取到）
        g.user_id = payload.get('user_id')
        g.role = payload.get('role')
        g.username = payload.get('username')

        # 检查权限（role >= 3 为 root）
        role = g.role
        if role is None or role < 3:
            return jsonify({
                'success': False,
                'message': '权限不足，只有root用户可访问此功能',
                'code': 403
            }), 403

        return f(*args, **kwargs)
    return decorated_function


# ========== 认证相关API ==========

@frontend_bp.route('/auth/check', methods=['GET'])
@frontend_auth_required
def check_auth():
    """检查认证状态"""
    from core.models import User

    try:
        user = User.query.get(g.user_id)
        if not user or not user.is_active:
            return jsonify({
                'authenticated': False,
                'user': None
            })

        return jsonify({
            'authenticated': True,
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role': user.role,
                'role_name': get_role_name(user.role)
            }
        })
    except Exception as e:
        log.debug('ERROR', f"检查认证状态失败: {e}", exc_info=True)
        return jsonify({
            'authenticated': False,
            'user': None
        })


# ========== 视频管理API ==========

@frontend_bp.route('/videos', methods=['GET'])
@frontend_auth_required
def get_videos():
    """获取视频列表"""
    try:
        videos = Video.query.order_by(Video.created_at.desc()).all()

        videos_list = []
        for video in videos:
            videos_list.append({
                'id': video.id,
                'title': video.title or '未命名视频',
                'path': video.local_path or '',
                'duration': format_duration(video.duration),
                'file_size': format_size(video.file_size),
                'created_at': video.created_at.isoformat() if video.created_at else None,
                'thumbnail_url': video.thumbnail or '',
                'description': video.description or '',
                'priority': video.priority or 0
            })

        return jsonify({
            'success': True,
            'videos': videos_list,
            'total': len(videos_list)
        })
    except Exception as e:
        log.debug('ERROR', f"获取视频列表失败: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'获取视频列表失败: {str(e)}',
            'videos': [],
            'total': 0
        }), 500


def allowed_file(filename, allowed_extensions):
    """检查文件扩展名是否允许"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


@frontend_bp.route('/videos/upload', methods=['POST'])
@frontend_auth_required
def upload_video():
    """上传视频"""
    try:
        # 检查是否有视频文件
        if 'video' not in request.files:
            return jsonify({
                'success': False,
                'message': '没有选择视频文件'
            }), 400

        video_file = request.files['video']
        if video_file.filename == '':
            return jsonify({
                'success': False,
                'message': '没有选择视频文件'
            }), 400

        if not allowed_file(video_file.filename, ALLOWED_VIDEO_EXTENSIONS):
            return jsonify({
                'success': False,
                'message': '不支持的文件格式'
            }), 400

        # 保存视频文件
        video_filename = secure_filename(video_file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        video_filename = f"{timestamp}_{video_filename}"
        video_path = os.path.join(UPLOAD_FOLDER, video_filename)
        video_file.save(video_path)

        # 处理缩略图
        thumbnail_url = None
        if 'thumbnail' in request.files:
            thumbnail_file = request.files['thumbnail']
            if thumbnail_file and allowed_file(thumbnail_file.filename, ALLOWED_IMAGE_EXTENSIONS):
                thumb_filename = secure_filename(thumbnail_file.filename)
                thumb_filename = f"{timestamp}_{thumb_filename}"
                thumb_path = os.path.join(THUMBNAIL_FOLDER, thumb_filename)
                thumbnail_file.save(thumb_path)
                thumbnail_url = f"/static/uploads/thumbnails/{thumb_filename}"

        # 获取其他表单数据
        title = request.form.get('title', video_filename)
        description = request.form.get('description', '')
        tags_str = request.form.get('tags', '')
        priority = int(request.form.get('priority', 0))

        # 获取文件信息
        file_size = os.path.getsize(video_path)

        # 创建视频记录
        video = Video(
            title=title,
            description=description,
            file_path=f"/uploads/videos/{video_filename}",
            file_size=file_size,
            thumbnail_url=thumbnail_url,
            priority=priority,
            created_at=datetime.utcnow()
        )
        db.session.add(video)
        db.session.flush()  # 获取video.id

        # 处理标签
        if tags_str:
            tag_names = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
            for tag_name in tag_names:
                tag = Tag.query.filter_by(name=tag_name).first()
                if not tag:
                    # 创建新标签
                    tag = Tag(
                        name=tag_name,
                        color=get_random_color(),
                        description=''
                    )
                    db.session.add(tag)
                    db.session.flush()

                # 关联视频和标签
                video_tag = VideoTag(video_id=video.id, tag_id=tag.id)
                db.session.add(video_tag)

        db.session.commit()

        log.runtime('INFO', f"视频上传成功: {title} (ID: {video.id})")

        return jsonify({
            'success': True,
            'message': '上传成功',
            'data': {
                'id': video.id,
                'title': video.title,
                'path': video.local_path,
                'thumbnail_url': video.thumbnail
            }
        })

    except Exception as e:
        log.debug('ERROR', f"视频上传失败: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'上传失败: {str(e)}'
        }), 500


@frontend_bp.route('/videos/<int:video_id>', methods=['DELETE'])
@frontend_auth_required
def delete_video(video_id):
    """删除视频"""
    try:
        video = Video.query.get(video_id)
        if not video:
            return jsonify({
                'success': False,
                'message': '视频不存在'
            }), 404

        # 删除数据库记录
        db.session.delete(video)
        db.session.commit()

        log.runtime('INFO', f"删除视频成功: {video.title} (ID: {video_id})")

        return jsonify({
            'success': True,
            'message': '删除成功'
        })
    except Exception as e:
        log.debug('ERROR', f"删除视频失败: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'删除失败: {str(e)}'
        }), 500


@frontend_bp.route('/videos/<int:video_id>', methods=['PUT', 'PATCH'])
@frontend_auth_required
def update_video(video_id):
    """更新视频信息"""
    try:
        video = Video.query.get(video_id)
        if not video:
            return jsonify({
                'success': False,
                'message': '视频不存在',
                'code': 404
            }), 404

        data = request.get_json()

        # 更新标题
        if 'title' in data and data['title']:
            video.title = data['title']

        # 更新描述
        if 'description' in data:
            video.description = data['description']

        # 更新优先级
        if 'priority' in data:
            video.priority = data['priority']

        # 更新标签（先删除旧标签关联，再添加新标签关联）
        if 'tags' in data:
            # 删除所有现有标签关联
            VideoTag.query.filter_by(video_id=video_id).delete()

            # 添加新标签关联
            if data['tags']:
                tag_names = [tag.strip() for tag in data['tags'].split(',') if tag.strip()]
                for tag_name in tag_names:
                    # 查找或创建标签
                    tag = Tag.query.filter_by(name=tag_name).first()
                    if not tag:
                        tag = Tag(name=tag_name)
                        db.session.add(tag)
                        db.session.flush()  # 获取tag.id

                    # 创建视频标签关联
                    video_tag = VideoTag(video_id=video_id, tag_id=tag.id)
                    db.session.add(video_tag)

        db.session.commit()
        log.runtime('INFO', f"更新视频成功: {video.title} (ID: {video_id})")

        return jsonify({
            'success': True,
            'message': '更新成功',
            'data': {
                'id': video.id,
                'title': video.title,
                'description': video.description,
                'priority': video.priority
            }
        })
    except Exception as e:
        log.debug('ERROR', f"更新视频失败: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'更新失败: {str(e)}',
            'code': 500
        }), 500


# ========== 标签管理API ==========

@frontend_bp.route('/tags', methods=['GET'])
@frontend_auth_required
def get_tags():
    """获取标签列表"""
    try:
        tags = Tag.query.order_by(Tag.name).all()

        tags_list = []
        for tag in tags:
            tags_list.append({
                'id': tag.id,
                'name': tag.name,
                'color': None,          # Tag 模型无 color 字段，前端按 category 着色
                'category': tag.category or '',
                'video_count': tag.video_count(),
            })

        return jsonify({
            'success': True,
            'tags': tags_list,
            'total': len(tags_list)
        })
    except Exception as e:
        log.debug('ERROR', f"获取标签列表失败: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'获取标签列表失败: {str(e)}',
            'tags': [],
            'total': 0
        }), 500


@frontend_bp.route('/tags', methods=['POST'])
@frontend_auth_required
def create_tag():
    """创建标签"""
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                'success': False,
                'message': '请求数据不能为空'
            }), 400

        name = data.get('name', '').strip()
        color = data.get('color', get_random_color())
        description = data.get('description', '')

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
                'message': '标签已存在'
            }), 400

        # 创建标签
        tag = Tag(
            name=name,
            color=color,
            description=description
        )
        db.session.add(tag)
        db.session.commit()

        log.runtime('INFO', f"创建标签成功: {name} (ID: {tag.id})")

        return jsonify({
            'success': True,
            'message': '创建成功',
            'data': {
                'id': tag.id,
                'name': tag.name,
                'color': tag.color,
                'description': tag.description,
                'count': 0
            }
        })

    except Exception as e:
        log.debug('ERROR', f"创建标签失败: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'创建失败: {str(e)}'
        }), 500


@frontend_bp.route('/tags/<int:tag_id>', methods=['PUT'])
@frontend_auth_required
def update_tag(tag_id):
    """更新标签"""
    try:
        tag = Tag.query.get(tag_id)
        if not tag:
            return jsonify({
                'success': False,
                'message': '标签不存在'
            }), 404

        data = request.get_json()

        if not data:
            return jsonify({
                'success': False,
                'message': '请求数据不能为空'
            }), 400

        # 更新字段
        if 'name' in data:
            name = data['name'].strip()
            if name and name != tag.name:
                # 检查新名称是否已存在
                existing_tag = Tag.query.filter_by(name=name).first()
                if existing_tag:
                    return jsonify({
                        'success': False,
                        'message': '标签名称已存在'
                    }), 400
                tag.name = name

        if 'color' in data:
            tag.color = data['color']

        if 'description' in data:
            tag.description = data['description']

        db.session.commit()

        log.runtime('INFO', f"更新标签成功: {tag.name} (ID: {tag_id})")

        # 计算视频数量
        video_count = db.session.query(Video).join(
            Video.tags
        ).filter(VideoTag.tag_id == tag_id).count()

        return jsonify({
            'success': True,
            'message': '更新成功',
            'data': {
                'id': tag.id,
                'name': tag.name,
                'color': tag.color,
                'description': tag.description,
                'count': video_count
            }
        })

    except Exception as e:
        log.debug('ERROR', f"更新标签失败: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'更新失败: {str(e)}'
        }), 500


@frontend_bp.route('/tags/<int:tag_id>', methods=['DELETE'])
@frontend_auth_required
def delete_tag(tag_id):
    """删除标签"""
    try:
        tag = Tag.query.get(tag_id)
        if not tag:
            return jsonify({
                'success': False,
                'message': '标签不存在'
            }), 404

        # 删除标签
        db.session.delete(tag)
        db.session.commit()

        log.runtime('INFO', f"删除标签成功: {tag.name} (ID: {tag_id})")

        return jsonify({
            'success': True,
            'message': '删除成功'
        })
    except Exception as e:
        log.debug('ERROR', f"删除标签失败: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'删除失败: {str(e)}'
        }), 500


# ========== 日志查看API ==========

@frontend_bp.route('/logs', methods=['GET'])
@frontend_root_required
def get_logs():
    """获取日志列表"""
    try:
        level = request.args.get('level', '').upper()
        limit = int(request.args.get('limit', 100))

        # 这里简化实现，实际应该从日志文件读取
        # 暂时返回示例数据
        logs = [
            {
                'timestamp': '2026-03-15 10:00:00',
                'level': 'INFO',
                'message': '系统启动成功'
            },
            {
                'timestamp': '2026-03-15 10:00:01',
                'level': 'INFO',
                'message': '数据库连接成功'
            }
        ]

        # 如果指定了级别，进行过滤
        if level:
            logs = [log for log in logs if log['level'] == level]

        return jsonify({
            'success': True,
            'logs': logs[:limit],
            'total': len(logs)
        })
    except Exception as e:
        log.debug('ERROR', f"获取日志列表失败: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'获取日志列表失败: {str(e)}',
            'logs': [],
            'total': 0
        }), 500


# ========== 服务管理API ==========

@frontend_bp.route('/services', methods=['GET'])
@frontend_root_required
def get_services():
    """获取服务列表"""
    try:
        from service_manager import get_all_services_status

        services_status = get_all_services_status()

        services_list = []
        for key, status in services_status.get('services', {}).items():
            services_list.append({
                'key': key,
                'name': status.get('name', key),
                'description': status.get('description', ''),
                'running': status.get('running', False),
                'pid': status.get('pid'),
                'port': status.get('port'),
                'cpu': status.get('cpu'),
                'memory': status.get('memory')
            })

        return jsonify({
            'success': True,
            'services': services_list
        })
    except Exception as e:
        log.debug('ERROR', f"获取服务列表失败: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'获取服务列表失败: {str(e)}',
            'services': []
        }), 500


@frontend_bp.route('/services/<service_key>/start', methods=['POST'])
@frontend_root_required
def start_service(service_key):
    """启动服务"""
    try:
        from service_manager import start_service

        result = start_service(service_key)

        if result.get('success'):
            return jsonify({
                'success': True,
                'message': f'服务 {service_key} 启动成功'
            })
        else:
            return jsonify({
                'success': False,
                'message': result.get('message', f'启动服务失败')
            }), 500
    except Exception as e:
        log.debug('ERROR', f"启动服务失败: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'启动服务失败: {str(e)}'
        }), 500


@frontend_bp.route('/services/<service_key>/stop', methods=['POST'])
@frontend_root_required
def stop_service(service_key):
    """停止服务"""
    try:
        from service_manager import stop_service

        result = stop_service(service_key)

        if result.get('success'):
            return jsonify({
                'success': True,
                'message': f'服务 {service_key} 停止成功'
            })
        else:
            return jsonify({
                'success': False,
                'message': result.get('message', f'停止服务失败')
            }), 500
    except Exception as e:
        log.debug('ERROR', f"停止服务失败: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'停止服务失败: {str(e)}'
        }), 500


@frontend_bp.route('/services/<service_key>/restart', methods=['POST'])
@frontend_root_required
def restart_service(service_key):
    """重启服务"""
    try:
        from service_manager import restart_service

        result = restart_service(service_key)

        if result.get('success'):
            return jsonify({
                'success': True,
                'message': f'服务 {service_key} 重启成功'
            })
        else:
            return jsonify({
                'success': False,
                'message': result.get('message', f'重启服务失败')
            }), 500
    except Exception as e:
        log.debug('ERROR', f"重启服务失败: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'重启服务失败: {str(e)}'
        }), 500


# ========== 辅助函数 ==========

def format_duration(seconds):
    """格式化时长"""
    if not seconds:
        return '0:00'
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f'{minutes}:{secs:02d}'


def format_size(bytes_size):
    """格式化文件大小"""
    if not bytes_size:
        return '0 B'
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f'{bytes_size:.2f} {unit}'
        bytes_size /= 1024.0
    return f'{bytes_size:.2f} TB'


def get_role_name(role: int) -> str:
    """获取角色名称"""
    role_names = {
        0: '访客',
        1: '普通用户',
        2: '管理员',
        3: '超级管理员'
    }
    return role_names.get(role, '未知')


def get_random_color():
    """生成随机颜色"""
    import random
    colors = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399', '#8e44ad', '#3498db', '#1abc9c', '#e74c3c', '#f39c12']
    return random.choice(colors)


# ========== 系统状态API ==========

@frontend_bp.route('/system/status', methods=['GET'])
@frontend_root_required
def get_system_status():
    """获取系统状态"""
    try:
        import psutil
        import platform
        from datetime import datetime

        # CPU信息
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count(logical=True)
        cpu_count_physical = psutil.cpu_count(logical=False)

        # 内存信息
        mem = psutil.virtual_memory()
        mem_total = mem.total
        mem_used = mem.used
        mem_percent = mem.percent

        # 磁盘信息
        disk = psutil.disk_usage('/')
        disk_total = disk.total
        disk_used = disk.used
        disk_percent = disk.percent

        # 网络信息
        net_io = psutil.net_io_counters()
        net_sent = net_io.bytes_sent
        net_recv = net_io.bytes_recv

        # 系统信息
        system_info = {
            'platform': platform.system(),
            'platform_release': platform.release(),
            'platform_version': platform.version(),
            'architecture': platform.machine(),
            'hostname': platform.node(),
            'python_version': platform.python_version()
        }

        return jsonify({
            'success': True,
            'data': {
                'cpu': {
                    'percent': cpu_percent,
                    'count_logical': cpu_count,
                    'count_physical': cpu_count_physical
                },
                'memory': {
                    'total': disk_total,  # 使用format_size格式化
                    'used': disk_used,
                    'percent': mem_percent
                },
                'disk': {
                    'total': disk_total,
                    'used': disk_used,
                    'percent': disk_percent
                },
                'network': {
                    'bytes_sent': net_sent,
                    'bytes_recv': net_recv
                },
                'system': system_info,
                'timestamp': datetime.now().isoformat()
            }
        })
    except Exception as e:
        log.debug('ERROR', f"获取系统状态失败: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'获取系统状态失败: {str(e)}'
        }), 500


@frontend_bp.route('/system/stats', methods=['GET'])
@frontend_root_required
def get_system_stats():
    """获取系统统计信息（数据库、视频数量等）"""
    try:
        from core.models import Video, User, Tag

        # 统计信息
        video_count = Video.query.count()
        user_count = User.query.count()
        tag_count = Tag.query.count()

        # 计算总视频大小
        total_size = 0
        videos = Video.query.all()
        for video in videos:
            import os
            if video.local_path and os.path.exists(video.local_path):
                try:
                    total_size += os.path.getsize(video.local_path)
                except:
                    pass

        # 数据库大小
        db_size = 0
        db_path = 'instance/dplayer.db'
        if os.path.exists(db_path):
            db_size = os.path.getsize(db_path)

        return jsonify({
            'success': True,
            'data': {
                'videos': {
                    'total': video_count,
                    'total_size': total_size
                },
                'users': {
                    'total': user_count
                },
                'tags': {
                    'total': tag_count
                },
                'database': {
                    'size': db_size
                }
            }
        })
    except Exception as e:
        log.debug('ERROR', f"获取系统统计信息失败: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'获取系统统计信息失败: {str(e)}'
        }), 500


def get_random_color():
    """生成随机颜色"""
    import random
    colors = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399',
              '#8e44ad', '#3498db', '#1abc9c', '#e74c3c', '#f39c12']
    return random.choice(colors)
