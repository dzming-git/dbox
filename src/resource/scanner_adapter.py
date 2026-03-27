# -*- coding: utf-8 -*-
"""
BusResourceAdapter - 资源管理服务的总线适配器

将资源扫描服务封装为总线风格的服务。

总线服务定义：

  Service:        com.dplayer.resourced
  Interface:      com.dplayer.Resourced
  Object Path:    /com/dplayer/resourced

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
from typing import Dict, Any, Optional

# 添加 src 目录到 path 以便导入 servicebus
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from .models import (
    ResourceLibrary, ResourceLibraryDB, ResourceItem, ResourceItemDB,
    ResourceType, ScanMode, Database
)
from .indexer import MediaIndexer
from .watcher import LibraryWatcher
from servicebus.service_base import BaseDBusService


class BusResourceAdapter(BaseDBusService):
    """
    资源管理服务总线适配器
    """

    BUS_NAME = 'com.dplayer.resourced'
    INTERFACES = ['com.dplayer.Resourced']
    OBJECT_PATH = '/com/dplayer/resourced'

    def __init__(self, host: str = '127.0.0.1', rpc_port: int = 15555, pub_port: int = 15556):
        super().__init__(host, rpc_port, pub_port)
        self._watcher = LibraryWatcher()
        self._scan_lock = threading.Lock()
        self._scanning_libraries = set()  # 正在扫描的库 ID

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

            # 更新字段
            if 'name' in params:
                library.name = params['name'].strip()
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

    # ============ 扫描 ============

    def on_method_scan_library(self, params: Dict[str, Any]) -> Dict:
        """扫描资源库"""
        try:
            library_id = params.get('library_id')
            if not library_id:
                return {'success': False, 'error': '缺少 library_id'}

            # 检查是否正在扫描
            if library_id in self._scanning_libraries:
                return {'success': False, 'error': '扫描已在进行中'}

            library = ResourceLibraryDB.get_by_id(library_id)
            if not library:
                return {'success': False, 'error': '库不存在'}

            if not os.path.isdir(library.path):
                return {'success': False, 'error': '路径不存在'}

            # 启动扫描线程
            def scan():
                with self._scan_lock:
                    self._scanning_libraries.add(library_id)
                try:
                    self._do_scan(library)
                finally:
                    with self._scan_lock:
                        self._scanning_libraries.discard(library_id)

            threading.Thread(target=scan, daemon=True).start()

            # 同步执行一次扫描（阻塞直到完成，返回结果）
            return self._do_scan(library)
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _do_scan(self, library: ResourceLibrary) -> Dict:
        """执行实际扫描"""
        try:
            indexer = MediaIndexer()
            result = indexer.scan_directory(library.path, library.id)

            # 更新数据库
            items_added = 0
            for item_info in result.get('items', []):
                item = ResourceItem(
                    library_id=library.id,
                    hash=item_info['hash'],
                    file_path=item_info['file_path'],
                    file_name=item_info['file_name'],
                    file_ext=item_info['file_ext'],
                    file_size=item_info['file_size'],
                    mime_type=item_info['mime_type'],
                    width=item_info.get('width'),
                    height=item_info.get('height'),
                    duration=item_info.get('duration'),
                    metadata=item_info.get('metadata', {}),
                )
                ResourceItemDB.upsert(item)
                items_added += 1

            # 更新库的扫描时间
            library.last_scan_at = datetime.utcnow()
            ResourceLibraryDB.update(library)

            return {
                'success': True,
                'stats': {
                    'total': result['total'],
                    'videos': result['videos'],
                    'images': result['images'],
                    'galleries': result['galleries'],
                    'unknown': result['unknown'],
                    'items_added': items_added,
                }
            }
        except Exception as e:
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

            resource_count = ResourceItemDB.count_by_library(library_id)

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
        """启动文件监控"""
        try:
            library_id = params.get('library_id')
            if not library_id:
                return {'success': False, 'error': '缺少 library_id'}

            library = ResourceLibraryDB.get_by_id(library_id)
            if not library:
                return {'success': False, 'error': '库不存在'}

            if not os.path.isdir(library.path):
                return {'success': False, 'error': '路径不存在'}

            if self._watcher.is_watching(library_id):
                return {'success': True, 'message': '已经在监控中'}

            def on_change(event_type: str, file_path: str, file_hash: str):
                print(f"[ResourceWatcher] {library.name}: {event_type} {file_path}")

            self._watcher.watch(library_id, library.path, on_change)

            # 更新库的监控状态
            library.is_watching = True
            library.last_watch_at = datetime.utcnow()
            ResourceLibraryDB.update(library)

            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_unwatch_library(self, params: Dict[str, Any]) -> Dict:
        """停止文件监控"""
        try:
            library_id = params.get('library_id')
            if not library_id:
                return {'success': False, 'error': '缺少 library_id'}

            if not self._watcher.is_watching(library_id):
                return {'success': True, 'message': '未在监控'}

            self._watcher.unwatch(library_id)

            # 更新库的监控状态
            library = ResourceLibraryDB.get_by_id(library_id)
            if library:
                library.is_watching = False
                ResourceLibraryDB.update(library)

            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 资源查询 ============

    def on_method_get_resource(self, params: Dict[str, Any]) -> Dict:
        """根据 hash 获取资源"""
        try:
            hash_value = params.get('hash', '')
            if not hash_value:
                return {'success': False, 'error': '缺少 hash'}

            resource = ResourceItemDB.get_by_hash(hash_value)
            if not resource:
                return {'success': False, 'error': '资源不存在'}

            return {'success': True, 'resource': resource.to_dict()}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_get_resources_by_library(self, params: Dict[str, Any]) -> Dict:
        """获取库的所有资源"""
        try:
            library_id = params.get('library_id')
            if not library_id:
                return {'success': False, 'error': '缺少 library_id'}

            library = ResourceLibraryDB.get_by_id(library_id)
            if not library:
                return {'success': False, 'error': '库不存在'}

            resources = ResourceItemDB.get_by_library(library_id)
            total = len(resources)

            # 分页
            limit = params.get('limit', 100)
            offset = params.get('offset', 0)
            page_resources = resources[offset:offset+limit]

            return {
                'success': True,
                'resources': [r.to_dict() for r in page_resources],
                'total': total,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 健康检查 ============

    def on_method_health_check(self, params: Dict[str, Any]) -> Dict:
        """健康检查"""
        return {
            'status': 'healthy',
            'watching_count': len(self._watcher._observers),
            'scanning_count': len(self._scanning_libraries),
        }
