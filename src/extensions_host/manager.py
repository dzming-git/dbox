"""拓展插件管理器：发现插件、维护启用状态、读写独立设置、按域名匹配凭证。

本模块运行于独立的拓展宿主进程（extensions_host），不直接 import 主服务的
业务模块；涉及资源入库等副作用，由插件通过 host.ingest 等宿主契约以 HTTP
调用主服务的内部契约接口完成，从而实现拓展管理与主模块的彻底解耦。

注：旧「脚本执行引擎」（子进程 run / jobs DB / 交互输入等）已移除，
插件的能力改由各自的 backend 蓝图（create_blueprint）在框架进程内提供。
"""

import os
import json
import threading

from manifest import load_all, scripts_base_dir
from shared.credential_vault import CredentialVault

STATE_FILE = 'script_state.json'  # 持久化 enabled 覆盖，避免 reload 重置


class ScriptJobManager:
    """插件注册表：扫描 manifest、管理启用状态、读写插件设置、提供凭证保险库。"""

    def __init__(self):
        self.app = None
        self.base_dir = None
        self._lock = threading.RLock()
        self.scripts = {}
        self.vault = None
        self._state_path = None
        self._initialized = False

    # ---------- 初始化 ----------
    def init(self, app, base_dir=None):
        if self._initialized:
            return
        self.app = app
        self.base_dir = base_dir or scripts_base_dir()
        os.makedirs(self.base_dir, exist_ok=True)
        data_dir = self._data_dir()
        self._state_path = os.path.join(data_dir, STATE_FILE)
        self.vault = CredentialVault(data_dir)
        self.reload()
        self._initialized = True

    def _data_dir(self):
        env = os.environ.get('DBOX_DATA_DIR')
        if env:
            return env
        pkg_dir = os.path.dirname(os.path.abspath(__file__))    # src/extensions_host
        project_root = os.path.dirname(os.path.dirname(pkg_dir))  # 向上两级 -> 项目根 (dbox)
        return os.path.join(project_root, 'data')

    # ---------- 插件发现 / 状态 ----------
    def reload(self):
        with self._lock:
            self.scripts = load_all(self.base_dir)
            saved = self._load_state()
            for sid, sc in self.scripts.items():
                if sid in saved:
                    sc['enabled'] = bool(saved[sid])
        return len(self.scripts)

    def _load_state(self):
        if not self._state_path or not os.path.isfile(self._state_path):
            return {}
        try:
            with open(self._state_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_state(self):
        if not self._state_path:
            return
        with self._lock:
            try:
                with open(self._state_path, 'w', encoding='utf-8') as f:
                    json.dump({sid: bool(sc.get('enabled')) for sid, sc in self.scripts.items()}, f)
            except Exception:
                pass

    def set_enabled(self, script_id, enabled):
        with self._lock:
            if script_id not in self.scripts:
                return False
            self.scripts[script_id]['enabled'] = bool(enabled)
            self._save_state()
        return True

    # ---------- 插件独立设置（由 manifest.settings schema 驱动） ----------
    def _settings_path(self, script_id: str):
        if not self.base_dir:
            return None
        d = os.path.join(self.base_dir, '..', 'data', 'plugins', script_id)
        return os.path.abspath(d)

    def get_settings(self, script_id: str) -> dict:
        """返回插件当前保存的设置 {key: value}，缺失项回退到 manifest 默认值。"""
        sc = self.scripts.get(script_id)
        if not sc:
            return {}
        schema = sc.get('settings', [])
        # manifest 默认值
        out = {s['key']: s.get('default') for s in schema if 'key' in s}
        p = self._settings_path(script_id)
        fp = os.path.join(p, 'settings.json') if p else None
        if fp and os.path.isfile(fp):
            try:
                saved = json.load(open(fp, 'r', encoding='utf-8'))
                if isinstance(saved, dict):
                    out.update(saved)
            except Exception:
                pass
        return out

    def set_settings(self, script_id: str, values: dict) -> bool:
        """保存插件设置（按 schema 过滤非法 key，仅保留 manifest 声明的项）。"""
        sc = self.scripts.get(script_id)
        if not sc:
            return False
        schema = sc.get('settings', [])
        allowed = {s['key'] for s in schema if 'key' in s}
        clean = {k: v for k, v in (values or {}).items() if k in allowed}
        p = self._settings_path(script_id)
        if not p:
            return False
        try:
            os.makedirs(p, exist_ok=True)
            with open(os.path.join(p, 'settings.json'), 'w', encoding='utf-8') as f:
                json.dump(clean, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f'[plugin_manager] 保存插件设置失败 {script_id}: {e}')
            return False


mgr = ScriptJobManager()
