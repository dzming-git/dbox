#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行时产物（数据库 / 日志 / 缓存 / 凭证）落点的唯一解析入口。

硬约定：**运行时产物绝不落项目源码树**。

历史上这里栽过跟头：十几处代码各自写了一份「环境变量没设就往上几级找项目根的
data/」的兜底，一旦环境变量缺失（NSSM 服务重装、整个目录被搬走、手动起服务、
以 LocalSystem 运行的服务看不到用户级环境），日志和数据库就悄悄写进了项目目录——
于是它们会跟着代码一起被搬、被 git 看到、被当成源码分发，而且换台机器/换个目录
会「莫名其妙丢数据」。

本模块只做路径解析，不依赖任何业务代码，供各微服务、扩展宿主、脚本共用；规则与
src/web/backend/paths.py（数据/配置区）和 src/liblog/logger.py（日志）保持一致：

- 数据根：DBOX_DATA_DIR → <DBOX_DATA_ROOT>/data（默认 C:\\ProgramData\\Dbox/data）
        → 平台系统数据区（%LOCALAPPDATA%/Dbox/data，公共区不可写时兜底）
- 配置区：DBOX_USER_CONFIG_DIR → <DBOX_DATA_ROOT>/config → %LOCALAPPDATA%/Dbox/config
- 日志：DBOX_LOG_DIR → 数据根/logs（服务应显式设置，避免写到服务账户的用户目录）

用法（各微服务的 models.py 里也用了同样的写法，含不依赖 import 的等价兜底）：:

    from shared.data_paths import databases_dir, logs_dir
    _DB_PATH = os.path.join(databases_dir(), 'history.db')
"""
import os
import sys

# 目录名常量：与既有约定保持一致，改这里等于改全局
_DATABASES = 'databases'
_LOGS = 'logs'
_PLUGINS = 'plugins'
_THUMBNAILS = 'thumbnails'
_TRASH = 'trash'
_CACHE = 'cache'
_FEEDBACK_SPOOL = 'feedback_spool'
_UPLOADS = 'uploads'
INTERNAL_KEY_FILENAME = '.dbox_internal_key'


def public_data_root() -> str:
    """公共数据区根目录（多服务共享，避开用户目录权限问题）。

    DBOX_DATA_ROOT 可覆盖；默认 Windows: C:\\ProgramData\\Dbox，Linux/macOS: /var/lib/Dbox。
    """
    env = os.environ.get('DBOX_DATA_ROOT')
    if env:
        return env
    if sys.platform.startswith('win'):
        return r'C:\ProgramData\Dbox'
    return '/var/lib/Dbox'


def _system_data_root() -> str:
    """平台系统数据区（用户级，公共区不可写时的兜底）。"""
    if sys.platform.startswith('win'):
        local = os.environ.get('LOCALAPPDATA')
        if local:
            return local
        return os.path.expanduser('~\\AppData\\Local')
    return os.path.expanduser('~/.local/share')


def _is_writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        test = os.path.join(path, '.write_test')
        with open(test, 'w') as f:
            f.write('')
        os.remove(test)
        return True
    except Exception:
        return False


def data_root() -> str:
    """运行时数据根目录（数据库/缩略图/插件私有数据/回收站等都挂在它下面）。"""
    env = os.environ.get('DBOX_DATA_DIR')
    if env:
        return env
    public = os.path.join(public_data_root(), 'data')
    if os.path.isdir(public) or _is_writable(public):
        return public
    return os.path.join(_system_data_root(), 'Dbox', 'data')


def config_root() -> str:
    """运行时配置区（web_config.json / thumbnail_config.json 等）。"""
    env = os.environ.get('DBOX_USER_CONFIG_DIR')
    if env:
        return env
    public = os.path.join(public_data_root(), 'config')
    if os.path.isdir(public) or _is_writable(public):
        return public
    return os.path.join(_system_data_root(), 'Dbox', 'config')


def logs_dir() -> str:
    """日志目录。

    默认与 src/liblog/logger.py 一致；服务场景建议显式设置 DBOX_LOG_DIR 指向
    机器级目录（服务常以 LocalSystem 运行，用户级目录不是人找得到的地方）。
    """
    env = os.environ.get('DBOX_LOG_DIR')
    if env:
        return env
    return os.path.join(data_root(), _LOGS)


def databases_dir() -> str:
    """sqlite 数据库目录。"""
    return os.path.join(data_root(), _DATABASES)


def plugins_dir(key: str = None) -> str:
    """插件私有数据目录（传 key 则为其子目录）。"""
    base = os.path.join(data_root(), _PLUGINS)
    return os.path.join(base, key) if key else base


def thumbnails_dir() -> str:
    return os.path.join(data_root(), _THUMBNAILS)


def trash_dir() -> str:
    return os.path.join(data_root(), _TRASH)


def cache_root() -> str:
    return os.path.join(data_root(), _CACHE)


def uploads_dir(library_id=None) -> str:
    """入库落盘目录：库没配 path 时的持久存储位置。"""
    base = os.path.join(data_root(), _UPLOADS)
    return os.path.join(base, 'lib_%s' % library_id) if library_id is not None else base


def feedback_spool_dir() -> str:
    return os.path.join(data_root(), _FEEDBACK_SPOOL)


def internal_key_path() -> str:
    """主服务与扩展宿主共享的进程间内部密钥（两端必须指向同一份）。"""
    return os.path.join(data_root(), INTERNAL_KEY_FILENAME)


def data_root_candidates() -> list:
    """可能的数据根候选（按优先级），用于「找一份已存在的文件」。"""
    out = []
    for p in (os.environ.get('DBOX_DATA_DIR'), os.path.join(public_data_root(), 'data'),
              os.path.join(_system_data_root(), 'Dbox', 'data')):
        if p and p not in out:
            out.append(p)
    return out


def ensure(dir_path: str) -> str:
    """确保目录存在并返回它（失败不抛，交给调用方按需处理）。"""
    try:
        os.makedirs(dir_path, exist_ok=True)
    except Exception:
        pass
    return dir_path
