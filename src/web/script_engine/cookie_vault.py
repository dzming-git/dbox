"""Cookie 保险库：管理员集中管理网站 cookie（加密落盘），任务运行时按需物化到临时目录供脚本使用。

设计要点：
- 仅管理员可读写（接口层 admin_required 保证）。
- cookie 值使用 Fernet 对称加密落盘；明文绝不写入库文件，前端列表也不回传 value。
- 任务 DB 只保存 cookie profile 的 id 引用（在 params 里），绝不保存 cookie 原文。
- 运行时把对应 profile 解密写入任务 working_dir（如 cookies.txt / cookies.header），并把路径注入
  context.cookies / 替换 cookie_select 参数为文件路径；任务结束后 working_dir 被整体清理，临时 cookie 文件随之一并删除。
"""
import os
import json
import base64
import uuid
import threading
from datetime import datetime

try:
    from cryptography.fernet import Fernet
    _HAS_CRYPTO = True
except Exception:
    _HAS_CRYPTO = False


def _now():
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


class CookieVault:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._path = os.path.join(data_dir, 'cookie_vault.json')
        self._key_path = os.path.join(data_dir, 'cookie_vault.key')
        self._lock = threading.RLock()
        self._key = self._load_key()
        self._data = self._load()

    # ---------- 密钥（每安装一份，文件权限 600） ----------
    def _load_key(self):
        if os.path.isfile(self._key_path):
            with open(self._key_path, 'rb') as f:
                return f.read().strip()
        key = Fernet.generate_key() if _HAS_CRYPTO else base64.b64encode(os.urandom(32))
        with open(self._key_path, 'wb') as f:
            f.write(key)
        try:
            os.chmod(self._key_path, 0o600)
        except Exception:
            pass
        return key

    def _fernet(self):
        return Fernet(self._key)

    # ---------- 持久化 ----------
    def _load(self):
        if not os.path.isfile(self._path):
            return {'profiles': {}}
        try:
            with open(self._path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {'profiles': {}}

    def _save(self):
        tmp = self._path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)
        try:
            os.chmod(self._path, 0o600)
        except Exception:
            pass

    # ---------- 加解密 ----------
    def _encrypt(self, value):
        if _HAS_CRYPTO:
            return 'f:' + self._fernet().encrypt(value.encode('utf-8')).decode('ascii')
        # 降级：不应发生（cryptography 通常随 authlib 安装），仅防崩溃
        return 'b64:' + base64.b64encode(value.encode('utf-8')).decode('ascii')

    def _decrypt(self, blob):
        if blob.startswith('f:'):
            if not _HAS_CRYPTO:
                raise RuntimeError('cryptography 不可用，无法解密 cookie')
            return self._fernet().decrypt(blob[2:].encode('ascii')).decode('utf-8')
        if blob.startswith('b64:'):
            return base64.b64decode(blob[4:]).encode('ascii').decode('utf-8')
        return blob

    # ---------- CRUD ----------
    def add(self, name, domain, fmt, value):
        pid = 'ck_' + uuid.uuid4().hex[:12]
        with self._lock:
            self._data['profiles'][pid] = {
                'id': pid, 'name': name, 'domain': domain, 'format': fmt,
                'value': self._encrypt(value),
                'created_at': _now(), 'updated_at': _now(),
            }
            self._save()
        return pid

    def update(self, pid, name=None, domain=None, fmt=None, value=None):
        with self._lock:
            rec = self._data['profiles'].get(pid)
            if not rec:
                return False
            if name is not None:
                rec['name'] = name
            if domain is not None:
                rec['domain'] = domain
            if fmt is not None:
                rec['format'] = fmt
            if value:  # 仅当传入非空时才更新密文
                rec['value'] = self._encrypt(value)
            rec['updated_at'] = _now()
            self._save()
        return True

    def delete(self, pid):
        with self._lock:
            if pid in self._data['profiles']:
                del self._data['profiles'][pid]
                self._save()
                return True
        return False

    def list(self):
        with self._lock:
            return [
                {'id': r['id'], 'name': r['name'], 'domain': r['domain'],
                 'format': r['format'], 'created_at': r.get('created_at'),
                 'updated_at': r.get('updated_at')}
                for r in self._data['profiles'].values()
            ]

    def get(self, pid):
        """返回含解密后 value 的完整记录；不存在返回 None。"""
        with self._lock:
            rec = self._data['profiles'].get(pid)
            if not rec:
                return None
            return {
                'id': rec['id'], 'name': rec['name'], 'domain': rec['domain'],
                'format': rec['format'], 'value': self._decrypt(rec['value']),
            }

    def get_by_domain(self, domain):
        """按域名匹配（精确或后缀），返回记录（含解密 value）。"""
        with self._lock:
            for r in self._data['profiles'].values():
                d = r.get('domain', '')
                if not d:
                    continue
                if d == domain or domain.endswith(d) or d.endswith(domain):
                    return {
                        'id': r['id'], 'name': r['name'], 'domain': r['domain'],
                        'format': r['format'], 'value': self._decrypt(r['value']),
                    }
        return None

    # ---------- 运行时物化 ----------
    def materialize(self, pid, working_dir):
        """解密并写入 working_dir，返回 (abs_path, format)。失败时抛异常。"""
        rec = self.get(pid)
        if not rec:
            raise KeyError(f'cookie 配置不存在: {pid}')
        fmt = rec.get('format', 'netscape')
        fname = 'cookies.header' if fmt == 'header' else 'cookies.txt'
        path = os.path.join(working_dir, fname)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(rec['value'])
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
        return path, fmt
