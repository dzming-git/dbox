# -*- coding: utf-8 -*-
"""集中管理项目路径常量，避免在各模块重复推导或硬编码绝对路径。"""
import os

# _THIS_DIR: src/web/backend/
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# WEB_DIR: src/web/
WEB_DIR = os.path.dirname(_THIS_DIR)
# SRC_DIR: src/
SRC_DIR = os.path.dirname(WEB_DIR)
# PROJECT_ROOT: 项目根目录 (Dplayer2.0/)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
# CONFIGS_DIR: configs/
CONFIGS_DIR = os.path.join(PROJECT_ROOT, 'configs')
# DATA_DIR: data/
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
# 缩略图配置文件
THUMB_CONFIG_FILE = os.path.join(DATA_DIR, 'thumbnail_config.json')
# Web 配置文件
WEB_CONFIG_FILE = os.path.join(CONFIGS_DIR, 'web', 'config.json')
# 兼容别名（历史 main.py 使用 CONFIG_FILE）
CONFIG_FILE = WEB_CONFIG_FILE
