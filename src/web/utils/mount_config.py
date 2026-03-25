#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dplayer 挂载配置管理模块
支持灵活的多个文件夹挂载，通过配置文件统一管理
"""

import os
import json
from liblog import get_module_logger
from pathlib import Path
from typing import Dict, List, Optional

log = get_module_logger()


class MountConfig:
    """挂载配置管理类"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化挂载配置
        
        Args:
            config_path: 挂载配置文件路径，默认为 /config/mounts.json
        """
        self.config_path = config_path or os.environ.get(
            'DPLAYER_MOUNT_CONFIG',
            '/config/mounts.json'
        )
        self.mounts = {}
        self.load()
    
    def load(self):
        """加载挂载配置"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.mounts = data.get('mounts', {})
                log.runtime('INFO', f"加载挂载配置成功: {self.config_path}")
            else:
                # 使用默认配置
                self.mounts = self.get_default_mounts()
                log.runtime('INFO', f"挂载配置文件不存在，使用默认配置")
        except Exception as e:
            log.debug('ERROR', f"加载挂载配置失败: {e}")
            self.mounts = self.get_default_mounts()
    
    def get_default_mounts(self) -> Dict:
        """
        获取默认挂载配置
        
        Returns:
            默认挂载配置字典
        """
        return {
            "videos": {
                "source": "/data/videos",
                "target": "/app/videos",
                "description": "视频文件目录",
                "read_only": True
            },
            "thumbnails": {
                "source": "/data/thumbnails",
                "target": "/app/thumbnails",
                "description": "缩略图目录",
                "read_only": False
            },
            "uploads": {
                "source": "/data/uploads",
                "target": "/app/uploads",
                "description": "上传文件目录",
                "read_only": False
            },
            "static": {
                "source": "/data/static",
                "target": "/app/static",
                "description": "静态资源目录",
                "read_only": True
            },
            "cache": {
                "source": "/data/cache",
                "target": "/app/cache",
                "description": "缓存目录",
                "read_only": False
            }
        }
    
    def get_mount_path(self, mount_name: str) -> Optional[str]:
        """
        获取挂载点的目标路径
        
        Args:
            mount_name: 挂载点名称
            
        Returns:
            挂载点路径，如果不存在返回None
        """
        mount = self.mounts.get(mount_name)
        if mount:
            return mount.get('target')
        return None
    
    def get_source_path(self, mount_name: str) -> Optional[str]:
        """
        获取挂载点的源路径
        
        Args:
            mount_name: 挂载点名称
            
        Returns:
            源路径，如果不存在返回None
        """
        mount = self.mounts.get(mount_name)
        if mount:
            return mount.get('source')
        return None
    
    def is_read_only(self, mount_name: str) -> bool:
        """
        检查挂载点是否只读
        
        Args:
            mount_name: 挂载点名称
            
        Returns:
            是否只读
        """
        mount = self.mounts.get(mount_name)
        if mount:
            return mount.get('read_only', False)
        return False
    
    def get_all_mounts(self) -> Dict:
        """
        获取所有挂载配置
        
        Returns:
            所有挂载配置字典
        """
        return self.mounts
    
    def get_videos_path(self) -> str:
        """获取视频目录路径"""
        return self.get_mount_path('videos') or '/app/videos'
    
    def get_thumbnails_path(self) -> str:
        """获取缩略图目录路径"""
        return self.get_mount_path('thumbnails') or '/app/thumbnails'
    
    def get_uploads_path(self) -> str:
        """获取上传目录路径"""
        return self.get_mount_path('uploads') or '/app/uploads'
    
    def get_static_path(self) -> str:
        """获取静态资源目录路径"""
        return self.get_mount_path('static') or '/app/static'
    
    def get_cache_path(self) -> str:
        """获取缓存目录路径"""
        return self.get_mount_path('cache') or '/app/cache'
    
    def add_mount(self, name: str, source: str, target: str, 
                  description: str = "", read_only: bool = False):
        """
        添加挂载点
        
        Args:
            name: 挂载点名称
            source: 源路径
            target: 目标路径
            description: 描述
            read_only: 是否只读
        """
        self.mounts[name] = {
            'source': source,
            'target': target,
            'description': description,
            'read_only': read_only
        }
        log.runtime('INFO', f"添加挂载点: {name} -> {target}")
    
    def remove_mount(self, name: str):
        """
        移除挂载点
        
        Args:
            name: 挂载点名称
        """
        if name in self.mounts:
            del self.mounts[name]
            log.runtime('INFO', f"移除挂载点: {name}")
    
    def save(self, path: Optional[str] = None):
        """
        保存挂载配置到文件
        
        Args:
            path: 保存路径，默认为初始化时的路径
        """
        save_path = path or self.config_path
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump({'mounts': self.mounts}, f, indent=2, ensure_ascii=False)
            log.runtime('INFO', f"保存挂载配置成功: {save_path}")
        except Exception as e:
            log.debug('ERROR', f"保存挂载配置失败: {e}")
    
    def generate_docker_compose_volumes(self) -> List[str]:
        """
        生成Docker Compose格式的卷配置
        
        Returns:
            卷配置列表
        """
        volumes = []
        for name, mount in self.mounts.items():
            volumes.append(f"{mount['source']}:{mount['target']}")
            if mount.get('read_only', False):
                volumes[-1] += ':ro'
        return volumes
    
    def generate_docker_run_args(self) -> List[str]:
        """
        生成docker run命令的-v参数
        
        Returns:
            -v参数列表
        """
        args = []
        for name, mount in self.mounts.items():
            volume = f"{mount['source']}:{mount['target']}"
            if mount.get('read_only', False):
                volume += ':ro'
            args.append(f'-v {volume}')
        return args
    
    def print_mounts(self):
        """打印所有挂载配置"""
        print("\n" + "=" * 60)
        print("当前挂载配置")
        print("=" * 60)
        for name, mount in self.mounts.items():
            print(f"\n[{name}]")
            print(f"  源路径: {mount['source']}")
            print(f"  目标路径: {mount['target']}")
            print(f"  描述: {mount.get('description', 'N/A')}")
            print(f"  只读: {'是' if mount.get('read_only', False) else '否'}")
        print("=" * 60 + "\n")


# 全局挂载配置实例
_mount_config = None


def get_mount_config(config_path: Optional[str] = None) -> MountConfig:
    """
    获取全局挂载配置实例
    
    Args:
        config_path: 挂载配置文件路径
        
    Returns:
        挂载配置实例
    """
    global _mount_config
    if _mount_config is None:
        _mount_config = MountConfig(config_path)
    return _mount_config


def reload_mount_config():
    """重新加载挂载配置"""
    global _mount_config
    _mount_config = None


if __name__ == '__main__':
    # 测试代码
        config = MountConfig()
    config.print_mounts()
    
    print("\n生成Docker Compose卷配置:")
    volumes = config.generate_docker_compose_volumes()
    for vol in volumes:
        print(f"  - {vol}")
    
    print("\n生成docker run参数:")
    args = config.generate_docker_run_args()
    for arg in args:
        print(f"  {arg}")
