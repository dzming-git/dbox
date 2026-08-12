#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dbox - 服务启动守卫

开发模式：允许直接运行 python xxx.py，支持热加载
生产模式：要求通过 NSSM 服务管理启动

检测逻辑：
  1. 检查环境变量 DBOX_DEV_MODE=1（开发模式，允许直接运行）
  2. 检查父进程是否为 nssm.exe（Windows）
  3. 检查环境变量 DBOX_SERVICE_MODE=1（NSSM 启动时设置）
  4. 检查 NSSM_SERVICE_NAME 环境变量
"""

import os
import sys
from pathlib import Path


def _iter_parent_chain():
    """向上遍历进程树，逐个返回祖先进程对象（从父进程开始）。"""
    try:
        import psutil
    except Exception:
        return
    try:
        proc = psutil.Process()
    except Exception:
        return
    seen = set()
    while proc is not None and proc.pid not in seen:
        seen.add(proc.pid)
        try:
            proc = proc.parent()
        except Exception:
            return
        if proc is None:
            return
        yield proc


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


def _is_dev_mode() -> bool:
    """检查是否为开发模式"""
    return os.environ.get('DBOX_DEV_MODE') == '1'


def _is_service_mode_env() -> bool:
    """检测是否通过服务相关环境变量声明（install.py / 手动配置均可）。

    任何 DBOX_ENV / DBOX_SERVICE_MODE 取值都视为“由服务管理器托管”，
    避免非标准的 DBOX_ENV=production 这类配置导致守卫误杀生产服务。
    """
    if os.environ.get('DBOX_SERVICE_MODE') == '1':
        return True
    if os.environ.get('DBOX_ENV'):
        return True
    return False


def _parent_chain_has_nssm() -> bool:
    """沿进程树向上查找 nssm / services / svchost（NSSM 工作进程的最终祖先）。"""
    nssm_markers = ('nssm', 'services.exe', 'svchost')
    for proc in _iter_parent_chain():
        try:
            name = proc.name().lower()
        except Exception:
            continue
        if any(m in name for m in nssm_markers):
            return True
    return False


def _is_running_under_nssm() -> bool:
    """检测是否通过 NSSM 启动（多重判定，任一命中即视为受托管）。"""
    # 1. 检查 NSSM 设置的环境变量
    if os.environ.get('NSSM_SERVICE_NAME'):
        return True

    # 2. 检查父进程链是否包含 nssm / services / svchost
    if _parent_chain_has_nssm():
        return True

    # 3. 检查服务模式环境变量（install.py 或手动配置均可）
    if _is_service_mode_env():
        return True

    # 4. 检查开发模式环境变量（dev 模式下允许直接运行）
    if os.environ.get('DBOX_DEV_MODE') == '1':
        return True

    return False


def check_service_launch(service_name: str, entry_file: str) -> None:
    """
    检查服务启动模式：
    - 开发模式：允许直接运行，支持热加载
    - 生产模式：必须通过 NSSM 启动

    Args:
        service_name: 服务显示名称（如 "Dbox Web Service"）
        entry_file:   入口文件名（如 "web.py"）
    """
    # 开发模式：允许直接运行
    if _is_dev_mode():
        print(f"[DEV MODE] {service_name} running in development mode")
        return

    # 生产模式：检查是否通过 NSSM 启动
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

  This service must be started through NSSM service manager in production mode.

  Correct ways to start:
    1. NSSM service (production):
       nssm start dbox-web
       nssm start dbox-thumbnail

    2. Development mode (hot reload):
       set DBOX_DEV_MODE=1
       python src/web/main.py

    3. Service manager script:
       python services/service_manager.py start web

    4. Install and start via install script:
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
