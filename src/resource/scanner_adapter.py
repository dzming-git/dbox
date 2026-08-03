# -*- coding: utf-8 -*-
"""
BusResourceAdapter - 资源管理服务的总线适配器

将资源扫描服务封装为总线风格的服务。

总线服务定义：

  Service:        com.dbox.resourced
  Interface:      com.dbox.Resourced
  Object Path:    /com/dbox/resourced

  Methods:
    ListLibraries()
      → {libraries: [...]}

    AddLibrary(config)
      → {success: bool, library_id: int}

    RemoveLibrary(library_id)
      → {success: bool}

    ScanLibrary(library_id)
      → {success: bool, stats: {...}}

    GetLibraryStatus(library_id)
      → {success: bool, library: {...}, stats: {...}}

    WatchLibrary(library_id)
      → {success: bool}

    UnwatchLibrary(library_id)
      → {success: bool}

    GetResource(hash)
      → {success: bool, resource: {...}}

    GetResourcesByLibrary(library_id, limit, offset)
      → {success: bool, resources: [...], total: int}

    HealthCheck()
      → {status: str, watching_count: int}
"""

import os
import sys
import threading
import time
from datetime import datetime
from typing import Dict, Any, Optional, Callable
from types import SimpleNamespace

# 添加 src 目录到 path 以便导入 servicebus 和本地模块
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

# 支持直接运行和模块导入
try:
    from .models import (
        ResourceLibrary, ResourceLibraryDB, ResourceFolder, ResourceFolderDB,
        ResourceType, ScanMode, PathType, Database,
        get_db_dir
    )
    from .indexer import MediaIndexer
    from .watcher import LibraryWatcher
except ImportError:
    from resource.models import (
        ResourceLibrary, ResourceLibraryDB, ResourceFolder, ResourceFolderDB,
        ResourceType, ScanMode, PathType, Database,
        get_db_dir
    )
    from resource.indexer import MediaIndexer
    from resource.watcher import LibraryWatcher

from servicebus.service_base import BaseDBusService

# 数据库目录
_DB_DIR = get_db_dir()


class BusResourceAdapter(BaseDBusService):
    """
    资源管理服务总线适配器
    """

    BUS_NAME = 'com.dbox.resourced'
    INTERFACES = ['com.dbox.Resourced']
    OBJECT_PATH = '/com/dbox/resourced'

    def __init__(self, host: str = '127.0.0.1', rpc_port: int = 15555, pub_port: int = 15556):
        super().__init__(host, rpc_port, pub_port)
        self._watcher = LibraryWatcher()
        self._scan_lock = threading.Lock()
        self._scanning_libraries = set()   # 正在扫描的库 ID
        # 扫描进度：{library_id: {current, total, current_file, status, result}}
        self._scan_progress: Dict[int, Dict] = {}

    # ============ 库管理 ============

    def on_method_list_libraries(self, params: Dict[str, Any]) -> Dict:
        """列出所有资源库"""
        try:
            libraries = ResourceLibraryDB.get_all()
            return {
                'success': True,
                'libraries': [lib.to_dict() for lib in libraries],
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_add_library(self, params: Dict[str, Any]) -> Dict:
        """添加资源库"""
        try:
            name = params.get('name', '').strip()
            path = params.get('path', '').strip()
            resource_type = params.get('resource_type', 'video')
            scan_mode = params.get('scan_mode', 'manual')
            scan_interval = params.get('scan_interval', 60)

            if not name or not path:
                return {'success': False, 'error': '名称和路径不能为空'}

            if not os.path.isdir(path):
                return {'success': False, 'error': '路径不存在或不是目录'}

            # 检查是否已存在同名库
            existing = ResourceLibraryDB.get_all()
            for lib in existing:
                if lib.name == name:
                    return {'success': False, 'error': f'库名称 {name} 已存在'}

            library = ResourceLibrary(
                name=name,
                path=path,
                resource_type=ResourceType(resource_type),
                scan_mode=ScanMode(scan_mode),
                scan_interval=scan_interval,
            )
            library_id = ResourceLibraryDB.create(library)

            return {'success': True, 'library_id': library_id}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_remove_library(self, params: Dict[str, Any]) -> Dict:
        """删除资源库"""
        try:
            library_id = params.get('library_id')
            if not library_id:
                return {'success': False, 'error': '缺少 library_id'}

            # 停止监控
            if self._watcher.is_watching(library_id):
                self._watcher.unwatch(library_id)

            # 删除库（级联删除资源）
            success = ResourceLibraryDB.delete(library_id)
            return {'success': success}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_update_library(self, params: Dict[str, Any]) -> Dict:
        """更新资源库配置"""
        try:
            library_id = params.get('library_id')
            if not library_id:
                return {'success': False, 'error': '缺少 library_id'}

            library = ResourceLibraryDB.get_by_id(library_id)
            if not library:
                return {'success': False, 'error': '库不存在'}

            # 检查是否是重命名操作
            new_name = params.get('name', '').strip()
            if new_name and new_name != library.name:
                # 重命名：同时更新库名和数据库文件名
                new_db_file = f"{new_name}.db"
                old_db_file = library.db_file

                # 更新数据库记录
                ResourceLibraryDB.rename_library(library_id, new_name, new_db_file)

                # 重命名数据库文件
                if old_db_file:
                    old_path = os.path.join(_DB_DIR, old_db_file)
                    new_path = os.path.join(_DB_DIR, new_db_file)
                    if os.path.exists(old_path) and not os.path.exists(new_path):
                        os.rename(old_path, new_path)

                library.name = new_name
                library.db_file = new_db_file
            else:
                # 普通更新
                if 'path' in params:
                    library.path = params['path'].strip()
                if 'resource_type' in params:
                    library.resource_type = ResourceType(params['resource_type'])
                if 'scan_mode' in params:
                    library.scan_mode = ScanMode(params['scan_mode'])
                if 'scan_interval' in params:
                    library.scan_interval = params['scan_interval']
                if 'is_active' in params:
                    library.is_active = params['is_active']

                ResourceLibraryDB.update(library)

            return {'success': True, 'library': library.to_dict()}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 文件夹管理 ============

    def on_method_list_folders(self, params: Dict[str, Any]) -> Dict:
        """列出资源库的所有文件夹"""
        try:
            library_id = params.get('library_id')
            if not library_id:
                return {'success': False, 'error': '缺少 library_id'}

            folders = ResourceFolderDB.get_by_library(library_id)

            # 为每个文件夹添加资源数量
            result = []
            for folder in folders:
                folder_dict = folder.to_dict()
                folder_dict['item_count'] = ResourceFolderDB.get_item_count(folder.id)
                result.append(folder_dict)

            return {
                'success': True,
                'folders': result,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_add_folder(self, params: Dict[str, Any]) -> Dict:
        """添加文件夹/文件到资源库"""
        try:
            library_id = params.get('library_id')
            name = params.get('name', '').strip()
            path = params.get('path', '').strip()
            path_type = params.get('path_type', 'folder')
            is_default = params.get('is_default', False)

            if not library_id:
                return {'success': False, 'error': '缺少 library_id'}
            if not path:
                return {'success': False, 'error': '路径不能为空'}

            # 自动生成名称（从路径提取）
            if not name:
                name = os.path.basename(path.rstrip('/\\'))
                if not name:
                    name = path

            # 检查库是否存在
            library = ResourceLibraryDB.get_by_id(library_id)
            if not library:
                return {'success': False, 'error': '库不存在'}

            # 检查路径是否存在
            if path_type == 'folder' and not os.path.isdir(path):
                return {'success': False, 'error': '文件夹路径不存在'}
            if path_type == 'file' and not os.path.isfile(path):
                return {'success': False, 'error': '文件路径不存在'}

            # 检查是否已存在同名文件夹
            existing = ResourceFolderDB.get_by_path(path, library_id)
            if existing:
                return {'success': False, 'error': '该路径已添加'}

            # 如果设置为默认，且该库还没有默认路径，则直接设置
            # 如果设置为默认，但已有默认路径，会在 create 时自动替换
            folder = ResourceFolder(
                library_id=library_id,
                name=name,
                path=path,
                path_type=PathType(path_type),
                is_default=is_default,
            )
            folder_id = ResourceFolderDB.create(folder)
            folder.id = folder_id

            return {
                'success': True,
                'folder_id': folder_id,
                'folder': folder.to_dict(),
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_remove_folder(self, params: Dict[str, Any]) -> Dict:
        """从资源库移除文件夹"""
        try:
            folder_id = params.get('folder_id')
            if not folder_id:
                return {'success': False, 'error': '缺少 folder_id'}

            folder = ResourceFolderDB.get_by_id(folder_id)
            if not folder:
                return {'success': False, 'error': '文件夹不存在'}

            success = ResourceFolderDB.delete(folder_id)
            return {'success': success}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_update_folder(self, params: Dict[str, Any]) -> Dict:
        """更新文件夹配置"""
        try:
            folder_id = params.get('folder_id')
            if not folder_id:
                return {'success': False, 'error': '缺少 folder_id'}

            folder = ResourceFolderDB.get_by_id(folder_id)
            if not folder:
                return {'success': False, 'error': '文件夹不存在'}

            if 'name' in params:
                folder.name = params['name'].strip()
            if 'path' in params:
                folder.path = params['path'].strip()
            if 'is_active' in params:
                folder.is_active = params['is_active']
            if 'is_default' in params:
                folder.is_default = params['is_default']
            if 'scan_mode' in params:
                folder.scan_mode = ScanMode(params['scan_mode'])
            if 'scan_interval' in params:
                folder.scan_interval = params['scan_interval']

            ResourceFolderDB.update(folder)
            return {'success': True, 'folder': folder.to_dict()}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_set_default_folder(self, params: Dict[str, Any]) -> Dict:
        """设置文件夹为默认上传路径"""
        try:
            folder_id = params.get('folder_id')
            if not folder_id:
                return {'success': False, 'error': '缺少 folder_id'}

            success = ResourceFolderDB.set_default(folder_id)
            if success:
                folder = ResourceFolderDB.get_by_id(folder_id)
                return {'success': True, 'folder': folder.to_dict()}
            return {'success': False, 'error': '设置默认路径失败'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_get_default_folder(self, params: Dict[str, Any]) -> Dict:
        """获取库的默认上传路径"""
        try:
            library_id = params.get('library_id')
            if not library_id:
                return {'success': False, 'error': '缺少 library_id'}

            folder = ResourceFolderDB.get_default_folder(library_id)
            if folder:
                return {'success': True, 'folder': folder.to_dict()}
            return {'success': True, 'folder': None, 'message': '没有设置默认路径'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_get_default_upload_path(self, params: Dict[str, Any]) -> Dict:
        """获取库的默认上传路径（返回路径字符串）"""
        try:
            library_id = params.get('library_id')
            if not library_id:
                return {'success': False, 'error': '缺少 library_id'}

            folder = ResourceFolderDB.get_default_folder(library_id)
            if folder:
                return {'success': True, 'path': folder.path}

            # 如果没有设置默认文件夹，返回库的主路径
            library = ResourceLibraryDB.get_by_id(library_id)
            if library and library.path:
                return {'success': True, 'path': library.path}

            return {'success': False, 'error': '该库没有配置上传路径'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 扫描 ============

    def on_method_scan_library(self, params: Dict[str, Any]) -> Dict:
        """扫描资源库（异步，立即返回，前端轮询进度）"""
        try:
            library_id = params.get('library_id')
            if not library_id:
                return {'success': False, 'error': '缺少 library_id'}

            print(f"[scanner] ScanLibrary called, library_id={library_id}", flush=True)

            # 自动清理已完成的扫描状态（防止残留导致无法再次扫描）
            prog = self._scan_progress.get(library_id)
            if prog and prog.get('status') in ('done', 'error'):
                with self._scan_lock:
                    self._scanning_libraries.discard(library_id)
                del self._scan_progress[library_id]
                prog = None
                print(f"[scanner] cleaned stale scan state for library {library_id}", flush=True)
            
            # 额外清理：如果 library_id 在 _scanning_libraries 但不在 _scan_progress 中（孤立状态），也清理
            if library_id in self._scanning_libraries and library_id not in self._scan_progress:
                with self._scan_lock:
                    self._scanning_libraries.discard(library_id)
                print(f"[scanner] cleaned orphaned scan state for library {library_id}", flush=True)
                print(f"[scanner]   reason: in _scanning_libraries but not in _scan_progress", flush=True)

            with self._scan_lock:
                if library_id in self._scanning_libraries:
                    print(f"[scanner] scan already in progress for library {library_id}", flush=True)
                    return {'success': False, 'error': '扫描已在进行中，请稍候...'}
                self._scanning_libraries.add(library_id)
            print(f"[scanner] scan lock acquired for library {library_id}", flush=True)

            library = ResourceLibraryDB.get_by_id(library_id)
            if not library:
                with self._scan_lock:
                    self._scanning_libraries.discard(library_id)
                return {'success': False, 'error': '库不存在'}

            if not os.path.isdir(library.path):
                with self._scan_lock:
                    self._scanning_libraries.discard(library_id)
                return {'success': False, 'error': '路径不存在'}

            # 初始化进度
            self._scan_progress[library_id] = {
                'library_id': library_id,
                'current': 0,
                'total': 0,
                'current_file': '',
                'status': 'scanning',
                'result': None,
                'error': None,
            }

            # 后台线程执行扫描
            def _scan_thread():
                # 进度回调：更新 self._scan_progress
                def _progress(current: int, total: int, current_file: str):
                    prog = self._scan_progress.get(library_id)
                    if prog:
                        prog['current'] = current
                        prog['total'] = total
                        prog['current_file'] = current_file

                try:
                    result = self._do_scan(library, progress_callback=_progress)
                    prog = self._scan_progress.get(library_id)
                    if prog:
                        prog['status'] = 'done'
                        prog['result'] = result
                except Exception as e:
                    prog = self._scan_progress.get(library_id)
                    if prog:
                        prog['status'] = 'error'
                        prog['error'] = str(e)
                finally:
                    with self._scan_lock:
                        self._scanning_libraries.discard(library_id)

            threading.Thread(target=_scan_thread, daemon=True).start()
            return {'success': True, 'started': True}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_get_scan_progress(self, params: Dict[str, Any]) -> Dict:
        """获取扫描进度"""
        library_id = params.get('library_id')
        if not library_id:
            return {'success': False, 'error': '缺少 library_id'}
        prog = self._scan_progress.get(library_id)
        if not prog:
            return {'success': True, 'status': 'idle', 'message': '没有进行中的扫描'}
        return {'success': True, **prog}

    def on_method_reset_scan(self, params: Dict[str, Any]) -> Dict:
        """重置扫描状态（清除卡住的扫描状态）"""
        library_id = params.get('library_id')
        if not library_id:
            return {'success': False, 'error': '缺少 library_id'}
        with self._scan_lock:
            self._scanning_libraries.discard(library_id)
        self._scan_progress.pop(library_id, None)
        return {'success': True, 'message': '扫描状态已重置'}

    def _do_scan(self, library: ResourceLibrary, progress_callback: Callable = None) -> Dict:
        """执行实际扫描（仅枚举文件 + 进度上报，不做内容索引）。

        注：自 2026-07-12 起，resourced 不再维护文件级索引（ResourceItem 已废弃），
        索引权威源统一为 web 的 Video 表（由 web 的 library_watcher / scan-folder / 导入流程负责）。
        本方法只负责「遍历磁盘 + 进度上报 + 返回媒体文件清单」，供上层驱动 web 侧索引。
        """
        try:
            # 获取库下所有文件夹
            folders = ResourceFolderDB.get_by_library(library.id)
            if not folders:
                # 没有配置文件夹时，退回到扫描 library.path
                from types import SimpleNamespace
                folders = [SimpleNamespace(id=None, path=library.path)]

            # 预扫：收集所有文件路径（用于进度计算）
            indexer = MediaIndexer()
            all_files = []  # [(folder_id, file_path), ...]
            for folder in folders:
                fpath = folder.path
                if not os.path.isdir(fpath):
                    print(f"[scanner] folder not found, skip: {fpath}", flush=True)
                    continue
                for root, dirs, files in os.walk(fpath):
                    for filename in files:
                        all_files.append((folder.id, os.path.join(root, filename)))

            total = len(all_files)
            print(f"[scanner] start scan, {total} files in {len(folders)} folder(s)", flush=True)

            stats = {'total': 0, 'videos': 0, 'images': 0, 'galleries': 0, 'unknown': 0}
            scanned_files = []  # 媒体文件清单（供 web 侧索引使用）

            for idx, (folder_id, file_path) in enumerate(all_files, 1):
                if progress_callback:
                    progress_callback(idx, total, file_path)
                try:
                    rtype = indexer.detect_resource_type(file_path)
                    stats['total'] += 1
                    stats[rtype + 's'] = stats.get(rtype + 's', 0) + 1
                    if rtype in ('video', 'image', 'gallery'):
                        scanned_files.append(file_path)
                except Exception as e:
                    print(f"[scanner] classify failed: {file_path}: {e}", flush=True)
                    stats['unknown'] += 1

            print(f"[scanner] scan done, {len(scanned_files)} media files enumerated, stats={stats}", flush=True)

            # 更新库的扫描时间（仅元数据，不产生文件级索引）
            library.last_scan_at = datetime.utcnow()
            ResourceLibraryDB.update(library)

            return {
                'success': True,
                'stats': stats,
                'files': scanned_files,
                'added': [],
                'updated': [],
                'removed': [],
            }
        except Exception as e:
            print(f"[scanner] _do_scan error: {e}", flush=True)
            return {'success': False, 'error': str(e)}

    def on_method_get_library_status(self, params: Dict[str, Any]) -> Dict:
        """获取资源库状态"""
        try:
            library_id = params.get('library_id')
            if not library_id:
                return {'success': False, 'error': '缺少 library_id'}

            library = ResourceLibraryDB.get_by_id(library_id)
            if not library:
                return {'success': False, 'error': '库不存在'}

            # resource_count 已废弃：文件级索引（ResourceItem）于 2026-07-12 移除，
            # 索引权威源统一为 web 的 Video 表。此处恒为 0。
            resource_count = 0

            return {
                'success': True,
                'library': library.to_dict(),
                'stats': {
                    'resource_count': resource_count,
                    'is_watching': self._watcher.is_watching(library_id),
                    'is_scanning': library_id in self._scanning_libraries,
                }
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 文件监控 ============

    def on_method_watch_library(self, params: Dict[str, Any]) -> Dict:
        """登记文件监控状态（仅元数据）。

        注：自 2026-07-12 起，真实的文件系统监控由 web 的 library_watcher 负责
        （它直接维护 web 的 Video 表，作为唯一索引源）。resourced 不再启动 watchdog，
        避免与 web 重复监控、重复写索引。这里仅记录 is_watching 供展示。
        """
        try:
            library_id = params.get('library_id')
            if not library_id:
                return {'success': False, 'error': '缺少 library_id'}

            library = ResourceLibraryDB.get_by_id(library_id)
            if not library:
                return {'success': False, 'error': '库不存在'}

            library.is_watching = True
            library.last_watch_at = datetime.utcnow()
            ResourceLibraryDB.update(library)

            return {'success': True, 'message': '监控状态已登记（实际监控由 web 服务负责）'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_unwatch_library(self, params: Dict[str, Any]) -> Dict:
        """取消文件监控状态（仅元数据，见 on_method_watch_library 说明）"""
        try:
            library_id = params.get('library_id')
            if not library_id:
                return {'success': False, 'error': '缺少 library_id'}

            library = ResourceLibraryDB.get_by_id(library_id)
            if library:
                library.is_watching = False
                ResourceLibraryDB.update(library)

            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 资源查询 ============

    def on_method_get_resource(self, params: Dict[str, Any]) -> Dict:
        """根据 hash 获取资源（已废弃：ResourceItem 于 2026-07-12 移除，索引权威源为 web 的 Video 表）"""
        return {
            'success': False,
            'error': '资源索引已迁移至 web 的 Video 表（com.dbox.web），resourced 不再提供文件级资源查询',
        }

    def on_method_get_resources_by_library(self, params: Dict[str, Any]) -> Dict:
        """获取库的所有资源（已废弃：见 on_method_get_resource 说明，返回空列表）"""
        return {'success': True, 'resources': [], 'total': 0}

    # ============ 健康检查 ============

    def on_method_health_check(self, params: Dict[str, Any]) -> Dict:
        """健康检查"""
        return {
            'status': 'healthy',
            'watching_count': len(self._watcher._observers),
            'scanning_count': len(self._scanning_libraries),
        }
