"""
系统网络优化模块

自动执行以下优化：
1. 配置Windows防火墙规则
2. 优化TCP连接池设置
3. 启用TCP保活机制
4. 优化Python Socket配置

每个微服务启动时调用此模块进行系统级优化
"""

import os
import sys
from liblog import get_module_logger
import subprocess
import socket
import platform

# 创建日志记录器
log = get_module_logger()


class SystemOptimizer:
    """系统优化器类"""

    def __init__(self):
        self.windows = platform.system() == 'Windows'
        self.admin_required = True  # Windows下需要管理员权限

    def check_admin_rights(self):
        """
        检查是否有管理员权限

        Returns:
            bool: 是否有管理员权限
        """
        if not self.windows:
            return True  # Linux/Unix通常不需要

        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False

    def optimize_firewall(self, port, service_name):
        """
        配置Windows防火墙规则

        Args:
            port (int): 要开放的端口号
            service_name (str): 服务名称

        Returns:
            bool: 是否成功
        """
        if not self.windows:
            return True  # Linux/Unix不需要防火墙规则

        try:
            rule_name = f"DPlayer {service_name} 端口{port}"

            # 删除旧规则
            subprocess.run(
                f'netsh advfirewall firewall delete rule name="{rule_name}"',
                shell=True,
                capture_output=True
            )

            # 添加新规则（所有网络配置文件）
            result = subprocess.run(
                f'netsh advfirewall firewall add rule name="{rule_name}" '
                f'dir=in action=allow protocol=TCP localport={port} profile=any',
                shell=True,
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                optimizer_log.runtime('INFO', f'防火墙规则已添加: {rule_name}')
                return True
            else:
                optimizer_log.debug('WARN', f'防火墙规则添加失败: {rule_name}, 错误: {result.stderr}')
                return False

        except Exception as e:
            optimizer_log.debug('WARN', f'防火墙优化失败: {e}')
            return False

    def optimize_tcp_pool(self):
        """
        优化TCP连接池设置

        Returns:
            bool: 是否成功
        """
        if not self.windows:
            return True

        try:
            success = True

            # 增加动态端口范围
            result = subprocess.run(
                'netsh int ipv4 set dynamicport tcp start=1025 num=64512',
                shell=True,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                optimizer_log.debug('WARN', f'动态端口范围优化失败: {result.stderr}')
                success = False
            else:
                optimizer_log.runtime('INFO', '动态端口范围已优化: 1025-65537')

            # 减少TIME_WAIT超时时间（30秒）
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r'SYSTEM\CurrentControlSet\Services\Tcpip\Parameters',
                    0,
                    winreg.KEY_SET_VALUE
                )
                winreg.SetValueEx(key, 'TcpTimedWaitDelay', 0, winreg.REG_DWORD, 30)
                winreg.CloseKey(key)
                optimizer_log.runtime('INFO', 'TIME_WAIT超时时间已设置为30秒')
            except Exception as e:
                optimizer_log.debug('WARN', f'TCP超时优化失败: {e}')
                # 尝试使用reg命令
                subprocess.run(
                    'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters" '
                    '/v TcpTimedWaitDelay /t REG_DWORD /d 30 /f',
                    shell=True,
                    capture_output=True
                )

            return success

        except Exception as e:
            optimizer_log.debug('WARN', f'TCP连接池优化失败: {e}')
            return False

    def enable_tcp_keepalive(self):
        """
        启用TCP保活机制

        Returns:
            bool: 是否成功
        """
        if not self.windows:
            return True

        try:
            import winreg

            # 保活时间（60秒 = 0x3C000毫秒）
            # 保活间隔（10秒 = 0x2710毫秒）
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r'SYSTEM\CurrentControlSet\Services\Tcpip\Parameters',
                0,
                winreg.KEY_SET_VALUE
            )

            try:
                winreg.SetValueEx(key, 'KeepAliveTime', 0, winreg.REG_DWORD, 0x3C000)
                optimizer_log.runtime('INFO', 'TCP保活时间已设置为60秒')
            except:
                pass  # 可能已存在

            try:
                winreg.SetValueEx(key, 'KeepAliveInterval', 0, winreg.REG_DWORD, 0x2710)
                optimizer_log.runtime('INFO', 'TCP保活间隔已设置为10秒')
            except:
                pass  # 可能已存在

            winreg.CloseKey(key)
            return True

        except Exception as e:
            optimizer_log.debug('WARN', f'TCP保活机制启用失败: {e}')
            return False

    def flush_dns_cache(self):
        """
        刷新DNS缓存

        Returns:
            bool: 是否成功
        """
        if not self.windows:
            return True

        try:
            subprocess.run('ipconfig /flushdns', shell=True, capture_output=True)
            optimizer_log.runtime('INFO', 'DNS缓存已刷新')
            return True
        except Exception as e:
            optimizer_log.debug('WARN', f'DNS缓存刷新失败: {e}')
            return False

    def optimize_socket(self, sock):
        """
        优化Python Socket配置

        Args:
            sock: socket对象

        Returns:
            socket: 优化后的socket对象
        """
        try:
            # 设置TCP保活机制
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 6)

            # 允许地址重用
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, 'SO_REUSEPORT'):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

            # 设置缓冲区大小
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)

            # 禁用Nagle算法
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            optimizer_log.debug('DEBUG', 'Socket配置已优化')
        except Exception as e:
            optimizer_log.debug('WARN', f'Socket优化失败: {e}')

        return sock

    def optimize_all(self, ports=None, service_names=None):
        """
        执行所有系统优化

        Args:
            ports (list): 端口列表，如 [80, 8080]
            service_names (list): 服务名称列表，如 ['主应用', '管理后台']

        Returns:
            dict: 优化结果统计
        """
        optimizer_log.runtime('INFO', '=' * 50)
        optimizer_log.runtime('INFO', '开始执行系统网络优化...')
        optimizer_log.runtime('INFO', '=' * 50)

        results = {
            'firewall': False,
            'tcp_pool': False,
            'tcp_keepalive': False,
            'dns_cache': False
        }

        # 检查管理员权限
        if self.windows and not self.check_admin_rights():
            optimizer_log.debug('WARN', '警告: 未以管理员权限运行，部分优化可能失败')
            optimizer_log.debug('WARN', '建议以管理员权限启动服务')

        # 配置防火墙规则
        if ports and service_names and len(ports) == len(service_names):
            firewall_success = True
            for port, name in zip(ports, service_names):
                if not self.optimize_firewall(port, name):
                    firewall_success = False
            results['firewall'] = firewall_success
        else:
            results['firewall'] = None  # 跳过

        # 优化TCP连接池
        results['tcp_pool'] = self.optimize_tcp_pool()

        # 启用TCP保活机制
        results['tcp_keepalive'] = self.enable_tcp_keepalive()

        # 刷新DNS缓存
        results['dns_cache'] = self.flush_dns_cache()

        optimizer_log.runtime('INFO', '=' * 50)
        optimizer_log.runtime('INFO', '系统优化完成')
        optimizer_log.runtime('INFO', '=' * 50)

        return results


# 全局优化器实例
_optimizer = None


def get_optimizer():
    """获取优化器实例"""
    global _optimizer
    if _optimizer is None:
        _optimizer = SystemOptimizer()
    return _optimizer


def optimize_system(ports=None, service_names=None):
    """
    便捷函数：执行系统优化

    Args:
        ports (list): 端口列表，如 [80, 8080]
        service_names (list): 服务名称列表，如 ['主应用', '管理后台']

    Returns:
        dict: 优化结果统计

    Example:
        from utils.system_optimizer import optimize_system

        # 在服务启动时调用
        optimize_system(
            ports=[80, 8080],
            service_names=['主应用', '管理后台']
        )
    """
    optimizer = get_optimizer()
    return optimizer.optimize_all(ports, service_names)


def optimize_socket(sock):
    """
    便捷函数：优化Socket配置

    Args:
        sock: socket对象

    Returns:
        socket: 优化后的socket对象

    Example:
        import socket
        from utils.system_optimizer import optimize_socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock = optimize_socket(sock)
    """
    optimizer = get_optimizer()
    return optimizer.optimize_socket(sock)


if __name__ == '__main__':
    # 测试系统优化
        print('测试系统优化...')
    results = optimize_system(
        ports=[80, 8080],
        service_names=['主应用', '管理后台']
    )

    print('\n优化结果:')
    print(f'  防火墙: {"成功" if results["firewall"] else "失败" if results["firewall"] is False else "跳过"}')
    print(f'  TCP连接池: {"成功" if results["tcp_pool"] else "失败"}')
    print(f'  TCP保活: {"成功" if results["tcp_keepalive"] else "失败"}')
    print(f'  DNS缓存: {"成功" if results["dns_cache"] else "失败"}')

    # 测试Socket优化
    print('\n测试Socket优化...')
    test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    test_sock = optimize_socket(test_sock)
    print('Socket配置已优化')
    test_sock.close()
