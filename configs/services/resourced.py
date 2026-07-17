# -*- coding: utf-8 -*-
"""
DPlayer 资源管理服务 (resourced) NSSM 包装脚本

用于通过 NSSM 将 Python 服务安装为 Windows 服务。

Usage:
    python configs/services/resourced.py install
    python configs/services/resourced.py start
    python configs/services/resourced.py stop
    python configs/services/resourced.py restart
    python configs/services/resourced.py uninstall
"""

import os
import sys
import time
import subprocess
import shutil

# 路径配置
SERVICE_NAME = 'dplayer-resourced'
DISPLAY_NAME = 'DPlayer 资源管理服务'
DESCRIPTION = 'DPlayer 资源管理服务 - 负责资源库扫描和文件监控'

# 入口脚本
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(os.path.dirname(THIS_DIR))  # 项目根目录
RESOURCE_MAIN = os.path.join(SRC_DIR, 'src', 'resource', 'main.py')
VENV_PYTHON = os.path.join(SRC_DIR, 'venv', 'Scripts', 'python.exe')


def get_paths():
    """获取各种路径"""
    # 检测 venv python 是否存在
    if os.path.isfile(VENV_PYTHON):
        python_exe = VENV_PYTHON
    else:
        python_exe = sys.executable

    return {
        'python': python_exe,
        'script': RESOURCE_MAIN,
        'cwd': SRC_DIR,
    }


def run_nssm(args):
    """运行 NSSM 命令"""
    nssm = 'nssm.exe'
    result = subprocess.run([nssm] + args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"NSSM error: {result.stderr}")
        return False
    return True


def install_service():
    """安装服务"""
    paths = get_paths()

    if not os.path.isfile(paths['script']):
        print(f"错误: 找不到入口脚本 {paths['script']}")
        return False

    if not os.path.isfile(paths['python']):
        print(f"错误: 找不到 Python {paths['python']}")
        return False

    print(f"安装服务: {SERVICE_NAME}")
    print(f"  Python: {paths['python']}")
    print(f"  脚本: {paths['script']}")
    print(f"  工作目录: {paths['cwd']}")

    # 创建 AppDirectory 指向源码目录
    app_dir = SRC_DIR

    args = [
        'install', SERVICE_NAME,
        paths['python'],
        f'"{paths["script"]}"',
    ]

    # 先尝试直接安装
    if run_nssm(args):
        # 设置显示名和描述
        run_nssm(['set', SERVICE_NAME, 'DisplayName', DISPLAY_NAME])
        run_nssm(['set', SERVICE_NAME, 'Description', DESCRIPTION])
        # 设置工作目录
        run_nssm(['set', SERVICE_NAME, 'AppDirectory', app_dir])
        # 设置环境变量
        run_nssm(['set', SERVICE_NAME, 'AppEnvironmentExtra', 'PYTHONPATH=' + SRC_DIR])
        # 设置启动类型
        run_nssm(['set', SERVICE_NAME, 'Start', 'MANUAL'])

        print(f"服务安装成功: {SERVICE_NAME}")
        return True

    return False


def uninstall_service():
    """卸载服务"""
    print(f"卸载服务: {SERVICE_NAME}")
    return run_nssm(['uninstall', SERVICE_NAME])


def start_service():
    """启动服务"""
    print(f"启动服务: {SERVICE_NAME}")
    return run_nssm(['start', SERVICE_NAME])


def stop_service():
    """停止服务"""
    print(f"停止服务: {SERVICE_NAME}")
    return run_nssm(['stop', SERVICE_NAME])


def restart_service():
    """重启服务"""
    print(f"重启服务: {SERVICE_NAME}")
    stop_service()
    time.sleep(2)
    start_service()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == 'install':
        install_service()
    elif cmd == 'uninstall':
        uninstall_service()
    elif cmd == 'start':
        start_service()
    elif cmd == 'stop':
        stop_service()
    elif cmd == 'restart':
        restart_service()
    elif cmd == 'status':
        result = subprocess.run(['sc', 'query', SERVICE_NAME], capture_output=True, text=True)
        print(result.stdout)
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
        sys.exit(1)
