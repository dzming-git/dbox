# -*- coding: utf-8 -*-
"""
搜索服务

Service: com.dbox.searchd
Interface: com.dbox.Searchd
"""

from .models import SearchIndex, SearchDB
from .bus_adapter import BusSearchAdapter

__all__ = ['SearchIndex', 'SearchDB', 'BusSearchAdapter']
