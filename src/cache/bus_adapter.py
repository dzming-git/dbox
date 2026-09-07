# -*- coding: utf-8 -*-
"""缓存管理微服务的总线适配器（com.dbox.cached）。

把散落在各拓展里的媒体/资源磁盘缓存统一纳入框架治理：
- 自动发现所有托管分区（``<DATA>/plugins/<key>/cache/<name>`` 与 ``<DATA>/cache/<name>``）
- 提供统计占用、远程清理、容量上限等总线方法
- 后台周期执行容量上限兜底淘汰
- 启动时自检：把历史散落目录（x media_cache / pixiv img_cache / ugoira_cache）迁入托管存储

总线服务定义：
  Service:        com.dbox.cached
  Interface:      com.dbox.Cached
  Object Path:    /com/dbox/cached
"""
import os
import sys
import json
import time
import threading

_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from servicebus.service_base import BaseDBusService
from shared.cache_store import CachePartition, migrate_legacy_cache


def resolve_data_dir():
    # 与框架其余服务一致的数据目录解析顺序：
    #   1) 显式 DBOX_DATA_DIR（两端应一致设置）
    #   2) 生产运行时数据区 %ProgramData%\Dbox\data（拓展宿主落盘处）
    #   3) 仓库内 data/（dev 兜底）
    # 仅回退到仓库 data 会在“服务以生产数据区运行、缓存服务却装成开发模式”时
    # 扫错目录、看到全假数据且清空间操作打不到真实缓存。
    candidates = []
    env = os.environ.get('DBOX_DATA_DIR')
    if env:
        candidates.append(env)
    prog = os.environ.get('ProgramData')
    if prog:
        candidates.append(os.path.join(prog, 'Dbox', 'data'))
    candidates.append(os.path.join(os.path.dirname(_SRC_DIR), 'data'))
    for c in candidates:
        if c and os.path.isdir(c):
            return os.path.abspath(c)
    return os.path.abspath(candidates[-1])


# 历史散落缓存目录 -> 托管分区 的映射（启动自检迁移用）
# (拓展 key, 托管缓存名, 旧相对目录名, key_hash, key_len, default_ext, nested)
LEGACY_MAP = [
    ('x',      'media',  'media_cache/lru', 'md5',    32, '',      False),
    ('pixiv',  'img',    'img_cache',       'sha256', 32, '.bin',  False),
    ('pixiv',  'ugoira', 'ugoira_cache',    'sha256', 32, '',      True),
]

DEFAULT_CAP = 512 * 1024 * 1024          # 单分区默认 512MB
NESTED_DEFAULT_CAP = 2 * 1024 * 1024 * 1024


class CacheGovernor:
    """扫描并治理全部缓存分区。"""

    def __init__(self, data_dir):
        self.data_dir = data_dir
        self._caps_file = os.path.join(data_dir, 'cache', '_caps.json')
        self._lock = threading.RLock()
        self._partitions = {}             # namespace_id -> CachePartition
        self._caps = self._load_caps()

    # ---------- 容量配置 ----------
    def _load_caps(self):
        try:
            with open(self._caps_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_caps(self):
        try:
            os.makedirs(os.path.dirname(self._caps_file), exist_ok=True)
            tmp = self._caps_file + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self._caps, f)
            os.replace(tmp, self._caps_file)
        except Exception:
            pass

    def cap_for(self, ns_id, nested=False):
        if ns_id in self._caps:
            return self._caps[ns_id]
        return NESTED_DEFAULT_CAP if nested else DEFAULT_CAP

    def set_cap(self, ns_id, bytes_):
        self._caps[ns_id] = int(bytes_)
        self._save_caps()
        with self._lock:
            p = self._partitions.get(ns_id)
            if p:
                p.cap = int(bytes_)
                p.enforce_cap()

    # ---------- 发现 ----------
    def _discover(self):
        found = {}
        # 1) 各拓展的 cache 分区
        plugins_dir = os.path.join(self.data_dir, 'plugins')
        if os.path.isdir(plugins_dir):
            for key in os.listdir(plugins_dir):
                cache_dir = os.path.join(plugins_dir, key, 'cache')
                if not os.path.isdir(cache_dir):
                    continue
                for name in os.listdir(cache_dir):
                    root = os.path.join(cache_dir, name)
                    if not os.path.isdir(root):
                        continue
                    found['%s/%s' % (key, name)] = root
        # 2) 顶层共享 cache 分区
        shared_dir = os.path.join(self.data_dir, 'cache')
        if os.path.isdir(shared_dir):
            for name in os.listdir(shared_dir):
                root = os.path.join(shared_dir, name)
                if not os.path.isdir(root) or name.startswith('_'):
                    continue
                found['shared/%s' % name] = root
        return found

    def _is_nested(self, root):
        try:
            return any(os.path.isdir(os.path.join(root, n))
                       for n in os.listdir(root))
        except Exception:
            return False

    def refresh(self):
        """重新扫描磁盘，更新分区表（新出现的分区即时纳入治理）。"""
        found = self._discover()
        with self._lock:
            for ns_id, root in found.items():
                if ns_id in self._partitions:
                    continue
                nested = self._is_nested(root)
                p = CachePartition(root, cap=self.cap_for(ns_id, nested),
                                   nested=nested, lazy_index=True)
                if not nested:
                    p.reindex()
                self._partitions[ns_id] = p

    # ---------- 启动自检迁移 ----------
    def self_check_migrate(self):
        for key, name, legacy_rel, kh, kl, ext, nested in LEGACY_MAP:
            legacy_dir = os.path.join(self.data_dir, 'plugins', key, legacy_rel)
            # 兼容旧式：x 的 media_cache 实际是 <data_dir>/media_cache/lru
            if not os.path.isdir(legacy_dir):
                # 也尝试不带 /lru 的目录（部分部署差异）
                alt = os.path.join(self.data_dir, 'plugins', key,
                                    legacy_rel.split('/')[0])
                if os.path.isdir(alt):
                    legacy_dir = alt
                else:
                    continue
            target_root = os.path.join(self.data_dir, 'plugins', key, 'cache', name)
            partition = CachePartition(target_root, key_hash=kh, key_len=kl,
                                       default_ext=ext, nested=nested,
                                       cap=self.cap_for('%s/%s' % (key, name), nested))
            try:
                migrate_legacy_cache(legacy_dir, partition, nested=nested)
            except Exception as e:
                sys.stderr.write('[cached] migrate %s failed: %s\n' % (ns_id, e))

    # ---------- 对外查询 ----------
    def namespaces(self):
        with self._lock:
            ids = list(self._partitions.keys())
        out = []
        for ns_id in ids:
            p = self._partitions[ns_id]
            st = p.stat()
            out.append({
                'id': ns_id,
                'root': p.root,
                'count': st['count'],
                'bytes': st['bytes'],
                'cap': st['cap'],
                'nested': st['nested'],
            })
        return out

    def stats(self, ns_id):
        with self._lock:
            p = self._partitions.get(ns_id)
        if not p:
            return None
        st = p.stat()
        st['id'] = ns_id
        return st

    def path_of(self, ns_id):
        with self._lock:
            p = self._partitions.get(ns_id)
        return p.root if p else None

    def clear(self, ns_id):
        if ns_id == '*' or ns_id == 'all':
            with self._lock:
                ids = list(self._partitions.keys())
            for i in ids:
                self.clear(i)
            return {'cleared': ids}
        with self._lock:
            p = self._partitions.get(ns_id)
        if not p:
            return {'success': False, 'error': 'unknown namespace'}
        p.clear()
        return {'success': True, 'id': ns_id}

    def enforce_all(self):
        with self._lock:
            parts = list(self._partitions.items())
        for ns_id, p in parts:
            try:
                p.enforce_cap()
            except Exception:
                pass


class BusCacheAdapter(BaseDBusService):
    BUS_NAME = 'com.dbox.cached'
    INTERFACES = ['com.dbox.Cached']
    OBJECT_PATH = '/com/dbox/cached'

    def __init__(self, data_dir=None, host='127.0.0.1',
                 rpc_port=15555, pub_port=15556):
        super().__init__(host, rpc_port, pub_port)
        self._data_dir = data_dir or resolve_data_dir()
        self._governor = CacheGovernor(self._data_dir)
        self._governor.self_check_migrate()
        self._governor.refresh()

    # ============ 总线方法 ============
    def on_method_get_namespaces(self, params=None):
        return {'namespaces': self._governor.namespaces()}

    def on_method_get_stats(self, params=None):
        params = params or {}
        ns_id = params.get('namespace')
        if not ns_id:
            return {'success': False, 'error': 'namespace required'}
        st = self._governor.stats(ns_id)
        if st is None:
            return {'success': False, 'error': 'unknown namespace'}
        return {'success': True, 'stats': st}

    def on_method_set_cap(self, params=None):
        params = params or {}
        ns_id = params.get('namespace')
        cap = params.get('bytes')
        if not ns_id or cap is None:
            return {'success': False, 'error': 'namespace and bytes required'}
        self._governor.set_cap(ns_id, int(cap))
        return {'success': True, 'id': ns_id, 'cap': int(cap)}

    def on_method_clear(self, params=None):
        params = params or {}
        ns_id = params.get('namespace', '*')
        return self._governor.clear(ns_id)

    def on_method_get_path(self, params=None):
        params = params or {}
        ns_id = params.get('namespace')
        if not ns_id:
            return {'success': False, 'error': 'namespace required'}
        p = self._governor.path_of(ns_id)
        if not p:
            return {'success': False, 'error': 'unknown namespace'}
        return {'success': True, 'path': p}

    def on_method_refresh(self, params=None):
        self._governor.refresh()
        return {'success': True, 'namespaces': len(self._governor.namespaces())}

    # ============ 后台周期治理 ============
    def start_background(self):
        def loop():
            while self._running:
                try:
                    self._governor.self_check_migrate()
                    self._governor.refresh()
                    self._governor.enforce_all()
                except Exception:
                    pass
                time.sleep(30)
        t = threading.Thread(target=loop, daemon=True, name='cache-gov')
        t.start()

    def start(self, block=False):
        super().start(block=block)
        if not block:
            self.start_background()
