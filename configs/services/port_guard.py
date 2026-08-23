#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dbox - 端口单实例守卫

解决「NSSM 服务拉起一个 + 人/AI 又手动 python xxx.py 拉一个」导致的端口冲突、
双实例抢数据、配置改了不生效等问题。

核心逻辑：
  1. 启动时尝试 bind 目标 (host, port)。
  2. 若地址已被占用 -> 查出占用者 PID，打印清晰错误并退出（绝不静默失败或抢端口）。
  3. 若空闲 -> 立即 close，把端口交还给后续 Flask/Werkzeug 正常绑定（同进程内 close
     后立刻可重绑，竞态窗口极小且可接受；本守卫的目的是「防止第二个实例」，而非
     「独占端口到运行时」）。

Windows 下用 netstat 解析占用 PID；无 netstat 时回退到 psutil（若有）。

用法（放在各服务 __main__ 入口最前面，守卫之后）：
    from port_guard import guard_port
    guard_port(host, port)
"""
import os
import sys
import socket
import subprocess


def _pid_for_port(port: int):
    """返回占用 TCP 端口的 PID（Windows 用 netstat，无则返回 None）。"""
    try:
        out = subprocess.check_output(
            ['netstat', '-ano', '-p', 'TCP'],
            stderr=subprocess.DEVNULL, text=True, timeout=10)
        for line in out.splitlines():
            parts = line.split()
            # 形如: TCP    0.0.0.0:8093    0.0.0.0:0    LISTENING    12345
            if len(parts) >= 5 and parts[0] == 'TCP' and parts[3] == 'LISTENING':
                local = parts[1]
                if local.endswith(':%d' % port) or local.endswith(']:%d' % port):
                    return int(parts[4])
    except Exception:
        pass
    # 回退：psutil
    try:
        import psutil
        for c in psutil.net_connections(kind='tcp'):
            if c.laddr and c.laddr.port == port and c.status == psutil.CONN_LISTEN:
                return c.pid
    except Exception:
        pass
    return None


def guard_port(host: str, port: int) -> None:
    """端口单实例守卫。占用则打印错误并 sys.exit(1)。"""
    # 0.0.0.0 监听时，实际绑定到任意网卡；探测时分别尝试 0.0.0.0 与 127.0.0.1 都能命中。
    probe_hosts = []
    if host in ('0.0.0.0', ''):
        probe_hosts = ['0.0.0.0', '127.0.0.1']
    else:
        probe_hosts = [host]

    occupied_pid = None
    for ph in probe_hosts:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)  # 关闭复用，确保真实探测
        try:
            s.bind((ph, port))
            # 空闲：释放交还给后续绑定
            s.close()
            occupied_pid = None
            break
        except OSError:
            s.close()
            occupied_pid = _pid_for_port(port)
            if occupied_pid is None:
                # 探测主机无占用，但绑定仍失败，可能端口在另一地址被占
                continue
            break

    if occupied_pid is not None:
        msg = (
            "\n"
            "======================================================================\n"
            "  ERROR: Port %d is already in use (PID %s)\n"
            "======================================================================\n"
            "\n"
            "  Another instance of this service is already running on this port.\n"
            "  Refusing to start a second instance (would cause port conflict /\n"
            "  data race / config changes not taking effect).\n"
            "\n"
            "  To manage services, use the unified script instead of manual launch:\n"
            "      scripts\\dbox.ps1 restart <service>\n"
            "  or NSSM directly:\n"
            "      nssm restart dbox-<service>\n"
            "\n"
            "  If you are sure no instance should be here, kill the old one first:\n"
            "      taskkill /PID %s /F\n"
            "======================================================================\n"
        ) % (port, occupied_pid, occupied_pid)
        sys.stderr.write(msg)
        sys.stderr.flush()
        sys.exit(1)
