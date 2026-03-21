"""
DPlayer 2.0 - 统一服务管理器
管理 Web 服务和缩略图服务的启动、停止、重启

支持两种运行模式：
  1. 源码目录直接运行（开发模式）
  2. 从已安装的运行目录运行（NSSM 服务模式）

运行目录优先级：
  DPLAYER_RUNTIME 环境变量 > install.json 记录的 runtime_dir > 脚本所在目录父目录
"""
import os
import sys
import json
import time
import subprocess
import logging
from pathlib import Path
from datetime import datetime


def _resolve_runtime_dir() -> str:
    """
    解析服务实际工作目录，不依赖硬编码路径。
    优先级：
      1. 环境变量 DPLAYER_RUNTIME
      2. 同级目录下 install.json 的 runtime_dir 字段
      3. 当前文件所在目录的父目录（源码目录直接运行）
    """
    # 1. 环境变量
    env_dir = os.environ.get('DPLAYER_RUNTIME', '').strip()
    if env_dir and os.path.isdir(env_dir):
        return env_dir

    # 2. install.json（部署到运行目录时会存在）
    candidate = Path(__file__).parent.parent.resolve()
    install_json = candidate / 'install.json'
    if install_json.exists():
        try:
            info = json.loads(install_json.read_text(encoding='utf-8'))
            rt = info.get('runtime_dir', '')
            if rt and os.path.isdir(rt):
                return rt
        except Exception:
            pass

    # 3. 回退：脚本所在目录父级（源码/运行目录均适用）
    return str(candidate)


# 获取运行目录（动态解析，不硬编码源码路径）
PROJECT_DIR = Path(_resolve_runtime_dir())
BASEDIR = str(PROJECT_DIR)
LOG_DIR = os.path.join(BASEDIR, 'logs')

# 配置日志
os.makedirs(LOG_DIR, exist_ok=True)
logger = logging.getLogger('service_manager')
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.FileHandler(os.path.join(LOG_DIR, 'service_manager.log'), encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)

# Windows特定导入
IS_WINDOWS = os.name == 'nt'
if IS_WINDOWS:
    try:
        import win32service
        import win32serviceutil
        import win32con
        import psutil
        HAS_WIN32 = True
        HAS_PSUTIL = True
    except ImportError:
        HAS_WIN32 = False
        HAS_PSUTIL = False

# 服务定义
SERVICES = {
    'web': {
        'name': 'DPlayer-Web',
        'display_name': 'DPlayer 2.0 Web服务',
        'port': 8080,
        'script': os.path.join(BASEDIR, 'web.py'),
        'pid_file': os.path.join(BASEDIR, 'instance', 'web.pid'),
        'service_name': 'dplayer-web',
    },
    'thumbnail': {
        'name': 'DPlayer-Thumbnail',
        'display_name': 'DPlayer 2.0 缩略图服务',
        'port': 5001,
        'script': os.path.join(BASEDIR, 'thumbnail_service.py'),
        'pid_file': os.path.join(BASEDIR, 'instance', 'thumbnail.pid'),
        'service_name': 'dplayer-thumbnail',
    },
    'webui': {
        'name': 'DPlayer-WebUI',
        'display_name': 'DPlayer 2.0 WebUI服务',
        'port': 5173,
        'script': os.path.join(BASEDIR, 'services', 'webui_service.py'),
        'pid_file': os.path.join(BASEDIR, 'instance', 'webui.pid'),
        'service_name': 'dplayer-webui',
    }
}


def _port_listening(port):
    """检查端口是否在监听"""
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex(('127.0.0.1', port)) == 0
    except:
        return False


def _get_pid_from_file(pid_file):
    """从PID文件读取进程ID"""
    try:
        if os.path.exists(pid_file):
            with open(pid_file, 'r') as f:
                return int(f.read().strip())
    except:
        pass
    return None


def _pid_for_port(port):
    """获取占用端口的进程PID"""
    if not HAS_PSUTIL:
        return None
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                return conn.pid
    except:
        pass
    return None


def _get_windows_service_status(service_name):
    """获取Windows服务状态"""
    if not HAS_WIN32:
        return None
    try:
        scm = win32service.OpenSCManager(None, None, win32con.GENERIC_READ)
        svc = win32service.OpenService(scm, service_name, win32con.GENERIC_READ)
        status = win32service.QueryServiceStatus(svc)
        win32service.CloseServiceHandle(svc)
        win32service.CloseServiceHandle(scm)
        return 'RUNNING' if status[1] == win32service.SERVICE_RUNNING else 'STOPPED'
    except:
        return None


def start_service(svc_key, force=False):
    """启动服务"""
    if svc_key not in SERVICES:
        return {'success': False, 'message': f'未知服务: {svc_key}'}
    
    svc = SERVICES[svc_key]
    port = svc['port']
    script = svc['script']
    pid_file = svc['pid_file']
    
    logger.info(f"启动服务: {svc['display_name']} (端口: {port})")
    
    # 检查端口
    if _port_listening(port):
        pid = _pid_for_port(port)
        logger.info(f"服务已在运行 (PID: {pid})")
        return {'success': True, 'message': '服务已在运行', 'pid': pid}
    
    # 直接启动进程
    try:
        venv_python = os.path.join(BASEDIR, 'venv', 'Scripts', 'python.exe') if IS_WINDOWS else os.path.join(BASEDIR, 'venv', 'bin', 'python')
        python_exe = venv_python if os.path.exists(venv_python) else sys.executable
        
        # 创建日志目录
        os.makedirs(LOG_DIR, exist_ok=True)
        os.makedirs(os.path.dirname(pid_file), exist_ok=True)
        
        stdout_file = open(os.path.join(LOG_DIR, f'{svc_key}_stdout.log'), 'w', encoding='utf-8')
        stderr_file = open(os.path.join(LOG_DIR, f'{svc_key}_stderr.log'), 'w', encoding='utf-8')
        
        # 设置环境变量，允许服务启动
        env = os.environ.copy()
        env['DPLAYER_SERVICE_MODE'] = '1'
        
        proc = subprocess.Popen(
            [python_exe, script],
            cwd=BASEDIR,
            stdout=stdout_file,
            stderr=stderr_file,
            env=env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
        )
        
        stdout_file.close()
        stderr_file.close()
        
        with open(pid_file, 'w') as f:
            f.write(str(proc.pid))
        
        logger.info(f"进程已启动: PID={proc.pid}")
        
        # 等待端口就绪
        for _ in range(20):
            time.sleep(0.5)
            if _port_listening(port):
                logger.info(f"服务启动成功 (PID: {proc.pid}, 端口: {port})")
                return {'success': True, 'message': '启动成功', 'pid': proc.pid}
        
        return {'success': True, 'message': '进程已启动，等待端口就绪', 'pid': proc.pid}
    
    except Exception as e:
        logger.error(f"启动失败: {e}")
        return {'success': False, 'message': str(e)}


def stop_service(svc_key):
    """停止服务"""
    if svc_key not in SERVICES:
        return {'success': False, 'message': f'未知服务: {svc_key}'}
    
    svc = SERVICES[svc_key]
    port = svc['port']
    pid_file = svc['pid_file']
    
    logger.info(f"停止服务: {svc['display_name']}")
    
    pid = _pid_for_port(port) or _get_pid_from_file(pid_file)
    
    if not pid:
        logger.info("服务未在运行")
        return {'success': True, 'message': '服务未在运行'}
    
    try:
        proc = psutil.Process(pid)
        proc.terminate()
        proc.wait(timeout=5)
        
        if os.path.exists(pid_file):
            os.remove(pid_file)
        
        logger.info(f"服务已停止 (PID: {pid})")
        return {'success': True, 'message': '服务已停止'}
    
    except psutil.NoSuchProcess:
        if os.path.exists(pid_file):
            os.remove(pid_file)
        return {'success': True, 'message': '进程已不存在'}
    except Exception as e:
        logger.error(f"停止失败: {e}")
        return {'success': False, 'message': str(e)}


def get_service_status(svc_key):
    """获取服务状态"""
    if svc_key not in SERVICES:
        return {'running': False, 'error': f'未知服务: {svc_key}'}
    
    svc = SERVICES[svc_key]
    port = svc['port']
    pid_file = svc['pid_file']
    
    pid = _pid_for_port(port) or _get_pid_from_file(pid_file)
    port_listening = _port_listening(port)
    
    return {
        'running': port_listening,
        'pid': pid,
        'port': port,
        'port_listening': port_listening,
        'name': svc['display_name']
    }


def get_all_services_status():
    """获取所有服务状态"""
    return {key: get_service_status(key) for key in SERVICES.keys()}


def install_nssm_service(svc_key, runtime_dir: str | None = None):
    """
    安装NSSM服务。

    Args:
        svc_key:     服务 key（'web' 或 'thumbnail'）
        runtime_dir: 运行目录路径（None 时使用 BASEDIR）
    """
    if svc_key not in SERVICES:
        return {'success': False, 'message': f'未知服务: {svc_key}'}

    work_dir = Path(runtime_dir).resolve() if runtime_dir else PROJECT_DIR
    svc = SERVICES[svc_key]

    # 入口脚本指向运行目录
    script = work_dir / Path(svc['script']).name
    service_name = svc['service_name']
    log_dir = work_dir / 'logs'
    log_dir.mkdir(exist_ok=True)

    venv_python = work_dir / 'venv' / 'Scripts' / 'python.exe'
    python_exe = str(venv_python) if venv_python.exists() else sys.executable

    # 使用nssm安装服务
    cmd = f'nssm install {service_name} "{python_exe}" "{script}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0:
        # 配置服务参数（工作目录指向运行目录，不是源码目录）
        subprocess.run(f'nssm set {service_name} AppDirectory "{work_dir}"', shell=True)
        subprocess.run(f'nssm set {service_name} DisplayName "{svc["display_name"]}"', shell=True)
        subprocess.run(f'nssm set {service_name} Description "{svc["name"]}"', shell=True)
        subprocess.run(f'nssm set {service_name} Start SERVICE_AUTO_START', shell=True)
        subprocess.run(f'nssm set {service_name} AppStdout "{log_dir / (svc_key + "_stdout.log")}"', shell=True)
        subprocess.run(f'nssm set {service_name} AppStderr "{log_dir / (svc_key + "_stderr.log")}"', shell=True)
        subprocess.run(f'nssm set {service_name} AppRestartDelay "5000"', shell=True)
        subprocess.run(f'nssm set {service_name} AppEnvironmentExtra "DPLAYER_SERVICE_MODE=1"', shell=True)

        logger.info(f"NSSM服务已安装: {service_name}（工作目录: {work_dir}）")
        return {'success': True, 'message': f'服务已安装: {service_name}', 'work_dir': str(work_dir)}
    else:
        logger.error(f"安装服务失败: {result.stderr}")
        return {'success': False, 'message': result.stderr}


def uninstall_nssm_service(svc_key):
    """卸载NSSM服务"""
    if svc_key not in SERVICES:
        return {'success': False, 'message': f'未知服务: {svc_key}'}
    
    service_name = SERVICES[svc_key]['service_name']
    
    # 停止并移除服务
    subprocess.run(f'nssm stop {service_name}', shell=True)
    result = subprocess.run(f'nssm remove {service_name} confirm', shell=True, capture_output=True, text=True)
    
    if result.returncode == 0:
        logger.info(f"NSSM服务已卸载: {service_name}")
        return {'success': True, 'message': f'服务已卸载: {service_name}'}
    else:
        return {'success': False, 'message': result.stderr}


__all__ = [
    'SERVICES',
    'start_service',
    'stop_service',
    'get_service_status',
    'get_all_services_status',
    'install_nssm_service',
    'uninstall_nssm_service',
]
