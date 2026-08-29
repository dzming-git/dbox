# -*- coding: utf-8 -*-
"""系统设置与配置辅助函数（分层设置 / 配置读写 / 日志行解析）。

从 main.py 下沉而来，供 system_api 蓝图直接 import。

需要运行时单例（app / app_config / buses）的地方，统一从
backend.runtime 读取。

注：原「电脑关机控制」与「服务管理（扫描/状态/健康）」两块已移除——
对应能力现由 system-power / service-ops 扩展插件提供，主服务不再持有。
"""
import os
import json

from liblog import get_service_logger

log = get_service_logger('dbox-web')
from backend.runtime import runtime


# ============ 分层设置（用户 / 全局 / 浏览器） ============
# 合并优先级（高 -> 低）：browser > user > global > defaults
SETTINGS_DEFAULTS = {
    # 播放
    'autoplay': False,
    'defaultQuality': 'auto',
    'subtitleLanguage': 'off',
    'autoContinue': True,
    'volume': 80,
    'loop': False,
    'playbackRate': 1.0,
    'subtitleFontSize': 24,
    'subtitleColor': '#ffffff',
    # 外观
    'theme': 'sunset-dark',
    'language': 'zh-CN',
    # 列表与展示
    'blockDisliked': False,
    'defaultSort': 'recommended',
    'defaultOrder': 'desc',
    # 弹幕（后端保留，前端暂未开放编辑）
    'danmakuOpacity': 1.0,
    'danmakuSpeed': 1.0,
    'danmakuFont': 24,
    'danmakuColor': '#ffffff',
    'danmakuArea': 1.0,
}


# 说明：设置持久化已统一收敛到 UserState（见 backend/user_state_service），
# 分 global / user 两层存储，由 /api/settings 读写；browser 层仍由前端
# localStorage 维护、不入库。此处不再保留按单键落库的旧实现（已废弃且从未被调用）。

# ============ 配置管理 ============
# 默认配置（不含任何个人路径）。首次启动时由代码生成到系统数据区的用户配置文件中，
# 项目目录不再存放用户运行时配置（避免个人路径污染仓库、被他人拉取后不可用）。
def _default_config():
    return {
        "scan_directories": [],  # 由用户在界面中添加，不预置个人路径
        "auto_scan_on_startup": False,
        "library_watch_enabled": True,
        "supported_formats": [".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"],
        "default_tags": [],
        "default_priority": 0,
        "watch_poll_interval": 5,
        "scan_interval_minutes": 60,
        "host": "0.0.0.0",
        "auto_start": True,
        "ports": {
            "web": 8080,
            "main_app": 8080,
            "admin_app": 8081,
            "thumbnail": 5001
        },
        # HTTPS / TLS 支持（呼应反馈 202608090002：禁用 http、使用 https、可配置）。
        # 默认不启用，保持向后兼容；启用后优先使用 cert_file/key_file，
        # 缺失时自动生成自签名证书（默认 10 年，CN=localhost）一次。
        "tls": {
            "enabled": False,
            "cert_file": "",
            "key_file": "",
            "port": 8443,
            # 为 True 且 TLS 正常启用后，仅监听 HTTPS、不再提供明文 HTTP；
            # 为 False 时同时提供 HTTPS(tls.port) 与 HTTP(ports.web) 便于过渡。
            "disable_http": False
        }
    }


def load_config():
    """加载用户运行时配置。

    配置存放在系统数据区的用户配置文件（默认 %LOCALAPPDATA%/Dbox/config/web_config.json），
    不纳入 git。若文件不存在，则用默认配置生成并写入（首次启动自动初始化）。

    合并策略：默认配置为底座，用户文件覆盖同名键，保证新增键有默认值兜底。
    """
    from backend.paths import CONFIG_FILE, USER_CONFIG_DIR, _ensure_user_dirs
    _ensure_user_dirs()
    default = _default_config()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                user_cfg = json.load(f)
            return {**default, **user_cfg}
        except Exception:
            pass
    # 首次启动：生成默认配置文件
    try:
        os.makedirs(USER_CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(default, f, indent=4, ensure_ascii=False)
    except Exception:
        pass
    return default


def save_config(cfg):
    from backend.paths import CONFIG_FILE, USER_CONFIG_DIR, _ensure_user_dirs
    _ensure_user_dirs()
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        log.debug('ERROR', f'保存配置失败: {e}')
        return False


# ============ 日志查看 ============
def parse_log_line(line: str, log_type: str) -> dict | None:
    """解析单行日志。

    格式:
    - maintenance/runtime/debug: [时间] | [等级] | [服务] | [内容]
    - operation: [时间] | [IP] | [服务] | [内容]
    """
    import re

    match = re.match(r'^\[([^\]]+)\]\s*\|\s*\[([^\]]+)\]\s*\|\s*\[([^\]]+)\]\s*\|\s*\[(.+)\]$', line)
    if not match:
        return None

    timestamp = match.group(1).strip()
    field2 = match.group(2).strip()
    service = match.group(3).strip()
    content = match.group(4).strip()

    result = {
        'timestamp': timestamp,
        'level': field2 if log_type != 'operation' else '',
        'source': field2 if log_type == 'operation' else '',
        'service': service,
        'content': content,
        'type': log_type,
        'user': ''
    }

    if log_type == 'operation':
        user_match = re.search(r'(?:用户|user)=([^|]+)', content)
        if user_match:
            result['user'] = user_match.group(1).strip()

    return result

