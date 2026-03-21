# -*- coding: utf-8 -*-
"""
Adapters子模块

提供各种适配器：
- FlaskAdapter: Flask应用适配器
- DualRouter: 双轨路由系统
"""

from .flask import FlaskAdapter, DualRouter

__all__ = ['FlaskAdapter', 'DualRouter']
