# -*- coding: utf-8 -*-
"""
收藏夹服务

Service: com.dbox.collectiond
Interface: com.dbox.Collectiond
"""

from .models import Collection, CollectionItem, CollectionDB
from .bus_adapter import BusCollectionAdapter

__all__ = ['Collection', 'CollectionItem', 'CollectionDB', 'BusCollectionAdapter']
