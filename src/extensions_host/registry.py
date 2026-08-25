"""拓展资源集中注册表：把「文件夹名 key」映射到其真实地址。

设计目标（对应需求「拓展用文件夹名作唯一 key，框架提供真实地址翻译」）：
- 每个拓展在加载时以文件夹名（filesystem 唯一）注册一个 key；
- 框架据 key 派生/翻译其数据库、缓存、URL 前缀等真实地址；
- 一个拓展可拥有多个数据库（db(name)）、多个缓存（cache(name)）、多个 URL 前缀
  （在 /api/ext/<key>/ 下挂载多个 blueprint），全部集中登记于此，便于查询与治理。

本模块为纯函数 + 线程安全 dict，不依赖 Flask / 任何插件内部实现。
"""
import os
import threading

# key -> {
#   'key': str, 'folder': str, 'data_dir': str,
#   'databases': {name: path}, 'caches': {name: path}, 'url_prefixes': [str]
# }
_REGISTRY = {}
_LOCK = threading.RLock()


def register_extension(key, folder, data_dir):
    """拓展加载时登记其 key（=文件夹名）与私有数据目录。"""
    with _LOCK:
        rec = _REGISTRY.get(key)
        if rec is None:
            rec = {
                'key': key,
                'folder': folder,
                'data_dir': data_dir,
                'databases': {},
                'caches': {},
                'url_prefixes': [],
            }
            _REGISTRY[key] = rec
        else:
            # 重复注册（如 reload）：仅同步最新信息，保留已创建的资源路径
            rec['folder'] = folder
            rec['data_dir'] = data_dir
    return _REGISTRY[key]


def get(key):
    with _LOCK:
        return _REGISTRY.get(key)


def list_keys():
    with _LOCK:
        return list(_REGISTRY.keys())


def db_path(key, name='main'):
    """返回该 key 下名为 name 的数据库文件真实路径（按需创建目录）。"""
    with _LOCK:
        rec = _REGISTRY.get(key)
        if not rec:
            return None
        dbs = rec['databases']
        if name not in dbs:
            p = os.path.join(rec['data_dir'], 'db', '%s.db' % name)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            dbs[name] = p
        return dbs[name]


def cache_path(key, name='main'):
    """返回该 key 下名为 name 的缓存目录真实路径（按需创建目录）。"""
    with _LOCK:
        rec = _REGISTRY.get(key)
        if not rec:
            return None
        cs = rec['caches']
        if name not in cs:
            p = os.path.join(rec['data_dir'], 'cache', name)
            os.makedirs(p, exist_ok=True)
            cs[name] = p
        return cs[name]


def register_url(key, prefix):
    """记录该 key 注册的一个 URL 前缀（多 URL 能力）。"""
    with _LOCK:
        rec = _REGISTRY.get(key)
        if rec and prefix and prefix not in rec['url_prefixes']:
            rec['url_prefixes'].append(prefix)


def resolve(key, kind, name='main'):
    """真实地址翻译：kind ∈ {db, cache, url}。

    - db   -> db_path(key, name)
    - cache-> cache_path(key, name)
    - url  -> 该 key 已注册的 URL 前缀列表（name 作为索引，默认取第一个/全部）
    """
    with _LOCK:
        rec = _REGISTRY.get(key)
        if not rec:
            return None
        if kind == 'db':
            return db_path(key, name)
        if kind == 'cache':
            return cache_path(key, name)
        if kind == 'url':
            if name == 'main':
                return rec['url_prefixes'][0] if rec['url_prefixes'] else None
            # name 为索引（整数或数字字符串）
            try:
                idx = int(name)
                return rec['url_prefixes'][idx] if 0 <= idx < len(rec['url_prefixes']) else None
            except (TypeError, ValueError):
                return None
        return None
