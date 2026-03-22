#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DPlayer 1.0 - 服务管理脚本

功能：
  1. 通过 Python API 管理服务（不直接调用 Windows 命令）
  2. 支持服务启动、停止、重启
  3. 支持服务状态查询
  4. 支持批量操作

用法：
  python scripts/service_manager.py status              # 查看所有服务状态
  python scripts/service_manager.py start web           # 启动 web 服务
  python scripts/service_manager.py stop thumbnail      # 停止 thumbnail 服务
  python scripts/service_manager.py restart web         # 重启 web 服务
  python scripts/service_manager.py start-all           # 启动所有服务
  python scripts/service_manager.py stop-all            # 停止所有服务
  python scripts/service_manager.py restart-all         # 重启所有服务
"""

import os
import sys
import json
import subprocess
import argparse
from pathlib import Path
from typing import Dict, Optional, List

# ============================================================
# 配置
# ============================================================

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# 服务定义
SERVICES = {
    'web': {
        'service_name': 'dplayer-web',
        'display_name': 'DPlayer 1.0 Web服务',
        'description': 'DPlayer 1.0 Web API服务',
        'port': 8080,
    },
    'thumbnail': {
        'service_name': 'dplayer-thumbnail',
        'display_name': 'DPlayer 1.0 缩略图服务',
        'description': 'DPlayer 1.0 缩略图微服务',
        'port': 5001,
    },
    'webui': {
        'service_name': 'dplayer-webui',
        'display_name': 'DPlayer 1.0 WebUI服务',
        'description': 'DPlayer 1.0 Vue3前端界面',
        'port': 5173,
    },
}


# ============================================================
# NSSM 服务管理 API
# ============================================================

class NSSMServiceManager:
    """NSSM 服务管理器（通过 Python API 调用）"""
    
    def __init__(self):
        self.nssm_exe = self._find_nssm()
        if not self.nssm_exe:
            raise RuntimeError("未找到 nssm.exe，请先安装 NSSM")
    
    def _find_nssm(self) -> Optional[str]:
        """查找 nssm.exe 路径"""
        # 1. PATH 中查找
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
    
    def _run_nssm(self, *args) -> Dict:
        """
        执行 NSSM 命令并返回结果。
        
        Returns:
            {
                'success': bool,
                'returncode': int,
                'stdout': str,
                'stderr': str,
            }
        """
        cmd = [self.nssm_exe] + list(args)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=30
            )
            return {
                'success': result.returncode == 0,
                'returncode': result.returncode,
                'stdout': result.stdout.strip(),
                'stderr': result.stderr.strip(),
            }
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'returncode': -1,
                'stdout': '',
                'stderr': '命令执行超时',
            }
        except Exception as e:
            return {
                'success': False,
                'returncode': -1,
                'stdout': '',
                'stderr': str(e),
            }
    
    # --------------------------------------------------------
    # 服务状态查询
    # --------------------------------------------------------
    
    def get_status(self, service_name: str) -> Dict:
        """
        查询服务状态。
        
        Returns:
            {
                'success': bool,
                'status': str,  # 'RUNNING', 'STOPPED', 'PAUSED', 'UNKNOWN'
                'message': str,
            }
        """
        result = self._run_nssm('status', service_name)
        
        if result['success']:
            status = result['stdout'].upper()
            # NSSM 返回的状态字符串
            if 'RUNNING' in status or 'SERVICE_RUNNING' in status:
                return {
                    'success': True,
                    'status': 'RUNNING',
                    'message': '服务正在运行',
                }
            elif 'STOPPED' in status or 'SERVICE_STOPPED' in status:
                return {
                    'success': True,
                    'status': 'STOPPED',
                    'message': '服务已停止',
                }
            elif 'PAUSED' in status or 'SERVICE_PAUSED' in status:
                return {
                    'success': True,
                    'status': 'PAUSED',
                    'message': '服务已暂停',
                }
            else:
                return {
                    'success': True,
                    'status': 'UNKNOWN',
                    'message': f'未知状态: {status}',
                }
        else:
            return {
                'success': False,
                'status': 'ERROR',
                'message': result['stderr'] or result['stdout'],
            }
    
    def get_service_info(self, service_key: str) -> Dict:
        """
        获取服务完整信息。
        
        Returns:
            {
                'key': str,
                'service_name': str,
                'display_name': str,
                'status': str,
                'status_message': str,
                'port': int,
            }
        """
        if service_key not in SERVICES:
            return {
                'key': service_key,
                'service_name': 'unknown',
                'display_name': 'Unknown Service',
                'status': 'ERROR',
                'status_message': f'未知的服务: {service_key}',
                'port': 0,
            }
        
        svc = SERVICES[service_key]
        status_result = self.get_status(svc['service_name'])
        
        return {
            'key': service_key,
            'service_name': svc['service_name'],
            'display_name': svc['display_name'],
            'status': status_result['status'],
            'status_message': status_result['message'],
            'port': svc['port'],
        }
    
    # --------------------------------------------------------
    # 服务控制
    # --------------------------------------------------------
    
    def start(self, service_name: str) -> Dict:
        """
        启动服务。
        
        Returns:
            {
                'success': bool,
                'message': str,
            }
        """
        # 先检查当前状态
        status = self.get_status(service_name)
        if status['status'] == 'RUNNING':
            return {
                'success': True,
                'message': '服务已经在运行',
            }
        
        result = self._run_nssm('start', service_name)
        
        if result['success'] or 'SERVICE_RUNNING' in result['stdout']:
            return {
                'success': True,
                'message': '服务启动成功',
            }
        else:
            return {
                'success': False,
                'message': result['stderr'] or result['stdout'] or '启动失败',
            }
    
    def stop(self, service_name: str) -> Dict:
        """
        停止服务。
        
        Returns:
            {
                'success': bool,
                'message': str,
            }
        """
        # 先检查当前状态
        status = self.get_status(service_name)
        if status['status'] == 'STOPPED':
            return {
                'success': True,
                'message': '服务已经停止',
            }
        
        result = self._run_nssm('stop', service_name)
        
        if result['success'] or 'SERVICE_STOPPED' in result['stdout']:
            return {
                'success': True,
                'message': '服务停止成功',
            }
        else:
            return {
                'success': False,
                'message': result['stderr'] or result['stdout'] or '停止失败',
            }
    
    def restart(self, service_name: str) -> Dict:
        """
        重启服务。
        
        Returns:
            {
                'success': bool,
                'message': str,
            }
        """
        # 停止服务
        stop_result = self.stop(service_name)
        if not stop_result['success']:
            # 如果停止失败但服务本来就没运行，继续启动
            status = self.get_status(service_name)
            if status['status'] != 'STOPPED':
                return {
                    'success': False,
                    'message': f"停止服务失败: {stop_result['message']}",
                }
        
        # 等待服务完全停止
        import time
        time.sleep(2)
        
        # 启动服务
        start_result = self.start(service_name)
        if start_result['success']:
            return {
                'success': True,
                'message': '服务重启成功',
            }
        else:
            return {
                'success': False,
                'message': f"启动服务失败: {start_result['message']}",
            }
    
    # --------------------------------------------------------
    # 批量操作
    # --------------------------------------------------------
    
    def start_all(self) -> Dict[str, Dict]:
        """启动所有服务"""
        results = {}
        for key in SERVICES.keys():
            results[key] = self.start(SERVICES[key]['service_name'])
        return results
    
    def stop_all(self) -> Dict[str, Dict]:
        """停止所有服务"""
        results = {}
        for key in SERVICES.keys():
            results[key] = self.stop(SERVICES[key]['service_name'])
        return results
    
    def restart_all(self) -> Dict[str, Dict]:
        """重启所有服务"""
        results = {}
        for key in SERVICES.keys():
            results[key] = self.restart(SERVICES[key]['service_name'])
        return results


# ============================================================
# 命令行界面
# ============================================================

def print_service_status(info: Dict):
    """打印服务状态"""
    # Windows 控制台兼容的图标
    status_icon = {
        'RUNNING': '[OK]',
        'STOPPED': '[--]',
        'PAUSED': '[||]',
        'ERROR': '[!!]',
        'UNKNOWN': '[??]',
    }.get(info['status'], '[??]')
    
    print(f"  {status_icon} {info['display_name']:30s} "
          f"[{info['status']:8s}] "
          f"port: {info['port']}")
    if info['status'] == 'ERROR':
        print(f"    错误: {info['status_message']}")


def cmd_status(manager: NSSMServiceManager, args):
    """查询服务状态"""
    if args.service:
        # 查询单个服务
        info = manager.get_service_info(args.service)
        print()
        print_service_status(info)
        print()
    else:
        # 查询所有服务
        print()
        print("服务状态：")
        print("-" * 70)
        for key in SERVICES.keys():
            info = manager.get_service_info(key)
            print_service_status(info)
        print("-" * 70)
        print()


def cmd_start(manager: NSSMServiceManager, args):
    """启动服务"""
    if args.service:
        result = manager.start(SERVICES[args.service]['service_name'])
        print()
        if result['success']:
            print(f"[OK] 服务启动成功: {SERVICES[args.service]['display_name']}")
        else:
            print(f"[FAIL] 服务启动失败: {result['message']}")
        print()
    else:
        # 启动所有服务
        print("\n启动所有服务...")
        results = manager.start_all()
        print()
        for key, result in results.items():
            icon = '[OK]' if result['success'] else '[FAIL]'
            print(f"  {icon} {SERVICES[key]['display_name']:30s} {result['message']}")
        print()


def cmd_stop(manager: NSSMServiceManager, args):
    """停止服务"""
    if args.service:
        result = manager.stop(SERVICES[args.service]['service_name'])
        print()
        if result['success']:
            print(f"[OK] 服务停止成功: {SERVICES[args.service]['display_name']}")
        else:
            print(f"[FAIL] 服务停止失败: {result['message']}")
        print()
    else:
        # 停止所有服务
        print("\n停止所有服务...")
        results = manager.stop_all()
        print()
        for key, result in results.items():
            icon = '[OK]' if result['success'] else '[FAIL]'
            print(f"  {icon} {SERVICES[key]['display_name']:30s} {result['message']}")
        print()


def cmd_restart(manager: NSSMServiceManager, args):
    """重启服务"""
    if args.service:
        result = manager.restart(SERVICES[args.service]['service_name'])
        print()
        if result['success']:
            print(f"[OK] 服务重启成功: {SERVICES[args.service]['display_name']}")
        else:
            print(f"[FAIL] 服务重启失败: {result['message']}")
        print()
    else:
        # 重启所有服务
        print("\n重启所有服务...")
        results = manager.restart_all()
        print()
        for key, result in results.items():
            icon = '[OK]' if result['success'] else '[FAIL]'
            print(f"  {icon} {SERVICES[key]['display_name']:30s} {result['message']}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description='DPlayer 1.0 服务管理脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/service_manager.py status              # 查看所有服务状态
  python scripts/service_manager.py status web          # 查看 web 服务状态
  python scripts/service_manager.py start web           # 启动 web 服务
  python scripts/service_manager.py stop thumbnail      # 停止 thumbnail 服务
  python scripts/service_manager.py restart web         # 重启 web 服务
  python scripts/service_manager.py start-all           # 启动所有服务
  python scripts/service_manager.py stop-all            # 停止所有服务
  python scripts/service_manager.py restart-all         # 重启所有服务

服务列表:
  web       - Web API 服务 (port: 8080)
  thumbnail - 缩略图服务 (port: 5001)
  webui     - WebUI 前端服务 (port: 5173)
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='命令')
    
    # status 命令
    status_parser = subparsers.add_parser('status', help='查询服务状态')
    status_parser.add_argument('service', nargs='?', choices=list(SERVICES.keys()),
                               help='服务名称（不指定则查询所有）')
    status_parser.set_defaults(func=cmd_status)
    
    # start 命令
    start_parser = subparsers.add_parser('start', help='启动服务')
    start_parser.add_argument('service', nargs='?', choices=list(SERVICES.keys()),
                              help='服务名称（不指定则启动所有）')
    start_parser.set_defaults(func=cmd_start)
    
    # stop 命令
    stop_parser = subparsers.add_parser('stop', help='停止服务')
    stop_parser.add_argument('service', nargs='?', choices=list(SERVICES.keys()),
                             help='服务名称（不指定则停止所有）')
    stop_parser.set_defaults(func=cmd_stop)
    
    # restart 命令
    restart_parser = subparsers.add_parser('restart', help='重启服务')
    restart_parser.add_argument('service', nargs='?', choices=list(SERVICES.keys()),
                                help='服务名称（不指定则重启所有）')
    restart_parser.set_defaults(func=cmd_restart)
    
    # start-all 命令（兼容旧用法）
    start_all_parser = subparsers.add_parser('start-all', help='启动所有服务')
    start_all_parser.set_defaults(func=lambda m, a: cmd_start(m, argparse.Namespace(service=None)))
    
    # stop-all 命令（兼容旧用法）
    stop_all_parser = subparsers.add_parser('stop-all', help='停止所有服务')
    stop_all_parser.set_defaults(func=lambda m, a: cmd_stop(m, argparse.Namespace(service=None)))
    
    # restart-all 命令（兼容旧用法）
    restart_all_parser = subparsers.add_parser('restart-all', help='重启所有服务')
    restart_all_parser.set_defaults(func=lambda m, a: cmd_restart(m, argparse.Namespace(service=None)))
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    # 创建服务管理器
    try:
        manager = NSSMServiceManager()
    except RuntimeError as e:
        print(f"\n错误: {e}\n")
        print("请先安装 NSSM: https://nssm.cc/download\n")
        return 1
    
    # 执行命令
    args.func(manager, args)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
