#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DPlayer 服务安装脚本

功能：
  1. 将源码文件拷贝到指定运行目录（解除服务与源码目录的路径绑定）
  2. 使用 NSSM 将服务注册为 Windows 服务，工作目录指向运行目录
  3. 生成 install.json 记录安装信息
  4. 支持 --update 模式（重新覆盖代码，保留配置和数据）
  5. 支持 --dest 参数自定义运行目录

用法：
  python scripts/install.py                       # 首次安装到默认目录
  python scripts/install.py --dest D:\\DPlayer     # 安装到自定义目录
  python scripts/install.py --update              # 更新代码（保留配置/数据）
  python scripts/install.py --no-service          # 只拷贝文件，不注册 Windows 服务
  python scripts/install.py --service-only        # 只注册服务（文件已存在）
"""

import os
import sys
import json
import shutil
import argparse
import subprocess
import logging
from datetime import datetime
from pathlib import Path

# ============================================================
# 配置
# ============================================================

# 默认运行目录
DEFAULT_DEST = r'C:\DPlayer\runtime'

# 源码目录（本脚本上一级）
SOURCE_DIR = Path(__file__).parent.parent.resolve()

# 服务定义（与 services/service_manager.py 保持一致）
NSSM_SERVICES = {
    'web': {
        'service_name': 'dplayer-web',
        'display_name': 'DPlayer Web服务',
        'description': 'DPlayer Web API服务 - 提供视频管理、标签管理等API接口',
        'entry': 'web.py',
        'port': 8080,
        'log_prefix': 'web',
    },
    'thumbnail': {
        'service_name': 'dplayer-thumbnail',
        'display_name': 'DPlayer 缩略图服务',
        'description': 'DPlayer 缩略图微服务 - 负责视频缩略图的生成和管理',
        'entry': 'thumbnail_service.py',
        'port': 5001,
        'log_prefix': 'thumbnail',
    },
    'webui': {
        'service_name': 'dplayer-webui',
        'display_name': 'DPlayer WebUI服务',
        'description': 'DPlayer WebUI前端服务 - 提供Vue3前端界面',
        'entry': 'services/webui_service.py',
        'port': 5173,
        'log_prefix': 'webui',
    },
}

# 安装清单：(源码相对路径, 是否在 --update 时覆盖)
# True  = 代码文件，每次都覆盖（或 --update 时覆盖）
# False = 配置/数据文件，仅首次安装，--update 时不覆盖
INSTALL_MANIFEST = [
    # --- 入口脚本 ---
    ('web.py',               True),
    ('thumbnail_service.py', True),
    ('services/webui_service.py', True),
    # --- 前端 ---
    ('frontend',             True),
    # --- 核心模块 ---
    ('msas-web',             True),
    ('msas-thumb',           True),
    ('libs',                 True),
    ('services',             True),
    ('static',               True),   # 含 thumbnails/
    # --- 配置（首次拷贝，update 不覆盖） ---
    ('config',               False),
    # --- 运行时数据（绝不覆盖） ---
    ('instance',             False),
]

# 忽略拷贝的目录/扩展名
IGNORE_DIRS = {
    '__pycache__', '.git', '.venv', 'venv', 'node_modules',
    'frontend', 'task-acceptance-criteria', 'scripts',
    'tests', 'playwright-report', 'test-results', '.pytest_cache',
    '.mypy_cache', 'logs', 'uploads',
}
IGNORE_EXTS = {'.pyc', '.pyo', '.log', '.tmp', '.swp'}

# ============================================================
# 日志
# ============================================================

logging.basicConfig(
    format='%(message)s',
    level=logging.INFO,
)
log = logging.getLogger('installer')


# ============================================================
# 工具函数
# ============================================================

def _should_ignore(name: str) -> bool:
    """判断文件/目录名是否应被忽略"""
    if name in IGNORE_DIRS:
        return True
    ext = Path(name).suffix.lower()
    if ext in IGNORE_EXTS:
        return True
    return False


def _copy_path(src: Path, dst: Path, overwrite: bool, update_mode: bool) -> int:
    """
    拷贝单个文件或目录树到目标位置。
    返回实际拷贝的文件数。

    覆盖逻辑（优先级从高到低）：
      - overwrite=True  → 无条件覆盖（代码文件，update 模式也覆盖）
      - overwrite=False → 仅首次安装写入，--update 时也不覆盖（配置/数据文件）
    """
    if not src.exists():
        log.warning(f'  [skip-missing] {src.name}')
        return 0

    # 不可覆盖的项：文件已存在时，无论是否 update 都跳过
    if not overwrite and dst.exists():
        log.info(f'  [skip-keep]    {src.name}')
        return 0

    copied = 0

    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        log.info(f'  [copied]       {src.name}')
        return 1

    # 目录
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if _should_ignore(item.name):
            continue
        child_dst = dst / item.name
        if item.is_dir():
            copied += _copy_path(item, child_dst, overwrite, update_mode)
        else:
            # 子文件：非可覆盖目录内的文件，已存在时跳过
            if not overwrite and child_dst.exists():
                continue
            child_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(item), str(child_dst))
            copied += 1

    if copied > 0:
        log.info(f'  [copied]       {src.name}/  ({copied} files)')
    return copied


def get_version(source_dir: Path) -> str:
    """读取版本号"""
    ver_file = source_dir / 'VERSION'
    if ver_file.exists():
        return ver_file.read_text(encoding='utf-8').strip()
    return '2.0.0'


def find_python_exe(dest_dir: Path) -> str:
    """
    查找可用的 Python 可执行文件，优先使用运行目录下的 venv。
    """
    # 运行目录下的 venv
    venv_py = dest_dir / 'venv' / 'Scripts' / 'python.exe'
    if venv_py.exists():
        return str(venv_py)

    # 源码目录下的 venv
    src_venv_py = SOURCE_DIR / 'venv' / 'Scripts' / 'python.exe'
    if src_venv_py.exists():
        return str(src_venv_py)

    # 当前 Python
    return sys.executable


def find_nssm() -> str | None:
    """查找 nssm.exe 路径"""
    # 1. PATH 中
    try:
        result = subprocess.run(
            ['nssm', 'version'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return 'nssm'
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 2. 常见安装路径
    common_paths = [
        r'C:\nssm\win64\nssm.exe',
        r'C:\nssm\nssm.exe',
        r'C:\tools\nssm\nssm.exe',
        r'C:\Program Files\nssm\nssm.exe',
    ]
    for p in common_paths:
        if os.path.exists(p):
            return p

    return None


# ============================================================
# 核心：拷贝文件到运行目录
# ============================================================

def copy_files(source_dir: Path, dest_dir: Path, update: bool = False) -> int:
    """
    将源码文件按清单拷贝到运行目录。
    返回总拷贝文件数。
    """
    log.info(f'\n[1/3] Copy files: {source_dir} -> {dest_dir}')
    dest_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for rel_path, should_overwrite in INSTALL_MANIFEST:
        src = source_dir / rel_path
        dst = dest_dir / rel_path
        total += _copy_path(src, dst, overwrite=should_overwrite, update_mode=update)

    # 确保运行时目录存在
    for d in ['logs', 'uploads', 'instance']:
        (dest_dir / d).mkdir(exist_ok=True)

    log.info(f'\n  Total copied: {total} files')
    return total


# ============================================================
# 核心：写入 install.json
# ============================================================

def write_install_json(source_dir: Path, dest_dir: Path, update: bool):
    """生成安装元数据文件"""
    info = {
        'version':      get_version(source_dir),
        'install_time': datetime.now().isoformat(),
        'source_dir':   str(source_dir),
        'runtime_dir':  str(dest_dir),
        'update':       update,
        'python_exe':   find_python_exe(dest_dir),
    }
    path = dest_dir / 'install.json'
    path.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    log.info(f'  install.json -> {path}')
    return info


# ============================================================
# 核心：NSSM 服务注册
# ============================================================

def register_nssm_services(dest_dir: Path, nssm_exe: str, services: list[str] | None = None):
    """
    使用 NSSM 将服务注册为 Windows 服务，工作目录指向运行目录。

    Args:
        dest_dir:  运行目录（已拷贝好文件的目录）
        nssm_exe:  nssm 可执行文件路径
        services:  需要安装的服务 key 列表，None 表示全部
    """
    log.info(f'\n[3/3] Register NSSM services (work dir: {dest_dir})')

    python_exe = find_python_exe(dest_dir)
    log.info(f'  Python: {python_exe}')

    log_dir = dest_dir / 'logs'
    log_dir.mkdir(exist_ok=True)

    keys_to_install = services or list(NSSM_SERVICES.keys())

    results = {}
    for key in keys_to_install:
        svc = NSSM_SERVICES.get(key)
        if not svc:
            log.warning(f'  Unknown service key: {key}, skip')
            continue

        service_name = svc['service_name']
        entry_script = dest_dir / svc['entry']
        log_prefix   = svc['log_prefix']

        if not entry_script.exists():
            log.warning(f'  [WARN] Entry script not found: {entry_script}, skip {service_name}')
            results[key] = {'success': False, 'message': f'Entry script not found: {entry_script}'}
            continue

        log.info(f'\n  -> Install service: {service_name}')

        # 先停止并移除已有的同名服务（幂等）
        subprocess.run([nssm_exe, 'stop', service_name], capture_output=True)
        subprocess.run([nssm_exe, 'remove', service_name, 'confirm'], capture_output=True)

        # 安装服务
        result = subprocess.run(
            [nssm_exe, 'install', service_name, python_exe, str(entry_script)],
            capture_output=True, text=True, encoding='utf-8', errors='replace'
        )
        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip()
            log.error(f'  [FAIL] Install {service_name}: {msg}')
            results[key] = {'success': False, 'message': msg}
            continue

        # 配置服务参数
        env_extra = 'DPLAYER_SERVICE_MODE=1'
        nssm_sets = [
            ('AppDirectory',  str(dest_dir)),
            ('DisplayName',   svc['display_name']),
            ('Description',   svc['description']),
            ('Start',         'SERVICE_AUTO_START'),
            ('AppStdout',     str(log_dir / f'{log_prefix}_stdout.log')),
            ('AppStderr',     str(log_dir / f'{log_prefix}_stderr.log')),
            ('AppRestartDelay', '5000'),
            ('AppEnvironmentExtra', env_extra),
        ]

        for param, value in nssm_sets:
            r = subprocess.run(
                [nssm_exe, 'set', service_name, param, value],
                capture_output=True, text=True, encoding='utf-8', errors='replace'
            )
            if r.returncode != 0:
                log.warning(f'    set {param} failed: {r.stderr.strip()}')

        log.info(f'  [OK]  {service_name} registered')
        log.info(f'        work_dir   : {dest_dir}')
        log.info(f'        entry      : {entry_script}')
        log.info(f'        log_dir    : {log_dir}')

        results[key] = {'success': True, 'service_name': service_name}

    return results


# ============================================================
# 核心：备份运行目录（--update 前）
# ============================================================

def backup_runtime(dest_dir: Path) -> Path | None:
    """升级前备份当前运行目录"""
    if not dest_dir.exists():
        return None

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_dir = dest_dir.parent / f'runtime_backup_{ts}'

    log.info(f'\n[backup] {dest_dir} -> {backup_dir}')
    try:
        shutil.copytree(str(dest_dir), str(backup_dir), dirs_exist_ok=False)
        log.info(f'  Backup done: {backup_dir}')
        return backup_dir
    except Exception as e:
        log.warning(f'  Backup failed (continue install): {e}')
        return None


# ============================================================
# 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='DPlayer 服务安装脚本（拷贝文件 + NSSM 注册）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/install.py                        首次安装
  python scripts/install.py --dest D:\\DPlayer      安装到指定目录
  python scripts/install.py --update               更新代码（保留配置/数据）
  python scripts/install.py --no-service           只拷贝文件
  python scripts/install.py --service-only         只重新注册服务
  python scripts/install.py --services web         只安装 web 服务
        """
    )
    parser.add_argument(
        '--dest', default=DEFAULT_DEST,
        help=f'运行目录路径（默认: {DEFAULT_DEST}）'
    )
    parser.add_argument(
        '--update', action='store_true',
        help='更新模式：重新覆盖代码文件，保留 config/ 和 instance/'
    )
    parser.add_argument(
        '--no-service', action='store_true',
        help='只拷贝文件，不注册 Windows 服务'
    )
    parser.add_argument(
        '--service-only', action='store_true',
        help='只注册 Windows 服务（假设文件已存在于运行目录）'
    )
    parser.add_argument(
        '--services', nargs='+', choices=list(NSSM_SERVICES.keys()),
        help='只安装指定服务（默认: 全部）'
    )
    parser.add_argument(
        '--start', nargs='?', const=True, default=None, type=lambda x: x.lower() == 'true',
        help='安装完成后自动启动服务 (默认: 读取配置文件)'
    )
    args = parser.parse_args()

    dest_dir   = Path(args.dest).resolve()
    update     = args.update
    no_service = args.no_service
    svc_only   = args.service_only

    # 读取配置文件中的 auto_start 设置
    config_path = SOURCE_DIR / 'config' / 'config.json'
    config_auto_start = True  # 默认值
    try:
        if config_path.exists():
            import json
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                config_auto_start = config_data.get('auto_start', True)
    except Exception as e:
        log.warning(f'  读取配置文件失败，使用默认值: {e}')

    # 命令行 --start 参数优先，否则使用配置文件设置
    # args.start = None 表示未传参数，使用配置文件
    # args.start = True 表示传了 --start
    # args.start = False 表示传了 --start=false
    should_auto_start = config_auto_start
    if args.start is not None:
        should_auto_start = args.start

    WORK_DIR = dest_dir
    print('=' * 60)
    print('  DPlayer Installer')
    print('=' * 60)
    print(f'  Source dir : {SOURCE_DIR}')
    print(f'  Runtime dir: {dest_dir}')
    print(f'  Mode       : {"update" if update else "fresh install"}')
    print(f'  Auto start : {"Yes" if should_auto_start else "No"}')
    print('=' * 60)

    # 1. 拷贝文件
    if not svc_only:
        if update and dest_dir.exists():
            backup_runtime(dest_dir)
        copy_files(SOURCE_DIR, dest_dir, update=update)

    # 2. 写入 install.json
    if not svc_only:
        log.info('\n[2/3] Write install.json')
        info = write_install_json(SOURCE_DIR, dest_dir, update)
        log.info(f'  version : {info["version"]}')
        log.info(f'  time    : {info["install_time"]}')

    # 3. 注册 NSSM 服务
    if not no_service:
        nssm_exe = find_nssm()
        if nssm_exe is None:
            log.warning('\n[WARN] nssm.exe not found, skip service registration')
            log.warning('  Install NSSM: https://nssm.cc/download')
            log.warning('  Or manually: nssm install dplayer-web ...')
        else:
            reg_results = register_nssm_services(
                WORK_DIR, nssm_exe,
                services=args.services
            )

            # 根据配置文件或命令行参数决定是否自动启动服务
            if should_auto_start and nssm_exe:
                log.info(f'\n[auto-start services] (config: {config_auto_start}, cmd: {args.start})')
                for key, res in reg_results.items():
                    if res.get('success'):
                        svc_name = res['service_name']
                        r = subprocess.run(
                            [nssm_exe, 'start', svc_name],
                            capture_output=True, text=True, encoding='utf-8', errors='replace'
                        )
                        if r.returncode == 0:
                            log.info(f'  [OK]  {svc_name} started')
                        else:
                            log.warning(f'  [WARN] {svc_name} failed to start: {r.stderr.strip()}')
    else:
        log.info('\n[skip] Service registration skipped (--no-service)')

    print('\n' + '=' * 60)
    print(f'  [OK] Install complete')
    print('=' * 60)
    print('\nNext steps:')
    print(f'  Start web service    : nssm start dplayer-web')
    print(f'  Start thumb service  : nssm start dplayer-thumbnail')
    print(f'  Check service status : nssm status dplayer-web')
    print(f'  Uninstall            : python scripts/uninstall.py')


if __name__ == '__main__':
    main()
