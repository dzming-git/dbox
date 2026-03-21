# -*- coding: utf-8 -*-
"""
Routes - 路由注册中心

集中管理所有Node的注册。
"""

from ..core import NodeManager

# 导入所有Node
from ..nodes.health import HealthNode
from ..nodes.video import (
    VideoListNode, VideoDetailNode, VideoLikeNode, VideoFavoriteNode,
    VideoUploadNode, VideoDeleteNode, VideoScanNode, VideoAddNode,
    VideoRecommendNode, FavoritesNode
)
from ..nodes.tag import (
    TagListNode, TagAddNode, TagDetailNode, TagVideosNode, VideoTagsNode
)
from ..nodes.system import (
    ConfigNode, HealthNode as SystemHealthNode, StatusNode,
    DependenciesCheckNode, VideosClearNode, CheckFileNode,
    ThumbnailsRegenerateNode, ThumbnailStatusNode, ThumbnailProgressNode
)
from ..nodes.log import (
    LogsNode, LogDetailNode, LogDownloadNode,
    LogsClearNode, LogTypeClearNode, LogsSizeNode
)


def register_all_routes(node_manager: NodeManager):
    """
    注册所有路由到NodeManager

    Args:
        node_manager: NodeManager实例
    """

    # 健康检查
    node_manager.register_node('/health', SystemHealthNode(), ['GET'])
    node_manager.register_node('/api/health', HealthNode(), ['GET'])

    # 视频API
    node_manager.register_node('/api/videos', VideoListNode(), ['GET'])
    node_manager.register_node('/api/videos/recommend', VideoRecommendNode(), ['GET'])
    node_manager.register_node('/api/video/<video_hash>', VideoDetailNode(), ['GET'])
    node_manager.register_node('/api/video/<video_hash>', VideoDeleteNode(), ['DELETE'])
    node_manager.register_node('/api/video/<video_hash>/like', VideoLikeNode(), ['POST'])
    node_manager.register_node('/api/video/<video_hash>/download', VideoDetailNode(), ['GET', 'POST'])
    node_manager.register_node('/api/video/<video_hash>/priority', VideoDetailNode(), ['POST'])
    node_manager.register_node('/api/video/<video_hash>/regenerate', VideoDetailNode(), ['POST'])
    node_manager.register_node('/api/video/<video_hash>/favorite', VideoFavoriteNode(), ['POST'])
    node_manager.register_node('/api/video/<video_hash>/is-favorite', VideoFavoriteNode(), ['GET'])
    node_manager.register_node('/api/favorites', FavoritesNode(), ['GET'])
    node_manager.register_node('/api/video/upload', VideoUploadNode(), ['POST'])
    node_manager.register_node('/api/scan', VideoScanNode(), ['POST'])
    node_manager.register_node('/api/video/add', VideoAddNode(), ['POST'])
    node_manager.register_node('/api/videos/clear', VideosClearNode(), ['POST'])
    node_manager.register_node('/api/check-file', CheckFileNode(), ['POST'])

    # 缩略图
    node_manager.register_node('/api/thumbnail/<video_hash>/status', ThumbnailStatusNode(), ['GET'])
    node_manager.register_node('/api/thumbnails/regenerate', ThumbnailsRegenerateNode(), ['POST'])
    node_manager.register_node('/api/thumbnails/progress/<task_id>', ThumbnailProgressNode(), ['GET'])

    # 标签API
    node_manager.register_node('/api/tags', TagListNode(), ['GET'])
    node_manager.register_node('/api/tags/add', TagAddNode(), ['POST'])
    node_manager.register_node('/api/tags/<int:tag_id>', TagDetailNode(), ['GET', 'PUT', 'DELETE'])
    node_manager.register_node('/api/tags/<int:tag_id>/videos', TagVideosNode(), ['GET'])
    node_manager.register_node('/api/video/<video_hash>/tags', VideoTagsNode(), ['GET', 'PUT'])

    # 系统API
    node_manager.register_node('/api/config', ConfigNode(), ['GET', 'PUT'])
    node_manager.register_node('/api/status', StatusNode(), ['GET'])
    node_manager.register_node('/api/dependencies/check', DependenciesCheckNode(), ['GET'])

    # 日志API
    node_manager.register_node('/api/logs', LogsNode(), ['GET'])
    node_manager.register_node('/api/logs/<path:filepath>', LogDetailNode(), ['GET'])
    node_manager.register_node('/api/logs/download/<path:filepath>', LogDownloadNode(), ['GET'])
    node_manager.register_node('/api/logs/clear', LogsClearNode(), ['POST'])
    node_manager.register_node('/api/logs/clear/<log_type>', LogTypeClearNode(), ['POST'])
    node_manager.register_node('/api/logs/size', LogsSizeNode(), ['GET'])

    return node_manager


def get_registered_routes_count(node_manager: NodeManager) -> int:
    """
    获取已注册的路由数量

    Args:
        node_manager: NodeManager实例

    Returns:
        路由数量
    """
    routes = node_manager.get_registered_routes()
    return len(routes)
