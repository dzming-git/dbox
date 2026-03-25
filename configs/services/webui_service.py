#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DPlayer WebUI 服务启动器

通过 Python 包装器启动前端 Vite 开发服务器，使其可以被 NSSM 管理。
"""
import os
import sys
import subprocess
import signal
from liblog import get_module_logger
from pathlib import Path

# 服务启动守卫：必须通过 NSSM 启动
_CONFIGS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_CONFIGS_DIR))
_DATA_DIR = os.path.join(_PROJECT_ROOT, 'data')
_SRC_DIR = os.path.join(_PROJECT_ROOT, 'src')

for _p in [_CONFIGS_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
from launcher_guard import check_service_launch
check_service_launch('DPlayer WebUI Service', 'configs/services/webui_service.py')

# 配置日志
LOG_DIR = os.path.join(_DATA_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
s - %(levelname)s - %(message)s',
    handlers=[    ]
)
log = get_module_logger()

# 前端目录
FRONTEND_DIR = os.path.join(_SRC_DIR, 'webui')

def check_node_modules():
    """检查 node_modules 是否存在"""
    node_modules = os.path.join(FRONTEND_DIR, 'node_modules')
    if not os.path.exists(node_modules):
        log.debug('ERROR', f"node_modules 不存在，请先运行: cd {FRONTEND_DIR} && npm install")
        return False
    return True

def find_npm():
    """查找 npm 可执行文件路径"""
    # 常见路径
    possible_paths = [
        r'C:\Program Files\nodejs\npm.cmd',
        r'C:\Program Files (x86)\nodejs\npm.cmd',
        os.path.expanduser(r'~\AppData\Roaming\npm\npm.cmd'),
    ]
    
    # 从 PATH 环境变量查找
    for path in os.environ.get('PATH', '').split(os.pathsep):
        npm_path = os.path.join(path.strip(), 'npm.cmd')
        if os.path.exists(npm_path):
            return npm_path
    
    # 检查常见路径
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    # 默认使用 npm，希望它在 PATH 中
    return 'npm'


def start_webui():
    """启动 WebUI 服务"""
    log.runtime('INFO', "=" * 60)
    log.runtime('INFO', "DPlayer WebUI 服务启动")
    log.runtime('INFO', "=" * 60)
    log.runtime('INFO', f"工作目录: {FRONTEND_DIR}")
    log.runtime('INFO', f"服务地址: http://0.0.0.0:5173")
    
    if not check_node_modules():
        sys.exit(1)
    
    # 设置环境变量
    env = os.environ.copy()
    env['NODE_ENV'] = 'production'
    env['RUN_MODE'] = 'windows_service'
    
    # 查找 npm
    npm_cmd = find_npm()
    log.runtime('INFO', f"使用 npm: {npm_cmd}")
    
    try:
        # 启动 Vite 开发服务器
        # 注意：dev 模式适合开发环境，生产环境应该使用 preview 模式（需要先生成 dist）
        cmd = [npm_cmd, 'run', 'dev', '--', '--host', '0.0.0.0', '--port', '5173']
        
        log.runtime('INFO', f"执行命令: {' '.join(cmd)}")
        
        process = subprocess.Popen(
            cmd,
            cwd=FRONTEND_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        )
        
        log.runtime('INFO', f"WebUI 服务已启动，PID: {process.pid}")
        
        # 实时输出日志（忽略编码错误）
        while True:
            try:
                line = process.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if line:
                    log.runtime('INFO', f"[Vite] {line}")
            except UnicodeDecodeError:
                continue
            except Exception:
                break
        
        # 等待进程结束
        return_code = process.wait()
        log.runtime('INFO', f"WebUI 服务已退出，返回码: {return_code}")
        
    except KeyboardInterrupt:
        log.runtime('INFO', "收到中断信号，正在停止服务...")
        if process:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
    except Exception as e:
        log.debug('ERROR', f"启动失败: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    start_webui()
