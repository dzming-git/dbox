# -*- coding: utf-8 -*-
"""
BusSearchAdapter - 搜索服务的总线适配器

总线服务定义：

  Service:        com.dbox.searchd
  Interface:      com.dbox.Searchd
  Object Path:    /com/dbox/searchd

  Methods:
    IndexVideo(video_hash, title, description, tags, duration, library_id, path)
      → {success: bool, id: int}

    UpdateIndex(video_hash, fields)
      → {success: bool}

    DeleteFromIndex(video_hash)
      → {success: bool}

    Search(query, library_id, limit, offset)
      → {success: bool, results: [...], total: int}

    Suggest(keyword, limit)
      → {success: bool, suggestions: [...]}

    GetAllTags(library_id)
      → {success: bool, tags: [...]}

    RebuildIndex()
      → {success: bool}

    HealthCheck()
      → {status: str, indexed_count: int}
"""

import os
import sys
from datetime import datetime
from typing import Dict, Any, Optional

# 添加 src 目录到 path 以便导入 servicebus 和本地模块
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

# 支持直接运行和模块导入
try:
    from .models import SearchIndex, SearchDB
except ImportError:
    from models import SearchIndex, SearchDB

from servicebus.service_base import BaseDBusService


class BusSearchAdapter(BaseDBusService):
    """
    搜索服务总线适配器
    """

    BUS_NAME = 'com.dbox.searchd'
    INTERFACES = ['com.dbox.Searchd']
    OBJECT_PATH = '/com/dbox/searchd'

    def __init__(self, host: str = '127.0.0.1', rpc_port: int = 15555, pub_port: int = 15556):
        super().__init__(host, rpc_port, pub_port)

    # ============ 索引管理 ============

    def on_method_index_video(self, params: Dict[str, Any]) -> Dict:
        """索引视频"""
        try:
            video_hash = params.get('video_hash', '').strip()
            if not video_hash:
                return {'success': False, 'error': '缺少 video_hash'}

            index = SearchIndex(
                video_hash=video_hash,
                title=params.get('title', ''),
                description=params.get('description', ''),
                tags=params.get('tags', ''),
                duration=params.get('duration', 0.0),
                library_id=params.get('library_id', 0),
                path=params.get('path', ''),
            )

            index_id = SearchDB.index_video(index)

            return {
                'success': True,
                'id': index_id,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_update_index(self, params: Dict[str, Any]) -> Dict:
        """更新索引"""
        try:
            video_hash = params.get('video_hash', '').strip()
            if not video_hash:
                return {'success': False, 'error': '缺少 video_hash'}

            existing = SearchDB.get_by_hash(video_hash)
            if not existing:
                return {'success': False, 'error': '索引不存在'}

            # 更新字段
            if 'title' in params:
                existing.title = params['title']
            if 'description' in params:
                existing.description = params['description']
            if 'tags' in params:
                existing.tags = params['tags']
            if 'duration' in params:
                existing.duration = params['duration']
            if 'path' in params:
                existing.path = params['path']

            SearchDB.index_video(existing)

            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_delete_from_index(self, params: Dict[str, Any]) -> Dict:
        """从索引删除"""
        try:
            video_hash = params.get('video_hash', '').strip()
            if not video_hash:
                return {'success': False, 'error': '缺少 video_hash'}

            success = SearchDB.delete_by_hash(video_hash)
            return {'success': success}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 搜索 ============

    def on_method_search(self, params: Dict[str, Any]) -> Dict:
        """全文搜索"""
        try:
            query = params.get('query', '').strip()
            library_id = params.get('library_id')  # 可选
            limit = params.get('limit', 50)
            offset = params.get('offset', 0)

            if not query:
                return {'success': False, 'error': '缺少查询词'}

            # 限制参数范围
            limit = max(1, min(limit, 100))

            results, total = SearchDB.search(query, library_id, limit, offset)

            return {
                'success': True,
                'results': results,
                'total': total,
                'query': query,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_suggest(self, params: Dict[str, Any]) -> Dict:
        """获取搜索建议"""
        try:
            keyword = params.get('keyword', '').strip()
            limit = params.get('limit', 10)

            if not keyword:
                return {'success': True, 'suggestions': []}

            limit = max(1, min(limit, 20))
            suggestions = SearchDB.suggest(keyword, limit)

            return {
                'success': True,
                'suggestions': suggestions,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_get_all_tags(self, params: Dict[str, Any]) -> Dict:
        """获取所有标签"""
        try:
            library_id = params.get('library_id')  # 可选
            tags = SearchDB.get_all_tags(library_id)

            return {
                'success': True,
                'tags': tags,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_rebuild_index(self, params: Dict[str, Any]) -> Dict:
        """重建索引"""
        try:
            SearchDB.rebuild_index()
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 健康检查 ============

    def on_method_health_check(self, params: Dict[str, Any]) -> Dict:
        """健康检查"""
        try:
            # 获取索引数量
            with SearchDB.get_cursor() as cursor:
                cursor.execute('SELECT COUNT(*) FROM search_index')
                count = cursor.fetchone()[0]
            return {
                'status': 'healthy',
                'indexed_count': count,
            }
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
