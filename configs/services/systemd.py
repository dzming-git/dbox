# -*- coding: utf-8 -*-
"""
systemd - 系统监控服务 NSSM 配置

使用 nssm 安装服务:
    python configs/services/systemd.py install

使用说明:
    python configs/services/systemd.py install   # 安装服务
    python configs/services/systemd.py start     # 启动服务
    python configs/services/systemd.py stop      # 停止服务
    python configs/services/systemd.py remove   # 删除服务
"""
import os
import sys
import subprocess

# 路径设置
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
_VENV_PYTHON = os.path.join(_PROJECT_ROOT, 'venv', 'Scripts', 'python.exe')
_SERVICE_ENTRY = os.path.join(_PROJECT_ROOT, 'src', 'system', 'main.py')


def get_python():
    """获取 Python 解释器路径"""
    if os.path.exists(_VENV_PYTHON):
        return _VENV_PYTHON
    return sys.executable


def run_nssm(args):
    """运行 nssm 命令"""
    nssm = os.path.join(_PROJECT_ROOT, 'tools', 'nssm.exe')
    if not os.path.exists(nssm):
        # 尝试从 PATH 中查找
        try:
            result = subprocess.run(['where', 'nssm'], capture_output=True, text=True)
            if result.returncode == 0:
                nssm = result.stdout.strip().split('\n')[0]
        except Exception:
            pass

    cmd = [nssm] + args
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=_PROJECT_ROOT)


def install_service():
    """安装 systemd 服务"""
    python = get_python()
    run_nssm([
        'install', 'dbox-systemd',
        python,
        _SERVICE_ENTRY,
        '--rpc-port', '15555',
        '--pub-port', '15556',
        '--interval', '2.0',
    ])
    # 设置显示名和描述
    run_nssm(['set', 'dbox-systemd', 'DisplayName', 'Dbox System Monitor'])
    run_nssm(['set', 'dbox-systemd', 'Description', 'Dbox 系统监控服务 - 监控 CPU、内存、磁盘等系统资源'])
    # 设置启动类型
    run_nssm(['set', 'dbox-systemd', 'Start', 'AUTOMATIC'])
    # 设置工作目录
    run_nssm(['set', 'dbox-systemd', 'AppDirectory', _PROJECT_ROOT])
    print("服务安装完成: dbox-systemd")


def start_service():
    """启动服务"""
    run_nssm(['start', 'dbox-systemd'])


def stop_service():
    """停止服务"""
    run_nssm(['stop', 'dbox-systemd'])


def remove_service():
    """删除服务"""
    run_nssm(['remove', 'dbox-systemd', 'confirm'])


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        print("用法: python systemd.py [install|start|stop|remove]")
        sys.exit(1)

    action = sys.argv[1].lower()
    if action == 'install':
        install_service()
    elif action == 'start':
        start_service()
    elif action == 'stop':
        stop_service()
    elif action == 'remove':
        remove_service()
    else:
        print(f"未知操作: {action}")
        sys.exit(1)