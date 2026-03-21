#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块

支持：
- 环境变量配置
- 配置文件加载
- 跨平台路径处理
- Docker部署支持
- 多实例部署支持

使用方法：
from config_manager import ConfigManager
config = ConfigManager()
db_path = config.get_db_path()
"""

import os
import sys
import platform
import json
from pathlib import Path
from typing import Optional, Dict, Any


class ConfigManager:
    """配置管理器"""

    def __init__(self):
        """初始化配置管理器"""
        self.platform = platform.system()  # Windows, Linux, Darwin
        self.is_docker = self._detect_docker()
        self.project_root = self._get_project_root()
        self.config_dir = self._get_config_dir()
        self.data_dir = self._get_data_dir()
        self.log_dir = self._get_log_dir()
        self.thumbnail_dir = self._get_thumbnail_dir()
        self.video_dir = self._get_video_dir()
        self.config = self._load_config()

        print(f"[配置管理] 平台: {self.platform}")
        print(f"[配置管理] Docker环境: {self.is_docker}")
        print(f"[配置管理] 项目根目录: {self.project_root}")
        print(f"[配置管理] 配置目录: {self.config_dir}")
        print(f"[配置管理] 数据目录: {self.data_dir}")
        print(f"[配置管理] 日志目录: {self.log_dir}")

    def _detect_docker(self) -> bool:
        """检测是否运行在Docker容器中"""
        # 检查.dockerenv文件
        if os.path.exists('/.dockerenv'):
            return True

        # 检查cgroup文件
        try:
            with open('/proc/1/cgroup', 'r') as f:
                if 'docker' in f.read():
                    return True
        except (FileNotFoundError, IOError):
            pass

        return False

    def _get_project_root(self) -> Path:
        """获取项目根目录"""
        # 在Docker中，项目根目录通常是/app
        if self.is_docker:
            return Path('/app')

        # 在本地开发中，获取当前脚本的目录
        current_path = Path(__file__).resolve().parent
        return current_path

    def _get_config_dir(self) -> Path:
        """获取配置文件目录"""
        # 优先使用环境变量
        config_dir = os.getenv('DPLAYER_CONFIG_DIR')
        if config_dir:
            return Path(config_dir)

        # 在Docker中，使用挂载的配置目录
        if self.is_docker:
            return Path('/config')

        # 在本地开发中，使用项目根目录
        return self.project_root

    def _get_data_dir(self) -> Path:
        """获取数据目录（数据库等）"""
        # 优先使用环境变量
        data_dir = os.getenv('DPLAYER_DATA_DIR')
        if data_dir:
            return Path(data_dir)

        # 在Docker中，使用挂载的数据目录
        if self.is_docker:
            return Path('/data')

        # 在本地开发中，使用项目根目录
        return self.project_root

    def _get_log_dir(self) -> Path:
        """获取日志目录"""
        # 优先使用环境变量
        log_dir = os.getenv('DPLAYER_LOG_DIR')
        if log_dir:
            return Path(log_dir)

        # 在Docker中，使用挂载的日志目录
        if self.is_docker:
            return Path('/logs')

        # 在本地开发中，使用logs目录
        log_path = self.project_root / 'logs'
        log_path.mkdir(exist_ok=True)
        return log_path

    def _get_thumbnail_dir(self) -> Path:
        """获取缩略图目录"""
        # 优先使用环境变量
        thumbnail_dir = os.getenv('DPLAYER_THUMBNAIL_DIR')
        if thumbnail_dir:
            return Path(thumbnail_dir)

        # 在Docker中，使用挂载的缩略图目录
        if self.is_docker:
            return Path('/data/thumbnails')

        # 在本地开发中，使用static/thumbnails目录
        thumbnail_path = self.project_root / 'static' / 'thumbnails'
        thumbnail_path.mkdir(parents=True, exist_ok=True)
        return thumbnail_path

    def _get_video_dir(self) -> Path:
        """获取视频目录"""
        # 优先使用环境变量
        video_dir = os.getenv('DPLAYER_VIDEO_DIR')
        if video_dir:
            return Path(video_dir)

        # 在Docker中，使用挂载的视频目录
        if self.is_docker:
            return Path('/data/videos')

        # 在本地开发中，使用项目根目录
        return self.project_root

    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        config_file = self.config_dir / 'config.json'

        # 默认配置
        default_config = {
            'host': '0.0.0.0',
            'port': 80,
            'debug': False,
            'secret_key': 'your-secret-key-here-change-in-production',
            'max_content_length': 500 * 1024 * 1024,
            'thumbnail_service': {
                'enabled': True,
                'url': 'http://localhost:5001',
                'fallback_enabled': True
            },
            'git': {
                'enabled': False,
                'user_name': '',
                'user_email': ''
            },
            'logging': {
                'level': 'INFO',
                'max_bytes': 10 * 1024 * 1024,
                'backup_count': 5
            }
        }

        # 如果配置文件存在，加载并合并
        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)

                # 合并配置
                def merge_dict(base, override):
                    result = base.copy()
                    for key, value in override.items():
                        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                            result[key] = merge_dict(result[key], value)
                        else:
                            result[key] = value
                    return result

                self.config = merge_dict(default_config, user_config)
                print(f"[配置管理] 已加载配置文件: {config_file}")
            except Exception as e:
                print(f"[配置管理] 加载配置文件失败: {e}，使用默认配置")
                self.config = default_config
        else:
            # 创建默认配置文件
            self.config = default_config
            self._save_config()

        # 应用环境变量覆盖
        self._apply_env_overrides()

        return self.config

    def _apply_env_overrides(self):
        """应用环境变量覆盖配置"""
        env_mappings = {
            'DPLAYER_HOST': ('host', str),
            'DPLAYER_PORT': ('port', int),
            'DPLAYER_DEBUG': ('debug', bool),
            'DPLAYER_SECRET_KEY': ('secret_key', str),
            'DPLAYER_MAX_CONTENT_LENGTH': ('max_content_length', int),
            'DPLAYER_THUMBNAIL_SERVICE_ENABLED': ('thumbnail_service.enabled', bool),
            'DPLAYER_THUMBNAIL_SERVICE_URL': ('thumbnail_service.url', str),
            'DPLAYER_THUMBNAIL_FALLBACK_ENABLED': ('thumbnail_service.fallback_enabled', bool),
            'DPLAYER_GIT_ENABLED': ('git.enabled', bool),
            'DPLAYER_GIT_USER_NAME': ('git.user_name', str),
            'DPLAYER_GIT_USER_EMAIL': ('git.user_email', str),
            'DPLAYER_LOG_LEVEL': ('logging.level', str),
        }

        for env_key, (config_path, value_type) in env_mappings.items():
            env_value = os.getenv(env_key)
            if env_value is not None:
                # 解析值
                if value_type == bool:
                    parsed_value = env_value.lower() in ('true', '1', 'yes')
                elif value_type == int:
                    parsed_value = int(env_value)
                else:
                    parsed_value = env_value

                # 设置配置值
                keys = config_path.split('.')
                config = self.config
                for key in keys[:-1]:
                    if key not in config:
                        config[key] = {}
                    config = config[key]
                config[keys[-1]] = parsed_value

                print(f"[配置管理] 环境变量覆盖: {env_key} = {parsed_value}")

    def _save_config(self):
        """保存配置文件"""
        config_file = self.config_dir / 'config.json'
        config_file.parent.mkdir(parents=True, exist_ok=True)

        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

        print(f"[配置管理] 配置文件已保存: {config_file}")

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        keys = key.split('.')
        config = self.config

        for k in keys:
            if isinstance(config, dict) and k in config:
                config = config[k]
            else:
                return default

        return config

    def set(self, key: str, value: Any):
        """设置配置值"""
        keys = key.split('.')
        config = self.config

        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        config[keys[-1]] = value
        self._save_config()

    def get_db_path(self) -> str:
        """获取数据库路径"""
        db_dir = self.data_dir
        db_dir.mkdir(parents=True, exist_ok=True)

        db_file = db_dir / 'dplayer.db'
        return f'sqlite:///{db_file}'

    def get_host(self) -> str:
        """获取主机地址"""
        return self.get('host', '0.0.0.0')

    def get_port(self) -> int:
        """获取端口号"""
        return self.get('port', 80)

    def get_debug(self) -> bool:
        """获取调试模式"""
        return self.get('debug', False)

    def get_secret_key(self) -> str:
        """获取密钥"""
        return self.get('secret_key', 'your-secret-key-here-change-in-production')

    def get_max_content_length(self) -> int:
        """获取最大上传大小"""
        return self.get('max_content_length', 500 * 1024 * 1024)

    def get_git_config(self) -> Dict[str, Any]:
        """获取Git配置"""
        return {
            'enabled': self.get('git.enabled', False),
            'user_name': self.get('git.user_name', ''),
            'user_email': self.get('git.user_email', '')
        }

    def get_thumbnail_service_config(self) -> Dict[str, Any]:
        """获取缩略图服务配置"""
        return {
            'enabled': self.get('thumbnail_service.enabled', True),
            'url': self.get('thumbnail_service.url', 'http://localhost:5001'),
            'fallback_enabled': self.get('thumbnail_service.fallback_enabled', True)
        }

    def get_logging_config(self) -> Dict[str, Any]:
        """获取日志配置"""
        return {
            'level': self.get('logging.level', 'INFO'),
            'max_bytes': self.get('logging.max_bytes', 10 * 1024 * 1024),
            'backup_count': self.get('logging.backup_count', 5)
        }

    def is_platform_windows(self) -> bool:
        """是否是Windows平台"""
        return self.platform == 'Windows'

    def is_platform_linux(self) -> bool:
        """是否是Linux平台"""
        return self.platform == 'Linux'

    def is_platform_macos(self) -> bool:
        """是否是macOS平台"""
        return self.platform == 'Darwin'


# 创建全局配置管理器实例
config_manager = None


def get_config_manager() -> ConfigManager:
    """获取配置管理器实例"""
    global config_manager
    if config_manager is None:
        config_manager = ConfigManager()
    return config_manager


def get_config() -> ConfigManager:
    """获取配置（别名）"""
    return get_config_manager()
