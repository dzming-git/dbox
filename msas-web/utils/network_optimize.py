"""
优化网络连接配置，解决局域网偶现连接失败问题
Windows / Linux 兼容版本
"""

import sys
import socket


def optimize_socket(sock):
    """
    优化socket配置，提高连接稳定性（跨平台）

    解决问题：
    1. 连接超时导致的偶发失败
    2. TCP保活机制缺失导致的连接断开
    3. 连接重用问题
    """
    is_windows = sys.platform == 'win32'

    # 允许地址重用，避免 TIME_WAIT 导致端口占用（Windows/Linux 均支持）
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # SO_REUSEPORT 仅 Linux 支持，Windows 跳过
    if not is_windows:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass

    # 设置发送和接收缓冲区大小（Windows/Linux 均支持）
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)  # 64KB 发送缓冲区
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)  # 64KB 接收缓冲区

    # 禁用 Nagle 算法，减少小数据包延迟（Windows/Linux 均支持）
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    # TCP 保活机制
    # Windows: 用 SIO_KEEPALIVE_VALS ioctl（不需要 TCP_KEEPIDLE）
    # Linux:   用 TCP_KEEPIDLE / TCP_KEEPINTVL / TCP_KEEPCNT
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if is_windows:
            # Windows 通过 ioctl 设置保活间隔：keepalivetime=60s, keepaliveinterval=10s
            import struct
            keepalive_vals = struct.pack('lll', 1, 60000, 10000)  # 单位毫秒
            sock.ioctl(socket.SIO_KEEPALIVE_VALS, keepalive_vals)
        else:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 6)
    except (AttributeError, OSError):
        # 保活设置失败不影响正常运行
        pass

    return sock


def optimize_flask_app(app):
    """
    优化Flask应用的网络配置（仅在使用 Werkzeug 开发服务器时有效）

    注意：生产环境推荐直接使用 Waitress，不需要调用此函数。
    """
    import werkzeug.serving

    original_setup = werkzeug.serving.WSGIRequestHandler.connection_setup

    def optimized_connection_setup(self):
        original_setup(self)
        try:
            if hasattr(self.connection, 'setsockopt'):
                self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception as e:
            print(f"[警告] Socket优化失败: {e}")

    werkzeug.serving.WSGIRequestHandler.connection_setup = optimized_connection_setup


if __name__ == '__main__':
    print("测试socket优化配置...")
    test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    test_sock = optimize_socket(test_sock)
    print("Socket配置已优化:")
    print(f"  - 平台: {'Windows' if sys.platform == 'win32' else 'Linux/Mac'}")
    print(f"  - TCP保活: 启用")
    print(f"  - 地址重用: 启用")
    print(f"  - Nagle算法: 禁用")
    print(f"  - 缓冲区: 64KB")
    test_sock.close()
    print("\n请在 app.py 和 admin_app.py 中使用 Waitress 启动服务。")
