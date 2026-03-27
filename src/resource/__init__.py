# -*- coding: utf-8 -*-
"""
资源管理模块

提供统一的资源（视频、图片、组图）管理能力：
- 多库支持
- 自动扫描索引
- 文件监控（实时更新）
"""

from .models import (
    ResourceLibrary,
    ResourceItem,
    ResourceLibraryDB,
    ResourceItemDB,
    ResourceType,
    ScanMode,
    Database,
)
from .indexer import MediaIndexer
from .watcher import LibraryWatcher
from .scanner_adapter import BusResourceAdapter

__all__ = [
    'ResourceLibrary',
    'ResourceItem',
    'ResourceLibraryDB',
    'ResourceItemDB',
    'ResourceType',
    'ScanMode',
    'Database',
    'MediaIndexer',
    'LibraryWatcher',
    'BusResourceAdapter',
]
