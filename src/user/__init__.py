# -*- coding: utf-8 -*-
"""
用户管理模块

提供用户增删改查的独立服务，通过 ServiceBus 与其他服务通信。

服务: com.dbox.userd
"""

from .models import User, UserDB, UserRole, hash_password, verify_password
from .bus_adapter import BusUserAdapter

__all__ = [
    'User',
    'UserDB',
    'UserRole',
    'hash_password',
    'verify_password',
    'BusUserAdapter',
]