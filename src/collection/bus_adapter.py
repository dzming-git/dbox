# -*- coding: utf-8 -*-
"""
BusCollectionAdapter - 收藏夹服务的总线适配器

总线服务定义：

  Service:        com.dplayer.collectiond
  Interface:      com.dplayer.Collectiond
  Object Path:    /com/dplayer/collectiond

  Methods:
    CreateCollection(name, description, user_id, is_public)
      → {success: bool, collection: {...}}

    GetCollection(collection_id)
      → {success: bool, collection?: {...}}

    ListCollections(user_id, include_public)
      → {success: bool, collections: [...]}

    UpdateCollection(collection_id, fields)
      → {success: bool, collection: {...}}

    DeleteCollection(collection_id)
      → {success: bool}

    AddToCollection(collection_id, video_hash, note)
      → {success: bool, item_id: int}

    RemoveFromCollection(collection_id, video_hash)
      → {success: bool}

    GetCollectionItems(collection_id, page, limit)
      → {success: bool, items: [...], total: int}

    IsInCollection(collection_id, video_hash)
      → {success: bool, is_in: bool}

    GetCollectionsForVideo(video_hash, user_id)
      → {success: bool, collections: [...]}

    UpdateItemNote(collection_id, video_hash, note)
      → {success: bool}

    HealthCheck()
      → {status: str, collection_count: int}
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
    from .models import Collection, CollectionItem, CollectionDB
except ImportError:
    from models import Collection, CollectionItem, CollectionDB

from servicebus.service_base import BaseDBusService


class BusCollectionAdapter(BaseDBusService):
    """
    收藏夹服务总线适配器
    """

    BUS_NAME = 'com.dplayer.collectiond'
    INTERFACES = ['com.dplayer.Collectiond']
    OBJECT_PATH = '/com/dplayer/collectiond'

    def __init__(self, host: str = '127.0.0.1', rpc_port: int = 15555, pub_port: int = 15556):
        super().__init__(host, rpc_port, pub_port)

    # ============ 收藏夹管理 ============

    def on_method_create_collection(self, params: Dict[str, Any]) -> Dict:
        """创建收藏夹"""
        try:
            name = params.get('name', '').strip()
            user_id = params.get('user_id')
            description = params.get('description', '').strip()
            is_public = params.get('is_public', False)

            if not name:
                return {'success': False, 'error': '收藏夹名称不能为空'}
            if user_id is None:
                return {'success': False, 'error': '缺少 user_id'}

            collection = Collection(
                name=name,
                description=description,
                user_id=user_id,
                is_public=bool(is_public),
            )
            collection_id = CollectionDB.create_collection(collection)
            collection.id = collection_id

            return {
                'success': True,
                'collection': collection.to_dict(),
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_get_collection(self, params: Dict[str, Any]) -> Dict:
        """获取收藏夹详情"""
        try:
            collection_id = params.get('collection_id')
            if collection_id is None:
                return {'success': False, 'error': '缺少 collection_id'}

            collection = CollectionDB.get_collection_by_id(collection_id)
            if not collection:
                return {'success': False, 'error': '收藏夹不存在'}

            return {
                'success': True,
                'collection': collection.to_dict(),
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_list_collections(self, params: Dict[str, Any]) -> Dict:
        """列出用户的收藏夹"""
        try:
            user_id = params.get('user_id')
            if user_id is None:
                return {'success': False, 'error': '缺少 user_id'}

            include_public = params.get('include_public', True)
            collections = CollectionDB.get_collections_by_user(user_id, include_public)

            return {
                'success': True,
                'collections': [c.to_dict() for c in collections],
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_update_collection(self, params: Dict[str, Any]) -> Dict:
        """更新收藏夹"""
        try:
            collection_id = params.get('collection_id')
            if collection_id is None:
                return {'success': False, 'error': '缺少 collection_id'}

            collection = CollectionDB.get_collection_by_id(collection_id)
            if not collection:
                return {'success': False, 'error': '收藏夹不存在'}

            # 更新字段
            if 'name' in params:
                name = params['name'].strip()
                if name:
                    collection.name = name
            if 'description' in params:
                collection.description = params['description'].strip()
            if 'is_public' in params:
                collection.is_public = bool(params['is_public'])

            CollectionDB.update_collection(collection)

            return {
                'success': True,
                'collection': collection.to_dict(),
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_delete_collection(self, params: Dict[str, Any]) -> Dict:
        """删除收藏夹"""
        try:
            collection_id = params.get('collection_id')
            if collection_id is None:
                return {'success': False, 'error': '缺少 collection_id'}

            success = CollectionDB.delete_collection(collection_id)
            return {'success': success}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 收藏夹条目管理 ============

    def on_method_add_to_collection(self, params: Dict[str, Any]) -> Dict:
        """添加视频到收藏夹"""
        try:
            collection_id = params.get('collection_id')
            video_hash = params.get('video_hash', '').strip()
            note = params.get('note', '').strip()

            if collection_id is None:
                return {'success': False, 'error': '缺少 collection_id'}
            if not video_hash:
                return {'success': False, 'error': '缺少 video_hash'}

            # 检查收藏夹是否存在
            collection = CollectionDB.get_collection_by_id(collection_id)
            if not collection:
                return {'success': False, 'error': '收藏夹不存在'}

            item_id = CollectionDB.add_to_collection(collection_id, video_hash, note)

            return {
                'success': True,
                'item_id': item_id,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_remove_from_collection(self, params: Dict[str, Any]) -> Dict:
        """从收藏夹移除视频"""
        try:
            collection_id = params.get('collection_id')
            video_hash = params.get('video_hash', '').strip()

            if collection_id is None:
                return {'success': False, 'error': '缺少 collection_id'}
            if not video_hash:
                return {'success': False, 'error': '缺少 video_hash'}

            success = CollectionDB.remove_from_collection(collection_id, video_hash)
            return {'success': success}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_get_collection_items(self, params: Dict[str, Any]) -> Dict:
        """获取收藏夹中的视频列表"""
        try:
            collection_id = params.get('collection_id')
            if collection_id is None:
                return {'success': False, 'error': '缺少 collection_id'}

            page = params.get('page', 1)
            limit = params.get('limit', 50)

            items, total = CollectionDB.get_collection_items(collection_id, page, limit)

            return {
                'success': True,
                'items': [item.to_dict() for item in items],
                'total': total,
                'page': page,
                'limit': limit,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_is_in_collection(self, params: Dict[str, Any]) -> Dict:
        """检查视频是否在收藏夹中"""
        try:
            collection_id = params.get('collection_id')
            video_hash = params.get('video_hash', '').strip()

            if collection_id is None:
                return {'success': False, 'error': '缺少 collection_id'}
            if not video_hash:
                return {'success': False, 'error': '缺少 video_hash'}

            is_in = CollectionDB.is_in_collection(collection_id, video_hash)
            return {
                'success': True,
                'is_in': is_in,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_get_collections_for_video(self, params: Dict[str, Any]) -> Dict:
        """获取包含指定视频的所有收藏夹"""
        try:
            video_hash = params.get('video_hash', '').strip()
            user_id = params.get('user_id')

            if not video_hash:
                return {'success': False, 'error': '缺少 video_hash'}

            collections = CollectionDB.get_collections_for_video(video_hash, user_id)

            return {
                'success': True,
                'collections': [c.to_dict() for c in collections],
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_update_item_note(self, params: Dict[str, Any]) -> Dict:
        """更新收藏条目的备注"""
        try:
            collection_id = params.get('collection_id')
            video_hash = params.get('video_hash', '').strip()
            note = params.get('note', '')

            if collection_id is None:
                return {'success': False, 'error': '缺少 collection_id'}
            if not video_hash:
                return {'success': False, 'error': '缺少 video_hash'}

            success = CollectionDB.update_item_note(collection_id, video_hash, note)
            return {'success': success}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 健康检查 ============

    def on_method_health_check(self, params: Dict[str, Any]) -> Dict:
        """健康检查"""
        try:
            collections = CollectionDB.get_collections_by_user(0)  # 获取总数
            return {
                'status': 'healthy',
                'collection_count': len(collections),
            }
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
