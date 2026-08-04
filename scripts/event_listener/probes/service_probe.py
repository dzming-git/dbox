"""服务状态探针（内置）。

返回 {service_key: {'status': 'running'/'stopped'/'unknown'}}。
监听器据此与上一次快照做 diff，当运行状态变化时触发 service.status_changed 事件。

通过调用服务管理器（scripts/service_manager.py status <key>）获取真实状态，
避免直接 import 管理模块带来的重依赖耦合。
"""
import os
import sys
import importlib.util
import subprocess

_DBOX_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _service_keys():
    try:
        _path = os.path.join(_DBOX_ROOT, 'scripts', 'service_manager.py')
        _spec = importlib.util.spec_from_file_location('scripts_service_manager_probe', _path)
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        return list(_mod.SERVICES.keys())
    except Exception as e:
        print(f"[probe:service] 读取服务列表失败: {e}")
        return []


def snapshot():
    out = {}
    for key in _service_keys():
        try:
            proc = subprocess.run(
                ['python', os.path.join(_DBOX_ROOT, 'scripts', 'service_manager.py'), 'status', key],
                cwd=_DBOX_ROOT, capture_output=True, text=True, timeout=30,
            )
            text = (proc.stdout or '') + (proc.stderr or '')
            status = 'unknown'
            for line in text.splitlines():
                line = line.strip()
                if line.startswith('[RUNNING]'):
                    status = 'running'; break
                if line.startswith('[STOPPED]') or line.startswith('[NOT_INSTALLED]'):
                    status = 'stopped'; break
            out[key] = {'status': status}
        except Exception as e:
            print(f"[probe:service] 查询 {key} 状态失败: {e}")
            out[key] = {'status': 'unknown'}
    return out
