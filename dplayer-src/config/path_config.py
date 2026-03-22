#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DPlayer - 路径配置模块

提供运行目录的动态解析，确保服务可以在任何位置运行，不依赖硬编码路径。
"""

import os
import json
from pathlib import Path


def get_runtime_dir() -> Path:
    """
    获取运行目录，优先级：
    1. 环境变量 DPLAYER_RUNTIME
    2. 当前文件所在目录的上一级（即项目根目录）
    3. 从 install.json 读取（如果存在）
    
    Returns:
        Path: 运行目录的绝对路径
    """
    # 1. 环境变量优先级最高
    if env_dir := os.environ.get('DPLAYER_RUNTIME'):
        path = Path(env_dir).resolve()
        if path.exists():
            return path
    
    # 2. 尝试从 install.json 读取（如果存在）
    # 先尝试当前工作目录
    cwd = Path.cwd()
    install_json = cwd / 'install.json'
    if install_json.exists():
        try:
            data = json.loads(install_json.read_text(encoding='utf-8'))
            if runtime_dir := data.get('runtime_dir'):
                path = Path(runtime_dir).resolve()
                if path.exists():
                    return path
        except Exception:
            pass
    
    # 3. 基于当前文件动态解析
    # 本文件位于 config/path_config.py，项目根目录是上一级
    return Path(__file__).parent.parent.resolve()


def get_source_dir() -> Path | None:
    """
    获取源码目录（从 install.json 读取）
    
    Returns:
        Path | None: 源码目录，如果无法确定则返回 None
    """
    runtime_dir = get_runtime_dir()
    install_json = runtime_dir / 'install.json'
    
    if install_json.exists():
        try:
            data = json.loads(install_json.read_text(encoding='utf-8'))
            if source_dir := data.get('source_dir'):
                path = Path(source_dir).resolve()
                if path.exists():
                    return path
        except Exception:
            pass
    
    return None


# 运行目录（动态解析）
RUNTIME_DIR = get_runtime_dir()

# 所有路径均基于 RUNTIME_DIR
DATABASE_PATH = RUNTIME_DIR / 'instance' / 'dplayer.db'
UPLOAD_DIR = RUNTIME_DIR / 'uploads'
LOG_DIR = RUNTIME_DIR / 'logs'
STATIC_DIR = RUNTIME_DIR / 'static'
TEMPLATE_DIR = RUNTIME_DIR / 'templates'
CONFIG_DIR = RUNTIME_DIR / 'config'
INSTANCE_DIR = RUNTIME_DIR / 'instance'

# 路径字典（方便序列化）
PATHS = {
    'runtime': str(RUNTIME_DIR),
    'database': str(DATABASE_PATH),
    'uploads': str(UPLOAD_DIR),
    'logs': str(LOG_DIR),
    'static': str(STATIC_DIR),
    'templates': str(TEMPLATE_DIR),
    'config': str(CONFIG_DIR),
    'instance': str(INSTANCE_DIR),
}


def ensure_directories():
    """确保所有必要的目录都存在"""
    for path in [UPLOAD_DIR, LOG_DIR, STATIC_DIR, INSTANCE_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def get_version() -> str:
    """获取当前版本号"""
    version_file = RUNTIME_DIR / 'VERSION'
    if version_file.exists():
        return version_file.read_text(encoding='utf-8').strip()
    return '2.0.0'


def get_install_info() -> dict | None:
    """获取安装信息"""
    install_json = RUNTIME_DIR / 'install.json'
    if install_json.exists():
        try:
            return json.loads(install_json.read_text(encoding='utf-8'))
        except Exception:
            pass
    return None


if __name__ == '__main__':
    # 测试模式
    print('DPlayer 路径配置')
    print('=' * 60)
    print(f'运行目录: {RUNTIME_DIR}')
    print(f'源码目录: {get_source_dir() or "N/A (未安装)"}')
    print(f'版本号: {get_version()}')
    print('-' * 60)
    print('路径配置:')
    for key, value in PATHS.items():
        print(f'  {key:12s}: {value}')
    print('-' * 60)
    
    install_info = get_install_info()
    if install_info:
        print('安装信息:')
        print(f'  安装时间: {install_info.get("install_time", "N/A")}')
        print(f'  是否更新: {install_info.get("update", False)}')
    else:
        print('安装信息: 未安装（直接从源码运行）')
