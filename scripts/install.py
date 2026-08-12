#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dbox 服务安装脚本（简化版）

功能：
  1. 直接在源码目录注册 NSSM 服务（支持热加载）
  2. 不拷贝文件，开发和运行路径一致
  3. 支持 --dev 模式（开发模式）和 --prod 模式（生产模式）

用法：
  python scripts/install.py --dev          # 开发模式：启用热加载，设置 DBOX_DEV_MODE=1
  python scripts/install.py --prod         # 生产模式：不启用热加载，设置 DBOX_SERVICE_MODE=1
  python scripts/install.py --update       # 更新服务配置
  python scripts/install.py --uninstall    # 卸载服务
"""

import os
import sys
import json
import argparse
import subprocess
import logging
from datetime import datetime
from pathlib import Path

# ============================================================
# 配置
# ============================================================

# 源码目录（本脚本上一级）
SOURCE_DIR = Path(__file__).parent.parent.resolve()

# 服务定义
NSSM_SERVICES = {
    'web': {
        'service_name': 'dbox-web',
        'display_name': 'Dbox Web服务',
        'description': 'Dbox Web API服务 - 提供视频管理、标签管理等API接口',
        'entry': 'src/web/main.py',
        'port': 8080,
        'log_prefix': 'web',
    },
    'downloader': {
        'service_name': 'dbox-downloader',
        'display_name': 'Dbox 资源下载器',
        'description': 'Dbox 独立下载器服务 - 外部脚本执行（与主服务解耦，崩溃不影响主服务）',
        'entry': 'src/downloader/main.py',
        'port': 8092,
        'log_prefix': 'downloader',
    },
    'extensions': {
        'service_name': 'dbox-extensions',
        'display_name': 'Dbox 拓展管理宿主',
        'description': 'Dbox 拓展管理宿主 - 外部脚本执行引擎/脚本管理/UI扩展/AI助手/凭证保险库（与主服务完全解耦，8093）',
        'entry': 'src/extensions_host/app.py',
        'port': 8093,
        'log_prefix': 'extensions',
    },
    'bus': {
        'service_name': 'dbox-bus',
        'display_name': 'Dbox 服务总线',
        'description': 'Dbox 服务总线代理 - 所有内部服务通信中枢',
        'entry': 'configs/services/busbroker.py',
        'port': None,
        'log_prefix': 'bus',
    },
    'servicemgr': {
        'service_name': 'dbox-servicemgr',
        'display_name': 'Dbox 服务管理',
        'description': 'Dbox 服务管理守护进程 - 定期扫描和监控 dbox-* 服务状态',
        'entry': 'configs/services/servicemgrd.py',
        'port': None,
        'log_prefix': 'servicemgr',
    },
    'watchdog': {
        'service_name': 'dbox-watchdog',
        'display_name': 'Dbox 服务看门狗',
        'description': 'Dbox 服务看门狗 - 定时 ping 各服务总线，不可达则自动重启，多次失败则告警',
        'entry': 'configs/services/watchdogd.py',
        'port': None,
        'log_prefix': 'watchdog',
    },
    'thumbnail': {
        'service_name': 'dbox-thumbnail',
        'display_name': 'Dbox 缩略图服务',
        'description': 'Dbox 缩略图微服务 - 封面生成器守护进程（通过服务总线）',
        'entry': 'configs/services/thumbnaild.py',
        'port': None,
        'log_prefix': 'thumbnail',
    },
    'webui': {
        'service_name': 'dbox-webui',
        'display_name': 'Dbox WebUI服务',
        'description': 'Dbox WebUI前端服务 - 提供Vue3前端界面',
        'entry': 'configs/services/webui_service.py',
        'port': 5173,
        'log_prefix': 'webui',
    },
    'resource': {
        'service_name': 'dbox-resource',
        'display_name': 'Dbox 资源管理服务',
        'description': 'Dbox 资源管理微服务 - 负责资源库扫描、文件监控、索引管理',
        'entry': 'src/resource/main.py',
        'port': None,
        'log_prefix': 'resource',
    },
    'user': {
        'service_name': 'dbox-userd',
        'display_name': 'Dbox 用户管理服务',
        'description': 'Dbox 用户管理微服务 - 负责用户增删改查和认证',
        'entry': 'src/user/main.py',
        'port': None,
        'log_prefix': 'user',
    },
    'system': {
        'service_name': 'dbox-systemd',
        'display_name': 'Dbox 系统监控服务',
        'description': 'Dbox 系统监控服务 - 监控 CPU、内存、磁盘等系统资源',
        'entry': 'src/system/main.py',
        'port': None,
        'log_prefix': 'system',
    },
    'history': {
        'service_name': 'dbox-historyd',
        'display_name': 'Dbox 播放历史服务',
        'description': 'Dbox 播放历史服务 - 记录播放进度、支持断点续播',
        'entry': 'src/history/main.py',
        'port': None,
        'log_prefix': 'history',
    },
    'collection': {
        'service_name': 'dbox-collectiond',
        'display_name': 'Dbox 收藏夹服务',
        'description': 'Dbox 收藏夹服务 - 用户收藏视频、组织播放列表',
        'entry': 'src/collection/main.py',
        'port': None,
        'log_prefix': 'collection',
    },
    'search': {
        'service_name': 'dbox-searchd',
        'display_name': 'Dbox 搜索服务',
        'description': 'Dbox 搜索服务 - 全文搜索、视频标签和描述检索',
        'entry': 'src/search/main.py',
        'port': None,
        'log_prefix': 'search',
    },
    'scheduler': {
        'service_name': 'dbox-scheduler',
        'display_name': 'Dbox 脚本调度器',
        'description': 'Dbox 通用脚本轮询调度器 - 扫描 extensions/scripts 中声明 poll 触发的脚本并周期执行',
        'entry': 'scripts/poll_scheduler.py',
        'port': None,
        'log_prefix': 'scheduler',
    },
}

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

def get_version(source_dir: Path) -> str:
    """读取版本号"""
    ver_file = source_dir / 'VERSION'
    if ver_file.exists():
        return ver_file.read_text(encoding='utf-8').strip()
    return '2.0.0'


def find_python_exe() -> str:
    """查找可用的 Python 可执行文件"""
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
# 核心：注册 NSSM 服务
# ============================================================

def register_nssm_services(source_dir: Path, nssm_exe: str, dev_mode: bool, services: list[str] | None = None):
    """
    使用 NSSM 注册服务，工作目录指向源码目录。

    Args:
        source_dir:  源码目录
        nssm_exe:    nssm 可执行文件路径
        dev_mode:    是否为开发模式
        services:    需要安装的服务 key 列表，None 表示全部
    """
    mode_str = "开发模式（热加载）" if dev_mode else "生产模式"
    log.info(f'\n[注册服务] 模式: {mode_str}')
    log.info(f'  源码目录: {source_dir}')

    python_exe = find_python_exe()
    log.info(f'  Python: {python_exe}')

    log_dir = source_dir / 'data' / 'logs'
    log_dir.mkdir(exist_ok=True)

    keys_to_install = services or list(NSSM_SERVICES.keys())

    results = {}
    for key in keys_to_install:
        svc = NSSM_SERVICES.get(key)
        if not svc:
            log.warning(f'  Unknown service key: {key}, skip')
            continue

        service_name = svc['service_name']
        entry_script = source_dir / svc['entry']
        log_prefix   = svc['log_prefix']

        if not entry_script.exists():
            log.warning(f'  [WARN] 入口脚本不存在: {entry_script}, 跳过 {service_name}')
            results[key] = {'success': False, 'message': f'Entry script not found: {entry_script}'}
            continue

        log.info(f'\n  -> 安装服务: {service_name}')

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
            log.error(f'  [FAIL] 安装 {service_name} 失败: {msg}')
            results[key] = {'success': False, 'message': msg}
            continue

        # 设置环境变量：开发模式 vs 生产模式
        if dev_mode:
            env_extra = 'DBOX_DEV_MODE=1'
        else:
            env_extra = 'DBOX_SERVICE_MODE=1'

        # 配置服务参数
        nssm_sets = [
            ('AppDirectory',  str(source_dir)),
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

        log.info(f'  [OK]  {service_name} 已注册')
        log.info(f'        工作目录: {source_dir}')
        log.info(f'        入口脚本: {entry_script}')
        log.info(f'        环境变量: {env_extra}')

        results[key] = {'success': True, 'service_name': service_name}

    return results


def uninstall_services(nssm_exe: str, services: list[str] | None = None):
    """卸载服务"""
    log.info('\n[卸载服务]')
    
    keys_to_uninstall = services or list(NSSM_SERVICES.keys())
    
    for key in keys_to_uninstall:
        svc = NSSM_SERVICES.get(key)
        if not svc:
            continue
        
        service_name = svc['service_name']
        log.info(f'  -> 停止并移除: {service_name}')
        
        subprocess.run([nssm_exe, 'stop', service_name], capture_output=True)
        result = subprocess.run([nssm_exe, 'remove', service_name, 'confirm'], capture_output=True)
        
        if result.returncode == 0:
            log.info(f'  [OK]  {service_name} 已卸载')
        else:
            log.info(f'  [SKIP] {service_name} 不存在或已卸载')


# ============================================================
# 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='Dbox 服务安装脚本（源码直接运行，支持热加载）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/install.py --dev          # 开发模式：启用热加载
  python scripts/install.py --prod         # 生产模式：不启用热加载
  python scripts/install.py --update       # 更新服务配置
  python scripts/install.py --uninstall    # 卸载服务
  python scripts/install.py --services web --dev  # 只安装 web 服务（开发模式）
        """
    )
    parser.add_argument(
        '--dev', action='store_true',
        help='开发模式：启用热加载，设置 DBOX_DEV_MODE=1'
    )
    parser.add_argument(
        '--prod', action='store_true',
        help='生产模式：不启用热加载，设置 DBOX_SERVICE_MODE=1'
    )
    parser.add_argument(
        '--update', action='store_true',
        help='更新模式：重新注册服务（默认使用开发模式）'
    )
    parser.add_argument(
        '--uninstall', action='store_true',
        help='卸载所有服务'
    )
    parser.add_argument(
        '--services', nargs='+', choices=list(NSSM_SERVICES.keys()),
        help='只安装指定服务（默认: 全部）'
    )
    parser.add_argument(
        '--start', action='store_true',
        help='安装完成后自动启动服务'
    )
    args = parser.parse_args()

    # 确定模式
    if args.dev and args.prod:
        log.error('错误: --dev 和 --prod 不能同时使用')
        sys.exit(1)
    
    dev_mode = args.dev or (args.update and not args.prod)
    
    print('=' * 60)
    print('  Dbox Installer (Source Mode)')
    print('=' * 60)
    print(f'  源码目录: {SOURCE_DIR}')
    print(f'  模式    : {"开发模式（热加载）" if dev_mode else "生产模式"}')
    print('=' * 60)

    # 查找 NSSM
    nssm_exe = find_nssm()
    if nssm_exe is None:
        log.error('\n[ERROR] nssm.exe 未找到，无法注册服务')
        log.error('  下载 NSSM: https://nssm.cc/download')
        log.error('  或手动安装: nssm install dbox-web ...')
        sys.exit(1)

    # 卸载模式
    if args.uninstall:
        uninstall_services(nssm_exe, args.services)
        print('\n' + '=' * 60)
        print('  [OK] 卸载完成')
        print('=' * 60)
        return

    # 注册服务
    reg_results = register_nssm_services(
        SOURCE_DIR, nssm_exe,
        dev_mode=dev_mode,
        services=args.services
    )

    # 自动启动
    if args.start:
        log.info('\n[自动启动服务]')
        for key, res in reg_results.items():
            if res.get('success'):
                svc_name = res['service_name']
                r = subprocess.run(
                    [nssm_exe, 'start', svc_name],
                    capture_output=True, text=True, encoding='utf-8', errors='replace'
                )
                if r.returncode == 0:
                    log.info(f'  [OK]  {svc_name} 已启动')
                else:
                    log.warning(f'  [WARN] {svc_name} 启动失败: {r.stderr.strip()}')

    print('\n' + '=' * 60)
    print('  [OK] 安装完成')
    print('=' * 60)
    print('\n使用方式:')
    if dev_mode:
        print('  开发模式（热加载）:')
        print('    - 修改代码后自动重载，无需重启服务')
        print('    - 前端: http://localhost:5173 (Vue 热更新)')
        print('    - 后端: http://localhost:8080 (Flask 热更新)')
    else:
        print('  生产模式:')
        print('    - 代码修改后需要重启服务才能生效')
    print('\n常用命令:')
    print('  启动服务: nssm start dbox-web')
    print('  停止服务: nssm stop dbox-web')
    print('  重启服务: nssm restart dbox-web')
    print('  查看状态: nssm status dbox-web')
    print('  卸载服务: python scripts/install.py --uninstall')


if __name__ == '__main__':
    main()
