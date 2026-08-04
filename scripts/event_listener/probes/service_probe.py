"""服务状态探针（内置）。

返回 {service_key: {'service_key': str, 'status': 'running'/'stopped'/'unknown'}}。
监听器据此与上一次快照做 diff，当运行状态变化时触发 service.status_changed 事件。

实现说明：
- 服务列表从 scripts/service_manager.py 的 SERVICES 读取（按路径显式加载，避免与
  src/web/service_manager.py 重名冲突）。
- 状态直接调用 nssm status <service_name> 获取，不解析 CLI 的人类可读输出，
  避免格式变化导致解析失败。
"""
import os
import shutil
import subprocess
import importlib.util

_DBOX_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_SM_PATH = os.path.join(_DBOX_ROOT, 'scripts', 'service_manager.py')

# NSSM 可执行文件常见位置。
# 注意：监听器以 NSSM 服务账户运行时 PATH 与交互式登录不同，
# 因此不能只依赖 PATH，必须带绝对路径兜底。
_NSSM_CANDIDATES = [
    r'C:\Tools\nssm.exe',
    r'C:\nssm\win64\nssm.exe',
    r'C:\nssm\nssm.exe',
    r'C:\tools\nssm\nssm.exe',
    r'C:\Program Files\nssm\nssm.exe',
    os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'WinGet', 'Links', 'nssm.exe'),
]

_nssm_exe = None
_services = None


def _find_nssm():
    """定位 nssm.exe（结果缓存）。优先绝对路径，其次 PATH。"""
    global _nssm_exe
    if _nssm_exe is not None:
        return _nssm_exe
    for p in _NSSM_CANDIDATES:
        if p and os.path.exists(p):
            _nssm_exe = p
            return _nssm_exe
    found = shutil.which('nssm')
    if found:
        _nssm_exe = found
        return _nssm_exe
    print("[probe:service] 未找到 nssm.exe，服务状态将保持 unknown")
    _nssm_exe = ''
    return _nssm_exe


def _load_services():
    """读取服务定义（结果缓存）。返回 {key: service_name}。"""
    global _services
    if _services is not None:
        return _services
    try:
        spec = importlib.util.spec_from_file_location('scripts_service_manager_probe', _SM_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _services = {k: v['service_name'] for k, v in mod.SERVICES.items()}
    except Exception as e:
        print(f"[probe:service] 读取服务列表失败: {e}")
        _services = {}
    return _services


def _nssm_status(service_name):
    """调用 nssm status，返回 running / stopped / unknown。"""
    nssm = _find_nssm()
    if not nssm:
        return 'unknown'
    try:
        proc = subprocess.run(
            [nssm, 'status', service_name],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15,
        )
    except Exception as e:
        print(f"[probe:service] 查询 {service_name} 状态失败: {e}")
        return 'unknown'

    text = ((proc.stdout or '') + (proc.stderr or '')).upper()
    if 'SERVICE_RUNNING' in text or 'RUNNING' in text:
        return 'running'
    if 'SERVICE_STOPPED' in text or 'STOPPED' in text:
        return 'stopped'
    if 'SERVICE_PAUSED' in text or 'PAUSED' in text:
        return 'paused'
    # 服务未安装时 nssm 返回非零并提示找不到服务
    if 'NOT' in text and 'EXIST' in text:
        return 'not_installed'
    return 'unknown'


def snapshot():
    """返回各服务状态快照。

    注意：状态查不出来（unknown）时**不放入快照**。因为监听器是拿本次快照与
    上次快照做 diff，若把 unknown 写进去，一次偶发的查询失败就会产生
    running -> unknown、下一轮 unknown -> running 两次假事件（事件风暴）。
    跳过该条目即保留上一次的基线，等能确定状态时再比对。
    """
    out = {}
    for key, service_name in _load_services().items():
        status = _nssm_status(service_name)
        if status == 'unknown':
            continue
        out[key] = {
            'service_key': key,
            'service_name': service_name,
            'status': status,
        }
    return out
