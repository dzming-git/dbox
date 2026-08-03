# -*- coding: utf-8 -*-
"""
BusHistoryAdapter - 播放历史服务的总线适配器

总线服务定义：

  Service:        com.dbox.historyd
  Interface:      com.dbox.Historyd
  Object Path:    /com/dbox/historyd

  Methods:
    RecordProgress(video_hash, user_id, progress, duration)
      → {success: bool, history: {...}}

    GetProgress(video_hash, user_id)
      → {success: bool, history?: {...}}

    GetWatchHistory(user_id, limit, offset)
      → {success: bool, history: [...], total: int}

    GetContinueWatch(user_id, limit)
      → {success: bool, history: [...]}

    MarkCompleted(video_hash, user_id)
      → {success: bool}

    DeleteHistory(history_id)
      → {success: bool}

    ClearUserHistory(user_id)
      → {success: bool, deleted: int}

    HealthCheck()
      → {status: str, history_count: int}
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
    from .models import WatchHistory, WatchHistoryDB
except ImportError:
    from models import WatchHistory, WatchHistoryDB

from servicebus.service_base import BaseDBusService


class BusHistoryAdapter(BaseDBusService):
    """
    播放历史服务总线适配器
    """

    BUS_NAME = 'com.dbox.historyd'
    INTERFACES = ['com.dbox.Historyd']
    OBJECT_PATH = '/com/dbox/historyd'

    def __init__(self, host: str = '127.0.0.1', rpc_port: int = 15555, pub_port: int = 15556):
        super().__init__(host, rpc_port, pub_port)

    # ============ 播放进度 ============

    def on_method_record_progress(self, params: Dict[str, Any]) -> Dict:
        """记录播放进度"""
        try:
            video_hash = params.get('video_hash', '').strip()
            user_id = params.get('user_id')
            progress = params.get('progress', 0.0)
            duration = params.get('duration', 0.0)

            if not video_hash:
                return {'success': False, 'error': '缺少 video_hash'}
            if user_id is None:
                return {'success': False, 'error': '缺少 user_id'}

            # 获取或创建记录
            history = WatchHistoryDB.get_or_create(video_hash, user_id)

            # 更新进度
            history.progress = float(progress)
            if duration > 0:
                history.duration = float(duration)

            # 自动标记完成（进度超过95%）
            if history.duration > 0 and history.progress >= history.duration * 0.95:
                history.completed = True

            WatchHistoryDB.update(history)

            return {
                'success': True,
                'history': history.to_dict(),
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_get_progress(self, params: Dict[str, Any]) -> Dict:
        """获取播放进度"""
        try:
            video_hash = params.get('video_hash', '').strip()
            user_id = params.get('user_id')

            if not video_hash:
                return {'success': False, 'error': '缺少 video_hash'}

            # 如果提供了 user_id，精确匹配
            if user_id is not None:
                history = WatchHistoryDB.get_by_hash_user(video_hash, user_id)
            else:
                # 否则获取任意用户的最新记录
                history = WatchHistoryDB.get_by_hash(video_hash)

            if not history:
                return {'success': True, 'history': None}

            return {
                'success': True,
                'history': history.to_dict(),
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 观看历史列表 ============

    def on_method_get_watch_history(self, params: Dict[str, Any]) -> Dict:
        """获取观看历史列表"""
        try:
            user_id = params.get('user_id')
            if user_id is None:
                return {'success': False, 'error': '缺少 user_id'}

            limit = params.get('limit', 50)
            offset = params.get('offset', 0)

            histories = WatchHistoryDB.get_watch_history(user_id, limit, offset)
            total = WatchHistoryDB.count(user_id)

            return {
                'success': True,
                'history': [h.to_dict() for h in histories],
                'total': total,
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_get_continue_watch(self, params: Dict[str, Any]) -> Dict:
        """获取继续观看列表（未看完的视频）"""
        try:
            user_id = params.get('user_id')
            if user_id is None:
                return {'success': False, 'error': '缺少 user_id'}

            limit = params.get('limit', 10)

            histories = WatchHistoryDB.get_continue_watch(user_id, limit)

            return {
                'success': True,
                'history': [h.to_dict() for h in histories],
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 完成标记 ============

    def on_method_mark_completed(self, params: Dict[str, Any]) -> Dict:
        """标记视频已看完"""
        try:
            video_hash = params.get('video_hash', '').strip()
            user_id = params.get('user_id')

            if not video_hash:
                return {'success': False, 'error': '缺少 video_hash'}
            if user_id is None:
                return {'success': False, 'error': '缺少 user_id'}

            history = WatchHistoryDB.get_by_hash_user(video_hash, user_id)
            if not history:
                return {'success': False, 'error': '播放历史不存在'}

            history.completed = True
            WatchHistoryDB.update(history)

            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 删除操作 ============

    def on_method_delete_history(self, params: Dict[str, Any]) -> Dict:
        """删除单条播放历史"""
        try:
            history_id = params.get('history_id')
            if history_id is None:
                return {'success': False, 'error': '缺少 history_id'}

            success = WatchHistoryDB.delete(history_id)
            return {'success': success}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_clear_user_history(self, params: Dict[str, Any]) -> Dict:
        """清空用户的所有播放历史"""
        try:
            user_id = params.get('user_id')
            if user_id is None:
                return {'success': False, 'error': '缺少 user_id'}

            deleted = WatchHistoryDB.delete_by_user(user_id)
            return {'success': True, 'deleted': deleted}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 健康检查 ============

    def on_method_health_check(self, params: Dict[str, Any]) -> Dict:
        """健康检查"""
        try:
            history_count = WatchHistoryDB.count()
            return {
                'status': 'healthy',
                'history_count': history_count,
            }
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
