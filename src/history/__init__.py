# -*- coding: utf-8 -*-
"""
播放历史服务

Service: com.dplayer.historyd
Interface: com.dplayer.Historyd
"""

from .models import WatchHistory, WatchHistoryDB
from .bus_adapter import BusHistoryAdapter

__all__ = ['WatchHistory', 'WatchHistoryDB', 'BusHistoryAdapter']
