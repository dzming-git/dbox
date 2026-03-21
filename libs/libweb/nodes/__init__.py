# -*- coding: utf-8 -*-
"""
Node子模块

提供各种预定义的Node实现：
- HealthNode: 健康检查节点
- VideoNode: 视频相关节点
- TagNode: 标签相关节点
- SystemNode: 系统相关节点
- LogNode: 日志相关节点
- routes: 路由注册中心
"""

from .health import HealthNode
from .video import (
    VideoListNode, VideoDetailNode, VideoLikeNode, VideoFavoriteNode,
    VideoUploadNode, VideoDeleteNode, VideoScanNode, VideoAddNode,
    VideoRecommendNode, FavoritesNode
)
from .tag import (
    TagListNode, TagAddNode, TagDetailNode, TagVideosNode, VideoTagsNode
)
from .system import (
    ConfigNode, StatusNode, DependenciesCheckNode,
    VideosClearNode, CheckFileNode, ThumbnailsRegenerateNode,
    ThumbnailStatusNode, ThumbnailProgressNode
)
from .log import (
    LogsNode, LogDetailNode, LogDownloadNode,
    LogsClearNode, LogTypeClearNode, LogsSizeNode
)
from .routes import register_all_routes, get_registered_routes_count

__all__ = [
    'HealthNode',
    'VideoListNode', 'VideoDetailNode', 'VideoLikeNode', 'VideoFavoriteNode',
    'VideoUploadNode', 'VideoDeleteNode', 'VideoScanNode', 'VideoAddNode',
    'VideoRecommendNode', 'FavoritesNode',
    'TagListNode', 'TagAddNode', 'TagDetailNode', 'TagVideosNode', 'VideoTagsNode',
    'ConfigNode', 'StatusNode', 'DependenciesCheckNode',
    'VideosClearNode', 'CheckFileNode', 'ThumbnailsRegenerateNode',
    'ThumbnailStatusNode', 'ThumbnailProgressNode',
    'LogsNode', 'LogDetailNode', 'LogDownloadNode',
    'LogsClearNode', 'LogTypeClearNode', 'LogsSizeNode',
    'register_all_routes', 'get_registered_routes_count',
]
