# -*- coding: utf-8 -*-
"""集中管理项目路径常量，避免在各模块重复推导或硬编码绝对路径。

路径分为两类：
1. 项目路径（PROJECT_ROOT / SRC_DIR / WEB_DIR 等）：源码与只读资源，随 git 版本控制。
2. 用户数据区（USER_CONFIG_DIR / USER_DATA_DIR）：运行时由用户/实例产生的配置、
   数据库、缩略图等，不属于项目，应存放在系统数据区（不纳入 git）。

用户数据区解析优先级：
- 环境变量 DBOX_USER_CONFIG_DIR / DBOX_DATA_DIR 显式指定 → 最高优先级；
- 否则使用公共数据区（多服务共享、避免用户目录权限问题）：
    Windows: C:\\ProgramData\\Dbox\\data
    Linux/macOS: /var/lib/Dbox/data  (macOS 也可接受)
  公共数据区的根可通过环境变量 DBOX_DATA_ROOT 覆盖（如 DBOX_DATA_ROOT=C:\\ProgramData\\Dbox）。
- 最后兜底使用平台系统数据区（仅当公共数据区不可写时）：
    Windows: %LOCALAPPDATA%/Dbox
    Linux/macOS: ~/.local/share/Dbox
- 首次启动时若系统数据区为空且项目根目录下存在旧 data/（历史遗留），会自动迁移一次，
  保证已有开发数据不丢失，之后完全使用系统数据区。
"""
import os
import sys
import shutil


# 测试隔离的强制覆盖目录（模块级，不依赖环境变量持久性——否则会被别的测试
# 模块层 os.environ.pop('DBOX_DATA_DIR') 之类操作扒掉，导致隔离失效）。
_DATA_DIR_OVERRIDE = None
_CONFIG_DIR_OVERRIDE = None


def _ensure_test_isolation():
    """测试隔离：在测试上下文下运行，强制把数据区指到临时目录。

    ⚠️ 为什么（2026-09-18 事故）：某测试 `import main` 后 `db.drop_all()` 曾把生产库
    整表删空。包级 `tests/__init__.py` 只对 `python -m unittest tests.xxx` 生效
    （先导入包）；直接 `python tests/xxx.py` 会绕过它。此处在 paths 解析数据目录前、
    依据通用信号强制隔离，覆盖两种跑法：
      - `unittest` 在 sys.modules（两种跑法里测试文件都先 import unittest）；
      - 环境变量 DBOX_TEST_MODE（tests/__init__.py 已设，冗余兜底）；
      - sys.argv[0] 落在 tests/ 下（即使测试文件未先 import unittest 也能兜住）。
    只在测试上下文触发；正常启动（服务/NSSM）三个信号皆无，绝不影响生产数据区。
    """
    in_test = (
        'unittest' in sys.modules
        or os.environ.get('DBOX_TEST_MODE') == '1'
        or any('tests' in a for a in sys.argv)
    )
    global _DATA_DIR_OVERRIDE, _CONFIG_DIR_OVERRIDE
    if not in_test:
        return
    # 测试上下文：强制临时目录。即便 tests/__init__.py 已预设了临时目录，也捕获到
    # 模块级覆盖里，避免被别的测试模块层 os.environ.pop('DBOX_DATA_DIR') 扒掉。
    env_dir = os.environ.get('DBOX_DATA_DIR')
    if env_dir and 'dbox_tests_' in env_dir:
        _DATA_DIR_OVERRIDE = env_dir
        _CONFIG_DIR_OVERRIDE = (os.environ.get('DBOX_USER_CONFIG_DIR')
                                or env_dir.rsplit('data', 1)[0] + 'config')
        return
    import tempfile
    _tmp = tempfile.mkdtemp(prefix='dbox_tests_')
    _DATA_DIR_OVERRIDE = os.path.join(_tmp, 'data')
    _CONFIG_DIR_OVERRIDE = os.path.join(_tmp, 'config')
    os.environ.setdefault('DBOX_DATA_DIR', _DATA_DIR_OVERRIDE)
    os.environ.setdefault('DBOX_USER_CONFIG_DIR', _CONFIG_DIR_OVERRIDE)


_ensure_test_isolation()


# _THIS_DIR: src/web/backend/
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
# WEB_DIR: src/web/
WEB_DIR = os.path.dirname(_THIS_DIR)
# SRC_DIR: src/
SRC_DIR = os.path.dirname(WEB_DIR)
# PROJECT_ROOT: 项目根目录 (Dbox2.0/)
PROJECT_ROOT = os.path.dirname(SRC_DIR)
# CONFIGS_DIR: configs/（项目内的静态/示例配置，非用户运行时配置）
CONFIGS_DIR = os.path.join(PROJECT_ROOT, 'configs')


def _system_data_root():
    """平台默认的系统数据区根目录（不含应用子目录）。"""
    env = os.environ.get('DBOX_SYSTEM_DATA')
    if env:
        return env
    if sys.platform.startswith('win'):
        local = os.environ.get('LOCALAPPDATA')
        if local:
            return local
        # 兜底：Windows 下 LOCALAPPDATA 缺失时回退到用户目录
        return os.path.expanduser('~\\AppData\\Local')
    # Linux / macOS
    return os.path.expanduser('~/.local/share')


def _public_data_root():
    """公共数据区根目录（多服务共享，避开用户目录权限问题）。

    可通过环境变量 DBOX_DATA_ROOT 覆盖（如 DBOX_DATA_ROOT=C:\\ProgramData\\Dbox）。
    默认 Windows: C:\\ProgramData\\Dbox；Linux/macOS: /var/lib/Dbox。
    """
    env = os.environ.get('DBOX_DATA_ROOT')
    if env:
        return env
    if sys.platform.startswith('win'):
        return r'C:\ProgramData\Dbox'
    return '/var/lib/Dbox'


def get_user_data_dir():
    """用户数据根目录（数据库、缩略图等运行时数据）。

    优先级：
    1. 环境变量 DBOX_DATA_DIR（显式指定完整 data 目录）
    2. 公共数据区下的 Dbox/data（DBOX_DATA_ROOT 可覆盖根，默认 C:\\ProgramData\\Dbox）
    3. 平台系统数据区下的 Dbox/data（兜底，仅当公共区不可写）
    首次启动做一次从项目根 data/ 的迁移（仅当系统区为空且项目 data 存在）。
    """
    if _DATA_DIR_OVERRIDE:
        return _DATA_DIR_OVERRIDE
    env = os.environ.get('DBOX_DATA_DIR')
    if env:
        return env
    public = os.path.join(_public_data_root(), 'data')
    if os.path.isdir(public) or _is_writable(public):
        return public
    return os.path.join(_system_data_root(), 'Dbox', 'data')


def get_user_config_dir():
    """用户配置根目录（web_config.json 等运行时配置）。

    优先级：
    1. 环境变量 DBOX_USER_CONFIG_DIR
    2. 公共数据区下的 Dbox/config（DBOX_DATA_ROOT 可覆盖根）
    3. 平台系统数据区下的 Dbox/config（兜底）
    """
    if _CONFIG_DIR_OVERRIDE:
        return _CONFIG_DIR_OVERRIDE
    env = os.environ.get('DBOX_USER_CONFIG_DIR')
    if env:
        return env
    public = os.path.join(_public_data_root(), 'config')
    if os.path.isdir(public) or _is_writable(public):
        return public
    return os.path.join(_system_data_root(), 'Dbox', 'config')


def _is_writable(path):
    """判断目录是否可写（不存在则尝试创建并清理，存在则试建临时文件）。"""
    try:
        os.makedirs(path, exist_ok=True)
        test = os.path.join(path, '.write_test')
        with open(test, 'w') as f:
            f.write('')
        os.remove(test)
        return True
    except Exception:
        return False


# 用户数据区（运行时生成，不纳入 git）
DATA_DIR = get_user_data_dir()
# 用户配置区（运行时生成，不纳入 git）
USER_CONFIG_DIR = get_user_config_dir()

# 缩略图配置文件（用户配置区，而非项目目录）
THUMB_CONFIG_FILE = os.path.join(USER_CONFIG_DIR, 'thumbnail_config.json')
# Web 运行时配置文件（用户数据区，首次启动由代码生成）
WEB_CONFIG_FILE = os.path.join(USER_CONFIG_DIR, 'web_config.json')
# 兼容别名（历史 main.py 使用 CONFIG_FILE）
CONFIG_FILE = WEB_CONFIG_FILE


def _ensure_user_dirs():
    """确保用户数据区与配置区存在，并在首次启动时迁移遗留的项目 data/。

    迁移采用「复制优先」策略：把项目根 data/ 的内容复制到系统数据区，已存在则跳过。
    这样即便某些文件被运行中的服务锁定（Windows 下数据库/日志无法移动），系统数据区
    仍能获得完整数据，服务始终以系统数据区为准。复制后尝试清理遗留源文件，删不掉的
    忽略（无害）。用 .migrated_from_legacy 标记避免重复复制。
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(USER_CONFIG_DIR, exist_ok=True)
    legacy = os.path.join(PROJECT_ROOT, 'data')
    marker = os.path.join(DATA_DIR, '.migrated_from_legacy')
    if os.path.isdir(legacy) and not os.path.exists(marker):
        try:
            items = os.listdir(legacy)
        except Exception:
            items = []
        for name in items:
            src = os.path.join(legacy, name)
            dst = os.path.join(DATA_DIR, name)
            if os.path.exists(dst):
                continue
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
            except Exception as e:  # pragma: no cover - 迁移失败不影响启动
                print(f'[paths] 迁移遗留数据失败 {src}: {e}')
        try:
            with open(marker, 'w') as f:
                f.write('migrated')
        except Exception:
            pass
        # 尝试清理遗留源（被锁文件忽略，用户停服务后可手动删除项目 data/）
        for name in items:
            src = os.path.join(legacy, name)
            try:
                if os.path.isdir(src):
                    shutil.rmtree(src, ignore_errors=True)
                else:
                    os.remove(src)
            except Exception:
                pass
        try:
            if not os.listdir(legacy):
                os.rmdir(legacy)
        except Exception:
            pass


def get_thumbnails_dir():
    return os.path.join(DATA_DIR, 'thumbnails')


def get_databases_dir():
    return os.path.join(DATA_DIR, 'databases')
