#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DPlayer 2.0 服务卸载脚本

功能：
  1. 停止并移除 NSSM 注册的 Windows 服务
  2. 可选：清除运行目录（--purge）
  3. 保留源码目录，不影响开发环境
  4. 支持指定服务（--services web）只卸载部分服务

用法：
  python scripts/uninstall.py                         # 仅卸载服务注册，保留运行目录文件
  python scripts/uninstall.py --purge                 # 卸载服务 + 删除运行目录
  python scripts/uninstall.py --services web          # 只卸载 web 服务
  python scripts/uninstall.py --dest D:\\DPlayer       # 指定运行目录
  python scripts/uninstall.py --service-only          # 只停止/移除服务，不动文件
"""

import os
import sys
import json
import shutil
import argparse
import subprocess
import logging
from pathlib import Path

# ============================================================
# 配置
# ============================================================

# 默认运行目录（与 install.py 保持一致）
DEFAULT_DEST = r'C:\DPlayer\runtime'

# 服务定义（与 install.py 保持一致）
NSSM_SERVICES = {
    'web': {
        'service_name': 'dplayer-web',
        'display_name': 'DPlayer 2.0 Web服务',
    },
    'thumbnail': {
        'service_name': 'dplayer-thumbnail',
        'display_name': 'DPlayer 2.0 缩略图服务',
    },
}

# ============================================================
# 日志
# ============================================================

logging.basicConfig(format='%(message)s', level=logging.INFO)
log = logging.getLogger('uninstaller')


# ============================================================
# 工具函数
# ============================================================

def find_nssm() -> str | None:
    """查找 nssm.exe 路径"""
    try:
        result = subprocess.run(
            ['nssm', 'version'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return 'nssm'
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

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


def read_install_info(dest_dir: Path) -> dict:
    """读取 install.json（如果存在）"""
    info_file = dest_dir / 'install.json'
    if info_file.exists():
        try:
            return json.loads(info_file.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}


def confirm(prompt: str) -> bool:
    """交互式确认（非 TTY 时直接返回 True）"""
    if not sys.stdin.isatty():
        return True
    ans = input(f'{prompt} [y/N] ').strip().lower()
    return ans in ('y', 'yes')


# ============================================================
# 核心：停止并移除 NSSM 服务
# ============================================================

def remove_nssm_services(nssm_exe: str, services: list[str] | None = None) -> dict:
    """
    停止并移除 NSSM 注册的 Windows 服务。
    返回各服务的操作结果。
    """
    log.info('\n[1/2] 移除 NSSM 服务...')
    keys = services or list(NSSM_SERVICES.keys())
    results = {}

    for key in keys:
        svc = NSSM_SERVICES.get(key)
        if not svc:
            log.warning(f'  未知服务 key: {key}，跳过')
            continue

        service_name = svc['service_name']
        display_name = svc['display_name']
        log.info(f'\n  → 处理: {display_name} ({service_name})')

        # 先尝试停止
        stop_result = subprocess.run(
            [nssm_exe, 'stop', service_name],
            capture_output=True, text=True, encoding='utf-8', errors='replace'
        )
        if stop_result.returncode == 0:
            log.info(f'    [已停止] {service_name}')
        else:
            # 可能服务根本没在运行，这是正常情况
            log.info(f'    [停止]  {service_name} (可能未运行)')

        # 移除服务注册
        remove_result = subprocess.run(
            [nssm_exe, 'remove', service_name, 'confirm'],
            capture_output=True, text=True, encoding='utf-8', errors='replace'
        )
        if remove_result.returncode == 0:
            log.info(f'    [已移除] {service_name}')
            results[key] = {'success': True, 'service_name': service_name}
        else:
            err = remove_result.stderr.strip() or remove_result.stdout.strip()
            # "服务不存在" 也视为成功（幂等）
            if 'does not exist' in err.lower() or '不存在' in err or 'service not' in err.lower():
                log.info(f'    [跳过]  {service_name} 服务不存在（已卸载或从未安装）')
                results[key] = {'success': True, 'service_name': service_name, 'skipped': True}
            else:
                log.error(f'    [失败]  移除 {service_name}: {err}')
                results[key] = {'success': False, 'service_name': service_name, 'message': err}

    return results


# ============================================================
# 核心：清除运行目录
# ============================================================

def purge_runtime(dest_dir: Path, force: bool = False) -> bool:
    """
    删除运行目录。
    - 如果目录不存在，直接返回 True
    - 非 --force 时会交互确认
    """
    if not dest_dir.exists():
        log.info(f'  运行目录不存在，无需清理: {dest_dir}')
        return True

    log.info(f'\n[2/2] 清除运行目录: {dest_dir}')

    # 显示目录大小（估算）
    try:
        file_count = sum(1 for _ in dest_dir.rglob('*') if _.is_file())
        log.info(f'  目录包含约 {file_count} 个文件')
    except Exception:
        pass

    if not force:
        if not confirm(f'  确认删除运行目录 {dest_dir}？（此操作不可撤销）'):
            log.info('  已取消，运行目录保留')
            return False

    try:
        shutil.rmtree(str(dest_dir))
        log.info(f'  [已删除] {dest_dir}')
        return True
    except Exception as e:
        log.error(f'  [失败] 删除运行目录: {e}')
        return False


# ============================================================
# 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='DPlayer 2.0 服务卸载脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/uninstall.py                         仅移除服务注册，保留运行目录
  python scripts/uninstall.py --purge                 移除服务 + 删除运行目录
  python scripts/uninstall.py --purge --force         强制删除，不询问确认
  python scripts/uninstall.py --services web          只卸载 web 服务
  python scripts/uninstall.py --dest D:\\DPlayer        指定运行目录
        """
    )
    parser.add_argument(
        '--dest', default=DEFAULT_DEST,
        help=f'运行目录路径（默认: {DEFAULT_DEST}）'
    )
    parser.add_argument(
        '--purge', action='store_true',
        help='删除运行目录（包含所有配置和数据，不可撤销）'
    )
    parser.add_argument(
        '--force', action='store_true',
        help='强制操作，跳过确认提示（与 --purge 配合使用）'
    )
    parser.add_argument(
        '--service-only', action='store_true',
        help='只移除服务注册，不处理运行目录（忽略 --purge）'
    )
    parser.add_argument(
        '--services', nargs='+', choices=list(NSSM_SERVICES.keys()),
        help='只卸载指定服务（默认: 全部）'
    )
    args = parser.parse_args()

    dest_dir    = Path(args.dest).resolve()
    purge       = args.purge and not args.service_only
    force       = args.force

    print('=' * 60)
    print('  DPlayer 2.0 服务卸载程序')
    print('=' * 60)
    print(f'  运行目录 : {dest_dir}')
    print(f'  操作     : {"移除服务 + 删除运行目录" if purge else "仅移除服务注册"}')
    print('=' * 60)

    # 显示已安装信息
    info = read_install_info(dest_dir)
    if info:
        print(f'\n  已安装版本 : {info.get("version", "未知")}')
        print(f'  安装时间   : {info.get("install_time", "未知")}')
        print(f'  源码目录   : {info.get("source_dir", "未知")}')

    # 全局确认（非 force 时）
    if not force and not args.service_only:
        action_desc = '删除运行目录中的所有数据' if purge else '停止并移除服务注册'
        if not confirm(f'\n即将执行：{action_desc}，确认继续？'):
            print('已取消卸载。')
            sys.exit(0)

    # 1. 移除 NSSM 服务
    nssm_exe = find_nssm()
    if nssm_exe is None:
        log.warning('\n[警告] 未找到 nssm.exe，跳过服务注销步骤')
        log.warning('  若服务已注册，请手动执行:')
        for svc in NSSM_SERVICES.values():
            log.warning(f'    nssm stop {svc["service_name"]} && nssm remove {svc["service_name"]} confirm')
    else:
        remove_nssm_services(nssm_exe, services=args.services)

    # 2. 清除运行目录（--purge）
    if purge:
        purge_runtime(dest_dir, force=force)
    else:
        log.info(f'\n[跳过] 运行目录保留: {dest_dir}')
        log.info('  若需删除，请使用 --purge 参数')

    print('\n' + '=' * 60)
    print('  卸载完成')
    print('=' * 60)
    if not purge:
        print(f'\n  运行目录仍保留在: {dest_dir}')
        print(f'  如需彻底清理，运行:')
        print(f'    python scripts/uninstall.py --dest "{dest_dir}" --purge')


if __name__ == '__main__':
    main()
