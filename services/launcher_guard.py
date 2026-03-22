#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DPlayer 1.0 - 服务启动守卫

拦截直接运行 python xxx.py 的行为，强制要求通过 NSSM 服务管理启动。

检测逻辑：
  1. 检查父进程是否为 nssm.exe（Windows）
  2. 检查环境变量 DPLAYER_SERVICE_MODE=1（NSSM 启动时设置）
  3. 检查 NSSM_SERVICE_NAME 环境变量

如果未通过 NSSM 启动，打印错误信息并退出。
"""

import os
import sys
import subprocess
from pathlib import Path


def _get_parent_process_name() -> str | None:
    """获取父进程名称（Windows）"""
    try:
        import psutil
        parent = psutil.Process().parent()
        if parent:
            return parent.name().lower()
    except Exception:
        pass
    return None


def _is_running_under_nssm() -> bool:
    """检测是否通过 NSSM 启动"""
    # 1. 检查 NSSM 设置的环境变量
    if os.environ.get('NSSM_SERVICE_NAME'):
        return True

    # 2. 检查父进程是否为 nssm.exe
    parent = _get_parent_process_name()
    if parent and 'nssm' in parent:
        return True

    # 3. 检查自定义环境变量（install.py 注册服务时设置）
    if os.environ.get('DPLAYER_SERVICE_MODE') == '1':
        return True

    # 4. 检查开发模式环境变量（dev 模式下允许直接运行）
    if os.environ.get('DPLAYER_DEV_MODE') == '1':
        return True

    return False


def check_service_launch(service_name: str, entry_file: str) -> None:
    """
    检查服务是否通过 NSSM 启动。
    如果不是，打印错误信息并退出。

    Args:
        service_name: 服务显示名称（如 "DPlayer Web Service"）
        entry_file:   入口文件名（如 "web.py"）
    """
    # 检查是否通过 NSSM 启动
    if _is_running_under_nssm():
        return

    # 未通过 NSSM 启动，打印错误并退出
    runtime_dir = Path(__file__).parent.parent.resolve()
    install_json = runtime_dir / 'install.json'

    msg = f"""
======================================================================
  ERROR: Direct execution is not allowed
======================================================================

  Service: {service_name}
  Entry  : {entry_file}

  This service must be started through NSSM service manager.

  Correct ways to start:
    1. NSSM service (recommended):
       nssm start dplayer-web
       nssm start dplayer-thumbnail

    2. Service manager script:
       python services/service_manager.py start web

    3. Install and start via install script:
       python scripts/install.py --start
======================================================================
"""
    # 如果 install.json 不存在，提示先安装
    if not install_json.exists():
        msg += """
  NOTE: Service not installed yet.
        Run 'python scripts/install.py' first.
======================================================================
"""

    sys.stderr.write(msg)
    sys.stderr.flush()
    sys.exit(1)


if __name__ == '__main__':
    # 测试模式
    print("Testing launcher_guard...")
    print(f"Parent process: {_get_parent_process_name()}")
    print(f"Under NSSM: {_is_running_under_nssm()}")
