"""Auto-split blueprint: library_api (moved from main.py)."""
from backend.paths import DATA_DIR
from backend.library_helpers import _restart_library_watchers
from core.models import LibraryUserGroupMember
from backend.library_helpers import _INVALID_NAME_RE
from backend.library_helpers import _library_scan_progress
import threading
from backend.trash import get_trash_list
from backend.access import resolve_identity
from core.models import VideoTag
from core.models import LibraryAuditLog
from backend.trash import get_trash_obj
from core.models import Tag
from urllib.parse import quote, unquote
from core.models import Gallery
from backend.audit import log_operation
from core.models import Text
from backend.library_helpers import _library_scan_all_progress
from core.models import Post, PostRef
from core.models import User
from core.models import ResourceLibrary
from core.models import LibraryPermission
from core.models import ResourceIndex
from backend.access import _user_library_admin_ids
from core.models import LibraryUserGroup
from core.models import db
import os
from backend.library_helpers import _list_system_drives
from backend.trash import restore_from_trash
from core.models import Video
from core.models import UserRole
import random
import re
from datetime import datetime, timedelta
from backend.trash import purge_trash
from backend.runtime import runtime
from backend.helpers import _resolve_resource_library_id, _ensure_resource_library
from backend.access import admin_required, library_admin_required, library_write_required, resource_manager_required, get_allowed_library_ids
from flask import Blueprint, request, jsonify, send_file, send_from_directory, session, g, abort, Response, current_app
from liblog import get_service_logger
log = get_service_logger('dbox-web')

bp = Blueprint('library_api', __name__)

@bp.route('/api/admin/libraries', methods=['GET'])
@admin_required
def get_libraries():
    """获取所有资源库列表"""
    try:
        libraries = ResourceLibrary.query.order_by(ResourceLibrary.created_at.desc()).all()
        result = []
        for lib in libraries:
            lib_dict = lib.to_dict(include_stats=True)
            try:
                lib_dict['video_count'] = Video.query.filter_by(library_id=lib.id).count()
                lib_dict['gallery_count'] = Gallery.query.filter_by(library_id=lib.id).count()
                lib_dict['post_count'] = Post.query.join(
                    PostRef, PostRef.post_id == Post.id
                ).join(
                    ResourceIndex, ResourceIndex.id == PostRef.resource_index_id
                ).filter(ResourceIndex.library_id == lib.id).distinct(Post.id).count()
                lib_dict['text_count'] = Text.query.join(
                    ResourceIndex, ResourceIndex.id == Text.resource_index_id
                ).filter(ResourceIndex.library_id == lib.id).count()
            except Exception:
                lib_dict.setdefault('video_count', 0)
                lib_dict.setdefault('gallery_count', 0)
                lib_dict.setdefault('post_count', 0)
                lib_dict.setdefault('text_count', 0)
            result.append(lib_dict)
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        log.debug('ERROR', f"获取资源库列表失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/my-libraries', methods=['GET'])
def get_my_libraries():
    """获取当前用户可管理的资源库。

    全局管理员返回全部；资源库管理员（LibraryPermission.role='admin'）返回其管理的资源库。
    用于前端在「非全局管理员」场景下展示可管理的资源库。
    """
    try:
        user_id, role = resolve_identity()
        if not user_id:
            return jsonify({'success': False, 'message': '未授权', 'code': 401}), 401
        if role >= UserRole.ADMIN:
            libs = ResourceLibrary.query.order_by(ResourceLibrary.created_at.desc()).all()
        else:
            admin_ids = _user_library_admin_ids(user_id)
            if not admin_ids:
                return jsonify({'success': True, 'data': []})
            libs = ResourceLibrary.query.filter(ResourceLibrary.id.in_(admin_ids)).all()
        result = []
        for lib in libs:
            lib_dict = lib.to_dict(include_stats=True)
            try:
                lib_dict['video_count'] = Video.query.filter_by(library_id=lib.id).count()
                lib_dict['gallery_count'] = Gallery.query.filter_by(library_id=lib.id).count()
                lib_dict['post_count'] = Post.query.join(
                    PostRef, PostRef.post_id == Post.id
                ).join(
                    ResourceIndex, ResourceIndex.id == PostRef.resource_index_id
                ).filter(ResourceIndex.library_id == lib.id).distinct(Post.id).count()
                lib_dict['text_count'] = Text.query.join(
                    ResourceIndex, ResourceIndex.id == Text.resource_index_id
                ).filter(ResourceIndex.library_id == lib.id).count()
            except Exception:
                lib_dict.setdefault('video_count', 0)
                lib_dict.setdefault('gallery_count', 0)
                lib_dict.setdefault('post_count', 0)
                lib_dict.setdefault('text_count', 0)
            result.append(lib_dict)
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        log.debug('ERROR', f"获取我的资源库失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/libraries', methods=['POST'])
@admin_required
def create_library():
    """创建新资源库"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()

        # 自动生成数据库文件名：直接使用库名
        import re
        if not name:
            return jsonify({'success': False, 'message': '请输入资源库名称'}), 400

        # 检查名称是否重复
        if ResourceLibrary.query.filter_by(name=name).first():
            return jsonify({'success': False, 'message': '资源库名称已存在'}), 400

        # 直接使用库名作为数据库文件名（保留中文、英文、数字、下划线）
        safe_name = re.sub(r'[^\w\u4e00-\u9fff]', '_', name)  # 保留中文、字母、数字、下划线
        db_file = f"{safe_name}.db"

        # 确保文件名唯一（如果已存在则追加序号）
        base_db_file = db_file
        counter = 1
        while ResourceLibrary.query.filter_by(db_file=db_file).first():
            db_file = f"{base_db_file.rstrip('.db')}_{counter}.db"
            counter += 1

        # 创建资源库
        library = ResourceLibrary(
            name=name,
            description=description,
            db_path='libraries',
            db_file=db_file,
            is_active=True,
            config=data.get('config', {})
        )

        # 创建数据库文件（从模板复制或创建空数据库）
        db_full_path = library.full_db_path
        # 确保数据库文件所在目录存在（基于实际绝对路径，而非相对 db_path）
        db_dir = os.path.dirname(db_full_path)
        os.makedirs(db_dir, exist_ok=True)
        if not os.path.exists(db_full_path):
            # 从现有数据库复制结构
            import shutil
            template_db = os.path.join(DATA_DIR, 'databases', 'dbox.db')
            if os.path.exists(template_db):
                shutil.copy2(template_db, db_full_path)
            else:
                # 创建空数据库
                db.create_all()

        db.session.add(library)
        db.session.commit()
        log_operation('create library', target=name, success=True)

        # 同步创建 resource.db 中的资源库（供 resourced 服务使用）
        if runtime.resource_bus:
            try:
                # 库路径默认为空，用户可以后续添加文件夹
                default_path = data.get('path', '')
                result = runtime.resource_bus.call_method(
                    'com.dbox.resourced',
                    'com.dbox.Resourced',
                    'AddLibrary',
                    {
                        'name': name,
                        'path': default_path,
                        'resource_type': 'video',
                        'scan_mode': 'manual'
                    },
                    timeout=5000
                )
                if result and result.get('success'):
                    log.debug('INFO', f'已同步创建 resource.db 资源库: {name} (ID: {result.get("library_id")})')
                else:
                    error = result.get('error') if result else '无响应'
                    log.debug('WARN', f'同步创建 resource.db 资源库失败: {name}, {error}')
            except Exception as sync_e:
                log.debug('WARN', f'同步创建 resource.db 资源库异常: {sync_e}')

        return jsonify({'success': True, 'data': library.to_dict()})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"创建资源库失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/libraries/<int:library_id>', methods=['GET'])
@admin_required
def get_library(library_id):
    """获取资源库详情"""
    try:
        library = ResourceLibrary.query.get_or_404(library_id)
        lib_dict = library.to_dict(include_stats=True)
        return jsonify({'success': True, 'data': lib_dict})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/libraries/<int:library_id>', methods=['PUT'])
@admin_required
def update_library(library_id):
    """更新资源库配置"""
    try:
        library = ResourceLibrary.query.get_or_404(library_id)
        data = request.get_json()
        import re

        if 'name' in data:
            # 检查名称重复
            new_name = data['name'].strip()
            existing = ResourceLibrary.query.filter(ResourceLibrary.name == new_name, ResourceLibrary.id != library_id).first()
            if existing:
                return jsonify({'success': False, 'message': '资源库名称已存在'}), 400

            old_name = library.name
            library.name = new_name

            # 如果库名改变了，同步修改数据库文件名
            if old_name != new_name:
                old_db_file = library.db_file
                safe_name = re.sub(r'[^\w\u4e00-\u9fff]', '_', new_name)
                new_db_file = f"{safe_name}.db"

                # 确保新文件名不冲突
                while ResourceLibrary.query.filter(ResourceLibrary.db_file == new_db_file, ResourceLibrary.id != library_id).first():
                    new_db_file = f"{safe_name}_{random.randint(1,999)}.db"

                # 重命名数据库文件
                old_path = library.full_db_path
                library.db_file = new_db_file
                new_path = library.full_db_path

                # 执行文件重命名
                if os.path.exists(old_path) and old_path != new_path:
                    os.rename(old_path, new_path)
                    log.debug('INFO', f'重命名数据库文件: {old_db_file} -> {new_db_file}')

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
        log.debug('ERROR', f'更新资源库失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/libraries/<int:library_id>', methods=['DELETE'])
@admin_required
def delete_library(library_id):
    """删除资源库"""
    try:
        library = ResourceLibrary.query.get_or_404(library_id)

        # 可选：删除数据库文件
        # db_file = library.full_db_path
        # if os.path.exists(db_file):
        #     os.remove(db_file)

        db.session.delete(library)
        db.session.commit()
        log_operation('delete library', target=f'{library.name}(id={library_id})', success=True)
        return jsonify({'success': True, 'message': '资源库已删除'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/libraries/<int:library_id>/folders', methods=['GET'])
@library_admin_required('library_id')
def get_library_folders(library_id):
    """获取资源库的所有文件夹"""
    try:
        if not runtime.resource_bus:
            return jsonify({'success': False, 'message': '资源服务未连接'}), 500

        # 使用 resource.db 中的库 ID（可能与 dbox.db 的 ID 不同）
        res_lib_id = _resolve_resource_library_id(library_id)

        result = runtime.resource_bus.call_method(
            'com.dbox.resourced',
            'com.dbox.Resourced',
            'ListFolders',
            {'library_id': res_lib_id},
            timeout=3000
        )
        if result is None:
            return jsonify({'success': False, 'message': '资源服务无响应'}), 500
        if result.get('success'):
            return jsonify({'success': True, 'data': result.get('folders', [])})
        return jsonify({'success': False, 'message': result.get('error', '获取文件夹列表失败')}), 500
    except Exception as e:
        log.debug('ERROR', f'获取文件夹列表失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/test/add-folder', methods=['POST'])
def test_add_folder():
    """测试添加文件夹"""
    try:
        data = request.get_json()
        log.debug('INFO', f'Test add folder: {data}')
        if not runtime.resource_bus:
            return jsonify({'success': False, 'message': '资源服务未连接'}), 500

        result = runtime.resource_bus.call_method(
            'com.dbox.resourced',
            'com.dbox.Resourced',
            'AddFolder',
            data,
            timeout=5000
        )
        log.debug('INFO', f'AddFolder result: {result}')
        if result is None:
            return jsonify({'success': False, 'message': '资源服务无响应'}), 500
        if result.get('success'):
            return jsonify({'success': True, 'data': result.get('folder')})
        return jsonify({'success': False, 'message': result.get('error', '添加文件夹失败')}), 500
    except Exception as e:
        log.debug('ERROR', f'添加文件夹失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/libraries/<int:library_id>/folders', methods=['POST'])
@library_write_required('library_id')
def add_library_folder(library_id):
    """添加文件夹到资源库"""
    try:
        if not runtime.resource_bus:
            return jsonify({'success': False, 'message': '资源服务未连接'}), 500

        data = request.get_json()
        name = data.get('name', '').strip()
        path = data.get('path', '').strip()
        path_type = data.get('path_type', 'folder')
        is_default = data.get('is_default', False)

        if not path:
            return jsonify({'success': False, 'message': '路径不能为空'}), 400

        # 确保该资源库已在 resourced 中注册（缺失时自动注册，避免「库不存在」）
        _ensure_resource_library(library_id, fallback_path=path)

        # 使用 resource.db 中的库 ID（可能与 dbox.db 的 ID 不同）
        res_lib_id = _resolve_resource_library_id(library_id)

        result = runtime.resource_bus.call_method(
            'com.dbox.resourced',
            'com.dbox.Resourced',
            'AddFolder',
            {
                'library_id': res_lib_id,
                'name': name,
                'path': path,
                'path_type': path_type,
                'is_default': is_default
            },
            timeout=3000
        )
        if result is None:
            return jsonify({'success': False, 'message': '资源服务无响应'}), 500
        if result.get('success'):
            # 新文件夹加入后重启监控，使其立即纳入自动感知
            _restart_library_watchers()
            return jsonify({'success': True, 'data': result.get('folder')})
        return jsonify({'success': False, 'message': result.get('error', '添加文件夹失败')}), 500
    except Exception as e:
        log.debug('ERROR', f'添加文件夹失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/folders/<int:folder_id>', methods=['PUT'])
@library_write_required('folder_id')
def update_folder(folder_id):
    """更新文件夹"""
    try:
        if not runtime.resource_bus:
            return jsonify({'success': False, 'message': '资源服务未连接'}), 500

        data = request.get_json()

        result = runtime.resource_bus.call_method(
            'com.dbox.resourced',
            'com.dbox.Resourced',
            'UpdateFolder',
            {'folder_id': folder_id, **data},
            timeout=3000
        )
        if result is None:
            return jsonify({'success': False, 'message': '资源服务无响应'}), 500
        if result.get('success'):
            return jsonify({'success': True, 'data': result.get('folder')})
        return jsonify({'success': False, 'message': result.get('error', '更新文件夹失败')}), 500
    except Exception as e:
        log.debug('ERROR', f'更新文件夹失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/folders/<int:folder_id>', methods=['DELETE'])
@library_write_required('folder_id')
def delete_folder(folder_id):
    """删除文件夹"""
    try:
        if not runtime.resource_bus:
            return jsonify({'success': False, 'message': '资源服务未连接'}), 500

        result = runtime.resource_bus.call_method(
            'com.dbox.resourced',
            'com.dbox.Resourced',
            'RemoveFolder',
            {'folder_id': folder_id},
            timeout=3000
        )
        if result is None:
            return jsonify({'success': False, 'message': '资源服务无响应'}), 500
        if result.get('success'):
            return jsonify({'success': True, 'message': '文件夹已删除'})
        return jsonify({'success': False, 'message': result.get('error', '删除文件夹失败')}), 500
    except Exception as e:
        log.debug('ERROR', f'删除文件夹失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/folders/<int:folder_id>/set-default', methods=['POST'])
@library_write_required('folder_id')
def set_default_folder(folder_id):
    """设置文件夹为默认上传路径"""
    try:
        if not runtime.resource_bus:
            return jsonify({'success': False, 'message': '资源服务未连接'}), 500

        result = runtime.resource_bus.call_method(
            'com.dbox.resourced',
            'com.dbox.Resourced',
            'SetDefaultFolder',
            {'folder_id': folder_id},
            timeout=3000
        )
        if result is None:
            return jsonify({'success': False, 'message': '资源服务无响应'}), 500
        if result.get('success'):
            return jsonify({'success': True, 'data': result.get('folder')})
        return jsonify({'success': False, 'message': result.get('error', '设置默认路径失败')}), 500
    except Exception as e:
        log.debug('ERROR', f'设置默认路径失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/system/folders', methods=['GET'])
@resource_manager_required
def list_system_folders():
    """浏览服务器文件系统：返回指定路径下的子目录（及可选文件）。path 为空时返回盘符。"""
    try:
        path = (request.args.get('path', '') or '').strip()
        include_files = request.args.get('files', '0') == '1'
        folders = []
        files = []
        if not path:
            for d in _list_system_drives():
                folders.append({'name': d, 'path': d, 'display': d, 'type': 'drive'})
        else:
            if not os.path.isdir(path):
                return jsonify({'success': False, 'message': f'路径不存在或不是目录：{path}'}), 400
            try:
                entries = sorted(os.listdir(path))
            except PermissionError:
                return jsonify({'success': False, 'message': f'无权限访问：{path}'}), 403
            for name in entries:
                full = os.path.join(path, name)
                try:
                    if os.path.isdir(full):
                        folders.append({'name': name, 'path': full, 'display': name, 'type': 'folder'})
                    elif include_files and os.path.isfile(full):
                        files.append({'name': name, 'path': full, 'display': name, 'type': 'file'})
                except OSError:
                    continue
        return jsonify({'success': True, 'path': path, 'folders': folders, 'files': files})
    except Exception as e:
        log.debug('ERROR', f'浏览文件夹失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/system/folders', methods=['POST'])
@resource_manager_required
def create_system_folder():
    """在指定路径下新建文件夹。body: { path, name }"""
    try:
        data = request.get_json() or {}
        base = (data.get('path', '') or '').strip()
        name = (data.get('name', '') or '').strip()
        if not name:
            return jsonify({'success': False, 'message': '文件夹名称不能为空'}), 400
        if name in ('.', '..') or _INVALID_NAME_RE.search(name):
            return jsonify({'success': False, 'message': '文件夹名称包含非法字符'}), 400
        if base and not os.path.isdir(base):
            return jsonify({'success': False, 'message': f'父路径不存在：{base}'}), 400
        new_path = os.path.join(base, name) if base else os.path.join(os.getcwd(), name)
        os.makedirs(new_path, exist_ok=False)
        return jsonify({'success': True, 'folder': {'name': name, 'path': new_path, 'display': name, 'type': 'folder'}})
    except FileExistsError:
        return jsonify({'success': False, 'message': f'文件夹已存在：{name}'}), 400
    except Exception as e:
        log.debug('ERROR', f'创建文件夹失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/libraries/<int:library_id>/scan', methods=['POST'])
@library_admin_required('library_id')
def scan_library(library_id):
    """启动资源库扫描（异步，立即返回）。

    统一索引源：扫描直接驱动 web 的 Video 表（由 library_watcher 维护），
    不再依赖 resourced 的 ResourceItem（已于 2026-07-12 废弃，双索引问题根因）。
    """
    try:
        if not runtime.resource_bus:
            return jsonify({'success': False, 'message': '资源服务未连接'}), 500

        from library_watcher import get_watcher
        watcher = get_watcher()
        if not watcher:
            return jsonify({'success': False, 'message': '资源库监控器未初始化'}), 500

        # 防止重复扫描
        if _library_scan_progress.get(library_id, {}).get('status') == 'scanning':
            return jsonify({'success': False, 'message': '扫描已在进行中，请稍候...'}), 400

        _library_scan_progress[library_id] = {
            'status': 'scanning', 'current': 0, 'total': 0, 'message': '扫描中...'
        }

        def _run():
            try:
                # 后台线程无请求上下文，需显式进入 Flask 习作上下文
                with current_app.app_context():
                    targets = watcher.scan_library(library_id)
                _library_scan_progress[library_id] = {
                    'status': 'done',
                    'targets': targets,
                    'message': f'扫描完成，已同步 {targets} 个目录到 Video 索引',
                }
                print(f"[web] library {library_id} scan done, targets={targets}", flush=True)
            except Exception as e:
                _library_scan_progress[library_id] = {
                    'status': 'error', 'error': str(e), 'message': f'扫描失败: {e}'
                }
                print(f"[web] library {library_id} scan failed: {e}", flush=True)

        threading.Thread(target=_run, daemon=True).start()
        return jsonify({'success': True, 'started': True, 'message': '扫描已启动'})
    except Exception as e:
        log.debug('ERROR', f'启动扫描失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/libraries/<int:library_id>/scan-status', methods=['GET'])
@library_admin_required('library_id')
def get_library_scan_status(library_id):
    """获取资源库扫描进度（轮询接口，web 侧驱动 Video 索引）"""
    try:
        prog = _library_scan_progress.get(library_id)
        if not prog:
            return jsonify({'success': True, 'status': 'idle',
                            'message': '没有进行中的扫描'})
        return jsonify({'success': True, **prog})
    except Exception as e:
        log.debug('ERROR', f'获取扫描状态失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/libraries/scan-all', methods=['POST'])
@admin_required
def scan_all_libraries():
    """一键同步所有（启用中的）资源库（异步，立即返回）。

    底层复用 library_watcher 的增量/全量 diff：新增/删除/重命名/文件名对齐
    均会自动同步到 Video 表，覆盖「软件未运行时改名」「旧逻辑漏更新」
    等导致网页仍显示旧文件名的情况。

    mode（请求体，默认 'incremental'）：
      'incremental' —— 仅处理自上次扫描以来变化的目录，最快，日常首选
      'verify'      —— 仅清理磁盘已不存在的孤儿记录，不枚举新增文件
      'full'       —— 全量枚举磁盘并 diff（慢，仅数据严重不一致的小库使用）
    """
    global _library_scan_all_progress
    try:
        data = request.get_json(silent=True) or {}
        mode = data.get('mode', 'incremental')
        if mode not in ('incremental', 'verify', 'full'):
            mode = 'incremental'
        from library_watcher import get_watcher
        watcher = get_watcher()
        if not watcher:
            return jsonify({'success': False, 'message': '资源库监控器未初始化'}), 500
        if _library_scan_all_progress.get('status') == 'scanning':
            return jsonify({'success': False, 'message': '同步已在进行中，请稍候...'}), 400

        _library_scan_all_progress = {
            'status': 'scanning', 'total': 0, 'done': 0, 'mode': mode,
            'message': f'正在同步所有资源库（{mode}）...'
        }
        mode_label = {'incremental': '增量同步', 'verify': '校验清理', 'full': '全量重建'}[mode]

        def _run_all():
            global _library_scan_all_progress
            try:
                from core.models import ResourceLibrary
                # 后台线程无请求上下文，使用全局 runtime.app 的应用上下文
                # （不能用 current_app：请求已返回，后台线程中无法解析）
                with runtime.app.app_context():
                    libs = ResourceLibrary.query.filter_by(is_active=True).all()
                    _library_scan_all_progress['total'] = len(libs)
                    for i, lib in enumerate(libs, 1):
                        try:
                            watcher.scan_library(lib.id, mode=mode)
                        except Exception as e:
                            log.debug('ERROR', f'扫描库 {lib.id} 失败: {e}')
                        _library_scan_all_progress['done'] = i
                        _library_scan_all_progress['message'] = f'已同步 {i}/{len(libs)} 个资源库'
                    _library_scan_all_progress['status'] = 'done'
                    _library_scan_all_progress['message'] = f'{mode_label}完成，共处理 {len(libs)} 个资源库'
                    print('[web] scan-all done', flush=True)
            except Exception as e:
                _library_scan_all_progress['status'] = 'error'
                _library_scan_all_progress['error'] = str(e)
                _library_scan_all_progress['message'] = f'同步失败: {e}'
                print(f'[web] scan-all failed: {e}', flush=True)

        threading.Thread(target=_run_all, daemon=True).start()
        return jsonify({'success': True, 'started': True, 'mode': mode, 'message': f'{mode_label}已启动'})
    except Exception as e:
        log.debug('ERROR', f'启动全量扫描失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/libraries/scan-all/status', methods=['GET'])
@admin_required
def get_scan_all_status():
    """获取全量扫描进度（轮询接口）"""
    try:
        return jsonify({'success': True, **_library_scan_all_progress})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/libraries/<int:library_id>/permissions', methods=['GET'])
@admin_required
def get_library_permissions(library_id):
    """获取资源库的权限列表"""
    try:
        library = ResourceLibrary.query.get_or_404(library_id)
        permissions = LibraryPermission.query.filter_by(library_id=library_id).all()
        return jsonify({
            'success': True,
            'data': [p.to_dict() for p in permissions]
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/libraries/<int:library_id>/permissions', methods=['POST'])
@admin_required
def add_library_permission(library_id):
    """添加用户权限"""
    try:
        library = ResourceLibrary.query.get_or_404(library_id)
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
        log_operation('add library permission', target=f'library={library_id},user={user_id or group_id}', detail=f'role={role},access={access_level}', success=True)
        return jsonify({'success': True, 'data': permission.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/libraries/<int:library_id>/permissions/<int:perm_id>', methods=['PUT'])
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
        log_operation('update library permission', target=f'library={library_id},user={permission.user_id}', detail=f'role={permission.role},access={permission.access_level}', success=True)
        return jsonify({'success': True, 'data': permission.to_dict()})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/libraries/<int:library_id>/permissions/<int:perm_id>', methods=['DELETE'])
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
        log_operation('delete library permission', target=f'library={library_id},user={permission.user_id}', success=True)
        return jsonify({'success': True, 'message': '权限已删除'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/scan-folder', methods=['POST'])
@resource_manager_required
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
        supported_formats = data.get('supported_formats', runtime.app_config.get('supported_formats', []))
        
        if not folder_path:
            return jsonify({'success': False, 'message': '请指定要扫描的文件夹路径'}), 400
        
        if not os.path.exists(folder_path):
            return jsonify({'success': False, 'message': '指定的文件夹不存在'}), 400
        
        if not os.path.isdir(folder_path):
            return jsonify({'success': False, 'message': '指定的路径不是文件夹'}), 400
        
        # 资源库管理员（非全局管理员）只能扫描其管理的资源库下的文件夹
        user_id, role = resolve_identity()
        if role < UserRole.ADMIN and _HAS_RESOURCE_DB:
            admin_ids = _user_library_admin_ids(user_id)
            allowed = False
            norm_target = os.path.normcase(os.path.abspath(folder_path))
            for lid in admin_ids:
                res_id = _resolve_resource_library_id(lid)
                if not res_id:
                    continue
                rl = ResourceLibraryDB.get_by_id(res_id)
                if not rl:
                    continue
                for f in ResourceFolderDB.get_by_library(rl.id):
                    if not f.path:
                        continue
                    fp = os.path.normcase(os.path.abspath(f.path))
                    if norm_target == fp or norm_target.startswith(fp + os.sep):
                        allowed = True
                        break
                if allowed:
                    break
            if not allowed:
                return jsonify({'success': False, 'message': '只能扫描您管理的资源库下的文件夹', 'code': 403}), 403
        
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

@bp.route('/api/admin/import-videos', methods=['POST'])
@admin_required
def import_videos():
    """批量导入视频到指定资源库
    
    请求参数:
    - library_id: 目标资源库ID（可选，默认导入到主数据库）
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
        # 导入的资源归属 root（id=1），管理员对所有资源有权限
        root_user = User.query.filter_by(role=UserRole.ROOT).order_by(User.id).first()
        root_id = root_user.id if root_user else 1
        data = request.get_json()
        library_id = data.get('library_id')  # 必须指定有效的资源库ID
        videos = data.get('videos', [])
        skip_existing = data.get('skip_existing', True)
        default_tags = data.get('default_tags', runtime.app_config.get('default_tags', []))

        if not videos:
            return jsonify({'success': False, 'message': '请选择要导入的视频'}), 400

        # 验证资源库：必须指定有效的激活资源库
        if not library_id:
            return jsonify({'success': False, 'message': '请选择目标资源库'}), 400

        # 检查资源库是否存在且已激活
        library = ResourceLibrary.query.get(library_id)
        if not library:
            return jsonify({'success': False, 'message': '资源库不存在'}), 400

        if not library.is_active:
            return jsonify({'success': False, 'message': '该资源库已被禁用，无法导入'}), 400
        
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
                    priority=0,
                    library_id=library_id,  # 绑定到指定的资源库
                    owner_id=root_id
                )
                db.session.add(video)
                db.session.flush()
                
                # 添加标签
                tags = video_data.get('tags', default_tags)
                for tag_name in tags:
                    tag = Tag.query.filter_by(name=tag_name).first()
                    if not tag:
                        tag = Tag(name=tag_name, category='类型')
                        tag.path = f'/{tag_name}'  # 计算完整路径
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

@bp.route('/api/admin/browse-folders', methods=['GET'])
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

@bp.route('/api/user/libraries', methods=['GET'])
def get_user_libraries():
    """获取当前用户可访问的资源库列表"""
    try:
        user_id = None
        user_role = 0
        
        # 方式1: 从 JWT Token 获取用户信息（前端使用）
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            try:
                from authlib.jose import jwt as _jwt
                _secret = 'dbox-jwt-secret-key-change-in-production-2024'
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
        user_id, user_role = resolve_identity()

        # 获取所有激活的资源库
        libraries = ResourceLibrary.query.filter_by(is_active=True).all()

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

            # 管理员和 ROOT 可以访问所有资源库
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

        # 获取当前选中的资源库
        current_library_id = session.get('current_library_id')
        if not current_library_id and result:
            current_library_id = result[0]['id']

        return jsonify({
            'success': True,
            'data': result,
            'current_library': current_library_id
        })
    except Exception as e:
        log.debug('ERROR', f"获取用户资源库失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/user/libraries/switch', methods=['POST'])
def switch_user_library():
    """切换当前资源库"""
    try:
        data = request.get_json()
        library_id = data.get('library_id')

        if not library_id:
            return jsonify({'success': False, 'message': '请指定资源库'}), 400

        # 验证用户身份：优先 JWT token，其次 session
        user_id = None
        user_role = 0
        # 尝试 JWT token
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            try:
                from authlib.jose import jwt as _jwt
                _secret = 'dbox-jwt-secret-key-change-in-production-2024'
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

        library = ResourceLibrary.query.get_or_404(library_id)

        # 检查资源库是否被禁用
        if not library.is_active:
            return jsonify({'success': False, 'message': '该资源库已被禁用'}), 403

        # 管理员/ROOT 可以访问所有库；普通用户检查权限
        if user_role not in [UserRole.ADMIN, UserRole.ROOT]:
            user_perm = LibraryPermission.query.filter_by(library_id=library_id, user_id=user_id).first()
            group_perms = LibraryUserGroupMember.query.filter_by(user_id=user_id).all()
            has_access = bool(user_perm or any(
                LibraryPermission.query.filter_by(library_id=library_id, group_id=ugm.group_id).first()
                for ugm in group_perms
            ))
            if not has_access:
                return jsonify({'success': False, 'message': '无权访问该资源库'}), 403

        session['current_library_id'] = library_id
        return jsonify({
            'success': True,
            'message': f'已切换到资源库: {library.name}',
            'current_library': library_id
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/user-groups', methods=['GET'])
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

@bp.route('/api/admin/user-groups', methods=['POST'])
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

@bp.route('/api/admin/user-groups/<int:group_id>', methods=['DELETE'])
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

@bp.route('/api/admin/user-groups/<int:group_id>/members', methods=['POST'])
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

@bp.route('/api/admin/user-groups/<int:group_id>/members/<int:user_id>', methods=['DELETE'])
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

@bp.route('/api/admin/libraries/<int:library_id>/audit-logs', methods=['GET'])
@admin_required
def get_library_audit_logs(library_id):
    """获取资源库权限变更日志"""
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

@bp.route('/api/admin/resources', methods=['GET'])
@admin_required
def admin_list_resources():
    """统一管理界面资源列表：涵盖视频/图集/帖子/文本，支持类型筛选、搜索、分页。管理员拥有完全编辑权限。"""
    rtype = (request.args.get('type') or '').strip()
    search = (request.args.get('search') or '').strip()
    library_id = request.args.get('library_id', '')
    # 是否包含被隐藏的资源（隐藏属性位于公共层 resource_index.hidden）。
    # 管理界面默认显示全部（含已隐藏），便于管理员恢复显示。
    show_hidden = request.args.get('show_hidden', 'true').lower() != 'false'
    try:
        limit = int(request.args.get('limit', 20))
    except (TypeError, ValueError):
        limit = 20
    try:
        offset = int(request.args.get('offset', 0))
    except (TypeError, ValueError):
        offset = 0

    lib_filter = None
    if library_id not in ('', None):
        try:
            lib_filter = int(library_id)
        except (TypeError, ValueError):
            lib_filter = None

    def _like(col):
        return col.like(f'%{search}%') if search else True

    # 资源库可见性：仅统计「当前用户可见（库已激活 + 有权限）」的资源，
    # 关闭资源库后其资源必须从所有入口（含管理后台）彻底不可见。
    allowed_ids = get_allowed_library_ids()
    allowed_set = set(allowed_ids)

    # 若指定了某个资源库筛选，但该库对当前用户不可见，则视为越权、直接返回空结果
    if lib_filter is not None and lib_filter not in allowed_set:
        return jsonify({'success': True, 'items': [], 'total': 0})

    items = []

    if rtype in ('', 'video'):
        q = Video.query.filter(Video.in_trash == False, Video.library_id.in_(allowed_ids))
        if search:
            q = q.filter(_like(Video.title))
        if lib_filter is not None:
            q = q.filter(Video.library_id == lib_filter)
        if not show_hidden:
            q = q.filter(~Video.resource_index.has(ResourceIndex.hidden == True))
        for v in q.order_by(Video.created_at.desc()).all():
            ri = v.resource_index
            pres = ri.presentation() if ri else {}
            # 文件大小：优先取已存储值，缺失时回退到磁盘实际大小（无需读取视频内容）
            file_size = getattr(v, 'file_size', None)
            if not file_size and ri and ri.location and os.path.exists(ri.location):
                try:
                    file_size = os.path.getsize(ri.location)
                except OSError:
                    file_size = None
            items.append({
                'type': 'video', 'id': v.hash, 'title': v.title,
                'resource_index_id': ri.id if ri else None,
                'hidden': bool(ri.hidden) if ri else False,
                'library_id': v.library_id, 'cover': v.thumbnail,
                'owner_id': getattr(v, 'owner_id', None),
                'updated_at': str(getattr(v, 'updated_at', None) or v.created_at),
                'file_size': file_size,
                'duration': pres.get('duration') or getattr(v, 'duration', None),
                'width': pres.get('width') or getattr(v, 'width', None),
                'height': pres.get('height') or getattr(v, 'height', None),
                'views': getattr(v, 'view_count', None),
            })

    if rtype in ('', 'gallery'):
        q = Gallery.query.filter(Gallery.in_trash == False, Gallery.library_id.in_(allowed_ids))
        if search:
            q = q.filter(_like(Gallery.title))
        if lib_filter is not None:
            q = q.filter(Gallery.library_id == lib_filter)
        if not show_hidden:
            q = q.filter(~Gallery.resource_index.has(ResourceIndex.hidden == True))
        for g in q.order_by(Gallery.created_at.desc()).all():
            ri = g.resource_index
            pres = ri.presentation() if ri else {}
            items.append({
                'type': 'gallery', 'id': g.hash, 'title': g.title,
                'resource_index_id': ri.id if ri else None,
                'hidden': bool(ri.hidden) if ri else False,
                'library_id': g.library_id, 'cover': g.cover_url,
                'owner_id': getattr(g, 'owner_id', None),
                'updated_at': str(getattr(g, 'updated_at', None) or g.created_at),
                'page_count': getattr(g, 'page_count', None) or pres.get('page_count'),
            })

    if rtype in ('', 'post'):
        # 帖子通过 refs 关联资源索引，按资源索引所属库过滤可见性
        q = Post.query.join(PostRef, PostRef.post_id == Post.id).join(
            ResourceIndex, ResourceIndex.id == PostRef.resource_index_id
        ).filter(ResourceIndex.library_id.in_(allowed_ids))
        if search:
            q = q.filter(_like(Post.title))
        if not show_hidden:
            q = q.filter(~ResourceIndex.hidden == True)
        seen = set()
        for p in q.order_by(Post.created_at.desc()).distinct(Post.id).all():
            if p.id in seen:
                continue
            seen.add(p.id)
            ri = p.refs[0].resource_index if p.refs else None
            items.append({
                'type': 'post', 'id': p.id, 'title': p.title or '未命名帖子',
                'resource_index_id': ri.id if ri else None,
                'hidden': bool(ri.hidden) if ri else False,
                'library_id': ri.library_id if ri else None, 'cover': p.cover_url,
                'owner_id': p.owner_id,
                'updated_at': str(getattr(p, 'updated_at', None) or p.created_at),
                'content_length': len((p.content or '') if isinstance(p.content, str) else ''),
            })

    if rtype in ('', 'text'):
        # Text 实体本身只有 body/summary，标题/库/时间都来自关联的资源索引
        q = Text.query.join(ResourceIndex, Text.resource_index_id == ResourceIndex.id).filter(
            ResourceIndex.library_id.in_(allowed_ids)
        )
        if search:
            q = q.filter(ResourceIndex.meta.like(f'%{search}%'))
        if not show_hidden:
            q = q.filter(ResourceIndex.hidden == False)
        for t in q.order_by(ResourceIndex.updated_at.desc()).all():
            ri = t.resource_index
            pres = ri.presentation() if ri else {}
            title = (pres.get('title') if pres else None) or '未命名文本'
            body = t.body or ''
            items.append({
                'type': 'text', 'id': t.id, 'title': title,
                'resource_index_id': ri.id if ri else None,
                'hidden': bool(ri.hidden) if ri else False,
                'library_id': ri.library_id if ri else None, 'cover': None,
                'owner_id': None,
                'updated_at': str(ri.updated_at) if ri and ri.updated_at else str(t.id),
                'char_count': len(body),
            })

    items.sort(key=lambda x: x['updated_at'], reverse=True)
    total = len(items)
    page = items[offset:offset + limit]
    return jsonify({'success': True, 'items': page, 'total': total})

@bp.route('/api/admin/resources/<rtype>/<rid>', methods=['PUT'])
@admin_required
def admin_update_resource(rtype, rid):
    """管理员更新任意资源（高权限，不受归属限制）。支持标题；帖子可改正文；文本可改标题/简介/正文。"""
    data = request.get_json(silent=True) or {}
    try:
        if rtype == 'video':
            obj = Video.query.filter_by(hash=rid).first()
            if not obj:
                return jsonify({'success': False, 'message': '视频不存在'}), 404
            if 'title' in data:
                obj.title = data['title']
        elif rtype == 'gallery':
            obj = Gallery.query.filter_by(hash=rid).first()
            if not obj:
                return jsonify({'success': False, 'message': '图集不存在'}), 404
            if 'title' in data:
                obj.title = data['title']
        elif rtype == 'post':
            obj = Post.query.get(int(rid))
            if not obj:
                return jsonify({'success': False, 'message': '帖子不存在'}), 404
            if 'title' in data:
                obj.title = data['title']
            if 'content' in data:
                obj.content = data['content']
        elif rtype == 'text':
            obj = Text.query.get(int(rid))
            if not obj:
                return jsonify({'success': False, 'message': '文本不存在'}), 404
            if 'title' in data:
                obj.title = data['title']
            if 'summary' in data:
                obj.summary = data['summary']
            if 'body' in data:
                obj.body = data['body']
        else:
            return jsonify({'success': False, 'message': '未知资源类型'}), 400
        db.session.commit()
        return jsonify({'success': True, 'message': '更新成功'})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"管理员更新资源失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/resources/<rtype>/<rid>', methods=['DELETE'])
@admin_required
def admin_delete_resource(rtype, rid):
    """管理员删除任意资源（高权限）。"""
    try:
        if rtype == 'video':
            obj = Video.query.filter_by(hash=rid).first()
            if obj:
                purge_trash(obj, 'video')
        elif rtype == 'gallery':
            obj = Gallery.query.filter_by(hash=rid).first()
            if obj:
                purge_trash(obj, 'gallery')
        elif rtype == 'post':
            obj = Post.query.get(int(rid))
            if obj:
                db.session.delete(obj)
        elif rtype == 'text':
            obj = Text.query.get(int(rid))
            if obj:
                db.session.delete(obj)
        else:
            return jsonify({'success': False, 'message': '未知资源类型'}), 400
        db.session.commit()
        return jsonify({'success': True, 'message': '删除成功'})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"管理员删除资源失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/trash', methods=['GET'])
@admin_required
def admin_trash_list():
    """列出回收站中的所有资源（视频 + 图集）。"""
    try:
        items = get_trash_list()
        return jsonify({'success': True, 'items': items, 'total': len(items)})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/trash/restore', methods=['POST'])
@admin_required
def admin_trash_restore():
    """将回收站中的资源恢复到原位置。"""
    try:
        data = request.get_json(silent=True) or {}
        kind = data.get('type')
        h = data.get('hash')
        obj = get_trash_obj(kind, h)
        if not obj:
            return jsonify({'success': False, 'message': '资源不存在或不在回收站中'}), 404
        restore_from_trash(obj, kind)
        return jsonify({'success': True, 'message': '已恢复'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/trash/purge', methods=['POST'])
@admin_required
def admin_trash_purge():
    """永久删除回收站中的资源。"""
    try:
        data = request.get_json(silent=True) or {}
        kind = data.get('type')
        h = data.get('hash')
        obj = get_trash_obj(kind, h)
        if not obj:
            return jsonify({'success': False, 'message': '资源不存在或不在回收站中'}), 404
        purge_trash(obj, kind)
        log_operation('permanently delete recycle-bin item', target=f'{kind}:{h}', success=True)
        return jsonify({'success': True, 'message': '已永久删除'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/admin/trash/empty', methods=['POST'])
@admin_required
def admin_trash_empty():
    """清空回收站（永久删除全部）。"""
    try:
        items = get_trash_list()
        for it in items:
            obj = get_trash_obj(it['type'], it['hash'])
            if obj:
                purge_trash(obj, it['type'])
        log_operation('empty recycle bin', target=f'{len(items)}项', success=True)
        return jsonify({'success': True, 'message': f'已清空回收站（{len(items)} 项）'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
