# -*- coding: utf-8 -*-
"""框架级托管缓存分区（CachePartition）。

一个分区 = 磁盘上一个目录，存放 key -> file 的 LRU 缓存：

- 文件名：``<hash(key)[:key_len]><ext>``（flat 模式直接落 root；nested 模式仅以
  root 作为命名空间根，内部结构由调用方自行管理）
- 索引：``root/.cache_index.json`` 记录每个 key 的 ``{ext, size, atime}``，用于统计/淘汰
- 容量：超过 cap 时按 atime 淘汰最久未访问的文件（LRU）

设计目标：本模块被两处复用——
1) ``plugin_host.Host.cache()`` 返回 CachePartition，插件后端直读直写，不再各写一套 LRU；
2) ``cached`` 微服务扫描所有分区做集中治理（统计占用 / 远程清理 / 容量上限 / 启动自检迁移）。

迁移兼容：文件名以 hash(key) 为前缀，因此只要 key 的哈希函数与历史一致（x 用 md5、
pixiv 用 sha256[:32]），把旧目录文件整体搬进新分区 root 后 ``reindex()`` 即可无缝承接，
旧缓存全部保留、无需重新下载。
"""
import os
import json
import time
import threading
import hashlib
import shutil


class CachePartition:
    """一个命名空间下的托管磁盘缓存分区。"""

    def __init__(self, root, key_hash='sha256', key_len=32, default_ext='',
                 cap=None, nested=False, lazy_index=True):
        """
        Args:
            root:        分区根目录（由 host.cache / 微服务治理器解析得到）
            key_hash:    key 的哈希算法名（x 媒体用 'md5'，pixiv 用 'sha256'）
            key_len:     哈希截取长度（md5=32，sha256 取 32）
            default_ext: 未显式给 ext 时使用的默认扩展名
            cap:         容量上限（字节）；None 表示不自动淘汰
            nested:      是否为嵌套结构（如 ugoira 的 <id>/frames/），True 时只计数不清索引
            lazy_index:  True=延迟到首次访问再加载索引
        """
        self.root = root
        self.key_hash = key_hash
        self.key_len = key_len
        self.default_ext = default_ext
        self.cap = cap
        self.nested = nested
        self._index_file = os.path.join(root, '.cache_index.json')
        self._lock = threading.RLock()
        self._entries = {}          # hash(key) -> {ext, size, atime}
        self._dirty = False
        os.makedirs(root, exist_ok=True)
        if not lazy_index:
            self.reindex()

    # ---------- 路径 / 标识 ----------
    def hash_of(self, key):
        return hashlib.new(self.key_hash, key.encode('utf-8')).hexdigest()[:self.key_len]

    def _ek(self, key):
        """索引键 = 文件名前缀（哈希值），保证 get/register 与 reindex 一致。"""
        return self.hash_of(key)

    def path(self, key, ext=None):
        """返回 key 对应的（预期）文件路径，无论是否存在。"""
        ext = ext or self.default_ext
        return os.path.join(self.root, self.hash_of(key) + ext)

    # ---------- 索引维护 ----------
    def reindex(self):
        """扫描磁盘重建索引（迁移后 / 索引缺失或损坏时调用）。"""
        with self._lock:
            self._entries = {}
            if not os.path.isdir(self.root):
                return
            for fn in os.listdir(self.root):
                if fn.startswith('.'):
                    continue
                full = os.path.join(self.root, fn)
                if not os.path.isfile(full):
                    continue
                base, ext = os.path.splitext(fn)
                if not base:
                    continue
                try:
                    st = os.stat(full)
                except Exception:
                    continue
                self._entries[base] = {
                    'ext': ext,
                    'size': st.st_size,
                    'atime': st.st_atime,
                }
            self._save_index()

    def _save_index(self):
        if self.nested:
            return
        try:
            tmp = self._index_file + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self._entries, f)
            os.replace(tmp, self._index_file)
        except Exception:
            pass

    # ---------- 读写 ----------
    def exists_meta(self, key):
        with self._lock:
            return self._ek(key) in self._entries

    def get(self, key):
        """命中返回 (path, ext)，并刷新访问时间；未命中返回 None。"""
        h = self._ek(key)
        with self._lock:
            ent = self._entries.get(h)
            if not ent:
                return None
            p = os.path.join(self.root, h + ent.get('ext', ''))
            if not os.path.exists(p):
                self._entries.pop(h, None)
                self._save_index()
                return None
            ent['atime'] = time.time()
            self._dirty = True
            return p, ent.get('ext', '')

    def put_file(self, key, tmp_path, ext, keep_on_fail=False):
        """把已落盘的临时文件原子改名登记进分区；返回最终路径或 None。

        与直接写文件相比：先写 .part 再 os.replace 保证「要么完整要么没有」，
        避免流式响应中途被打断留下半截文件被当成有效缓存。
        """
        dest = self.path(key, ext)
        replaced = False
        for _ in range(40):
            try:
                os.replace(tmp_path, dest)
                replaced = True
                break
            except Exception:
                time.sleep(0.15)
        if not replaced:
            if not keep_on_fail:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            return None
        try:
            sz = os.path.getsize(dest)
        except Exception:
            sz = 0
        h = self._ek(key)
        with self._lock:
            self._entries[h] = {'ext': ext, 'size': sz, 'atime': time.time()}
            self._dirty = True
        self.flush()
        self.enforce_cap()
        return dest

    def register(self, key, ext, size=None):
        """外部已写完文件（非经 put_file）后登记，使其进入索引统计与淘汰。"""
        dest = self.path(key, ext)
        if size is None:
            try:
                size = os.path.getsize(dest)
            except Exception:
                size = 0
        h = self._ek(key)
        with self._lock:
            self._entries[h] = {'ext': ext, 'size': size, 'atime': time.time()}
            self._dirty = True
        self.flush()
        self.enforce_cap()

    def touch(self, key):
        h = self._ek(key)
        with self._lock:
            ent = self._entries.get(h)
            if ent:
                ent['atime'] = time.time()
                self._dirty = True

    def remove(self, key):
        h = self._ek(key)
        with self._lock:
            ent = self._entries.pop(h, None)
            if ent:
                try:
                    os.remove(os.path.join(self.root, h + ent.get('ext', '')))
                except Exception:
                    pass
            self._save_index()

    def stat(self):
        """返回 {count, bytes, cap, nested}。bytes 为实际磁盘占用（递归）。"""
        with self._lock:
            total = sum(e.get('size', 0) for e in self._entries.values())
            count = len(self._entries)
        if not self._entries or self.nested:
            total = self.disk_bytes()
            count = self._count_files()
        return {'count': count, 'bytes': total, 'cap': self.cap, 'nested': self.nested}

    def disk_bytes(self):
        total = 0
        try:
            for dirpath, _, fnames in os.walk(self.root):
                for fn in fnames:
                    if fn.startswith('.'):
                        continue
                    try:
                        total += os.path.getsize(os.path.join(dirpath, fn))
                    except Exception:
                        pass
        except Exception:
            pass
        return total

    def _count_files(self):
        n = 0
        try:
            for dirpath, _, fnames in os.walk(self.root):
                for fn in fnames:
                    if fn.startswith('.'):
                        continue
                    n += 1
        except Exception:
            pass
        return n

    def clear(self):
        """清空分区全部文件（含嵌套子目录），并重置索引。"""
        with self._lock:
            for fn in os.listdir(self.root):
                if fn.startswith('.'):
                    continue
                p = os.path.join(self.root, fn)
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                    elif os.path.isdir(p):
                        shutil.rmtree(p)
                except Exception:
                    pass
            self._entries = {}
            self._save_index()

    def enforce_cap(self, cap=None):
        """超过容量上限时按 atime 淘汰最久未访问的文件（flat 模式）。"""
        if cap is None:
            cap = self.cap
        if not cap or self.nested:
            return
        with self._lock:
            total = sum(e.get('size', 0) for e in self._entries.values())
            if total <= cap:
                return
            order = sorted(self._entries.items(),
                           key=lambda kv: kv[1].get('atime', 0))
            for h, ent in order:
                if total <= cap:
                    break
                p = os.path.join(self.root, h + ent.get('ext', ''))
                try:
                    if os.path.isfile(p):
                        os.remove(p)
                    else:
                        shutil.rmtree(p)
                except Exception:
                    pass
                total -= ent.get('size', 0)
                del self._entries[h]
            self._save_index()

    def flush(self):
        if self._dirty:
            self._save_index()
            self._dirty = False


# ============================================================
# 一次性迁移（旧散落缓存目录 -> 托管分区）
# ============================================================
def migrate_legacy_cache(legacy_dir, partition, nested=False, remove_source=True):
    """把 legacy_dir 下的缓存文件搬进 partition.root。

    幂等：partition.root 已存在 ``.migrated`` 标记则跳过。成功后写标记，并可选清理旧目录。
    返回 True 表示本次执行了迁移（或已迁移完成）。
    """
    marker = os.path.join(partition.root, '.migrated')
    if os.path.exists(marker):
        return True
    if not os.path.isdir(legacy_dir) or not os.listdir(legacy_dir):
        # 无旧缓存可迁：仍写标记，避免每次启动都来探查
        try:
            open(marker, 'w', encoding='utf-8').close()
        except Exception:
            pass
        return True
    os.makedirs(partition.root, exist_ok=True)
    if nested:
        for name in os.listdir(legacy_dir):
            src = os.path.join(legacy_dir, name)
            dst = os.path.join(partition.root, name)
            try:
                if os.path.isdir(src):
                    if not os.path.exists(dst):
                        shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
            except Exception:
                pass
    else:
        for fn in os.listdir(legacy_dir):
            src = os.path.join(legacy_dir, fn)
            if not os.path.isfile(src):
                continue
            try:
                shutil.copy2(src, os.path.join(partition.root, fn))
            except Exception:
                pass
    # 重建索引（flat 模式按文件名前缀恢复 entries）
    if not nested:
        partition.reindex()
    try:
        open(marker, 'w', encoding='utf-8').close()
    except Exception:
        pass
    if remove_source:
        try:
            shutil.rmtree(legacy_dir, ignore_errors=True)
        except Exception:
            pass
    return True
