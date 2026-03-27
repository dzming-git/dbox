# -*- coding: utf-8 -*-
"""
资源管理模块 - 文件监控器
使用 watchdog 监控文件夹变化，实时更新索引
"""

import os
import threading
from datetime import datetime
from typing import Callable, Optional, Dict, Any

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = None
    FileSystemEvent = None

from .indexer import MediaIndexer
from .models import ResourceItem, ResourceItemDB


if WATCHDOG_AVAILABLE:
    class ResourceChangeHandler(FileSystemEventHandler):
        """资源文件变化处理器"""

        def __init__(self, library_id: int, on_change: Callable[[str, str, str], None]):
            self.library_id = library_id
            self.on_change = on_change
            self._indexer = MediaIndexer()

        def on_created(self, event: FileSystemEvent):
            if event.is_directory:
                return
            self._handle_file_event('created', event.src_path)

        def on_modified(self, event: FileSystemEvent):
            if event.is_directory:
                return
            self._handle_file_event('modified', event.src_path)

        def on_deleted(self, event: FileSystemEvent):
            if event.is_directory:
                return
            self._handle_file_event('deleted', event.src_path)

        def on_moved(self, event: FileSystemEvent):
            if event.is_directory:
                return
            self._handle_file_event('deleted', event.src_path)
            self._handle_file_event('created', event.dest_path)

        def _handle_file_event(self, event_type: str, file_path: str):
            try:
                resource_type = self._indexer.detect_resource_type(file_path)
                if resource_type == 'unknown':
                    return

                if event_type == 'deleted':
                    item = ResourceItemDB.get_by_library(self.library_id)
                    for i in item:
                        if i.file_path == file_path:
                            ResourceItemDB.soft_delete(i.hash)
                            self.on_change(event_type, file_path, i.hash)
                            break
                else:
                    info = self._indexer.index_file(file_path, self.library_id)
                    if info:
                        item = ResourceItem(
                            library_id=self.library_id,
                            hash=info['hash'],
                            file_path=info['file_path'],
                            file_name=info['file_name'],
                            file_ext=info['file_ext'],
                            file_size=info['file_size'],
                            mime_type=info['mime_type'],
                            width=info.get('width'),
                            height=info.get('height'),
                            duration=info.get('duration'),
                            metadata=info.get('metadata', {}),
                        )
                        ResourceItemDB.upsert(item)
                        self.on_change(event_type, file_path, info['hash'])
            except Exception as e:
                print(f"处理文件事件失败 {event_type} {file_path}: {e}")
else:
    ResourceChangeHandler = None


class LibraryWatcher:
    """资源库监控管理器"""

    def __init__(self):
        self._observers: Dict[int, Any] = {}
        self._handlers: Dict[int, Any] = {}
        self._threads: Dict[int, threading.Thread] = {}
        self._callbacks: Dict[int, Callable] = {}
        self._watching_paths: Dict[int, str] = {}
        self._lock = threading.Lock()

    def watch(self, library_id: int, path: str, callback: Callable[[str, str, str], None] = None):
        if not WATCHDOG_AVAILABLE:
            raise RuntimeError("watchdog 模块未安装，无法使用文件监控功能。请运行: pip install watchdog")

        with self._lock:
            if library_id in self._observers:
                self.unwatch(library_id)

            if not os.path.isdir(path):
                raise ValueError(f"路径不是有效的目录: {path}")

            handler = ResourceChangeHandler(library_id, callback or self._default_callback)
            observer = Observer()
            observer.schedule(handler, path, recursive=True)
            observer.start()

            self._observers[library_id] = observer
            self._handlers[library_id] = handler
            self._callbacks[library_id] = callback
            self._watching_paths[library_id] = path

    def unwatch(self, library_id: int):
        with self._lock:
            if library_id in self._observers:
                observer = self._observers.pop(library_id)
                observer.stop()
                observer.join(timeout=3)

            self._handlers.pop(library_id, None)
            self._callbacks.pop(library_id, None)
            self._watching_paths.pop(library_id, None)

    def is_watching(self, library_id: int) -> bool:
        return library_id in self._observers

    def get_watching_path(self, library_id: int) -> Optional[str]:
        return self._watching_paths.get(library_id)

    def stop_all(self):
        with self._lock:
            for library_id in list(self._observers.keys()):
                self.unwatch(library_id)

    @staticmethod
    def _default_callback(event_type: str, file_path: str, file_hash: str):
        print(f"[Watcher] {event_type}: {file_path} (hash: {file_hash[:16]}...)")
