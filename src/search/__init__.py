# -*- coding: utf-8 -*-
"""
搜索服务

Service: com.dplayer.searchd
Interface: com.dplayer.Searchd
"""

from .models import SearchIndex, SearchDB
from .bus_adapter import BusSearchAdapter

__all__ = ['SearchIndex', 'SearchDB', 'BusSearchAdapter']
