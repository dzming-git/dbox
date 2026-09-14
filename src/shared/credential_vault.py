# -*- coding: utf-8 -*-
"""通用凭证保险库（cookie / token / password / apikey 统一管理）。

中立能力，不依赖任何业务模块。供主 Web 服务、扩展宿主、下载器等任意子系统复用。

设计目标：
- 支持多种凭证类型（``kind``）：
  * ``cookie``  ：浏览器 cookie 集合，可物化为 Netscape/cookies.txt、JSON、header。
  * ``token``   ：API token / bearer key，物化为单文件，便于注入到
    ``ANTHROPIC_API_KEY`` 等环境变量让 CLI 免登录调用模型。
  * ``password``：账号口令。
  * ``apikey``  ：第三方服务 API key。
  后三者都是「单个字符串密文」，存取与物化方式一致。
- 所有凭证以 AES 加密落盘（密钥自动生成并持久化），避免明文泄露。
- 物化到磁盘的临时文件应在使用后及时删除（调用方负责清理）。
"""
import os
import re
import json
import base64
import struct
import hashlib
import time
from datetime import datetime, timezone

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.backends import default_backend

    _HAS_CRYPTO = True
except Exception:  # pragma: no cover - 极少数环境未安装 cryptography
    _HAS_CRYPTO = False


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


KIND_COOKIE = 'cookie'
KIND_TOKEN = 'token'
KIND_PASSWORD = 'password'
KIND_APIKEY = 'apikey'

# 全部受支持的凭证类型
CREDENTIAL_KINDS = (KIND_COOKIE, KIND_TOKEN, KIND_PASSWORD, KIND_APIKEY)
# 以「单个字符串」形式存储的类型（区别于 cookie 的 list[dict]）
_SCALAR_KINDS = (KIND_TOKEN, KIND_PASSWORD, KIND_APIKEY)


class CredentialVault:
    """通用凭证保险库（加密落盘 + 物化）。"""

    def __init__(self, data_dir: str):
        self._path = os.path.join(data_dir, 'credential_vault.json')
        self._key_path = os.path.join(data_dir, 'credential_vault.key')
        self._key = self._load_or_create_key()
        self._cache = self._load()
        self._mtime = self._file_mtime()

    # ---------- 密钥 ----------
    def _load_or_create_key(self):
        if _HAS_CRYPTO:
            if os.path.isfile(self._key_path):
                try:
                    with open(self._key_path, 'rb') as f:
                        return f.read()
                except Exception:
                    pass
            key = os.urandom(32)
            try:
                with open(self._key_path, 'wb') as f:
                    f.write(key)
                try:
                    os.chmod(self._key_path, 0o600)
                except Exception:
                    pass
            except Exception:
                pass
            return key
        # 无加密库时退化为「不加密但仍有落盘存储」（仅开发/兜底用）
        return b'__insecure_no_crypto__'

    # ---------- 加密 / 解密 ----------
    def _encrypt(self, data: bytes) -> str:
        if not _HAS_CRYPTO:
            return 'raw:' + base64.b64encode(data).decode('ascii')
        iv = os.urandom(16)
        cipher = Cipher(algorithms.AES(self._key), modes.CBC(iv),
                        backend=default_backend())
        enc = cipher.encryptor()
        p = padding.PKCS7(128).padder()
        ct = enc.update(p.update(data) + p.finalize()) + enc.finalize()
        blob = iv + ct
        return 'aes:' + base64.b64encode(blob).decode('ascii')

    def _decrypt(self, token: str) -> bytes:
        if token.startswith('raw:'):
            return base64.b64decode(token[len('raw:'):])
        if token.startswith('aes:'):
            blob = base64.b64decode(token[len('aes:'):])
            iv, ct = blob[:16], blob[16:]
            cipher = Cipher(algorithms.AES(self._key), modes.CBC(iv),
                            backend=default_backend())
            dec = cipher.decryptor()
            p = padding.PKCS7(128).unpadder()
            return p.update(dec.update(ct) + dec.finalize()) + p.finalize()
        # 未知格式按明文处理（兼容极老数据）
        return token.encode('utf-8', errors='replace')

    # ---------- 落盘 ----------
    def _load(self):
        if not os.path.isfile(self._path):
            return {'profiles': {}}
        try:
            with open(self._path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) and 'profiles' in data else {'profiles': {}}
        except Exception:
            return {'profiles': {}}

    def _save(self):
        tmp = self._path + '.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
            self._mtime = self._file_mtime()
            try:
                os.chmod(self._path, 0o600)
            except Exception:
                pass
        except Exception:
            pass

    # ---------- 惰性回源（多实例 / 多进程一致性） ----------
    def _file_mtime(self) -> float:
        """凭证落盘文件的修改时间；不存在返回 0.0。"""
        try:
            return os.path.getmtime(self._path)
        except OSError:
            return 0.0

    def _reload_if_changed(self):
        """多实例场景下，其他实例（如凭证管理 API）更新磁盘文件后，本实例的进程内
        缓存可能过期。按文件 mtime 惰性回源，避免「改了凭证却必须重启进程才生效」。

        典型场景：拓展宿主内插件各自持有独立 CredentialVault 实例，API 进程写入
        x.com Cookie 后，运行中的插件若不回源就会一直用过期 Cookie → 搜索持续 404。
        """
        m = self._file_mtime()
        if m and m > self._mtime:
            try:
                self._cache = self._load()
                self._mtime = m
            except Exception:
                pass

    # ---------- CRUD ----------
    def add(self, kind: str, name: str, domain: str, value,
            note: str = '', fmt: str = 'auto') -> str:
        """新增 / 覆盖一个凭证。

        kind: 'cookie' | 'token' | 'password' | 'apikey'
        name: 展示名（用户可读）
        domain: 域名或用途标识（如 'x.com' / 'codebuddy'）
        value: cookie 为 list[dict]；其余标量类型为 str
        fmt: cookie 物化格式（'netscape'|'json'|'header'）；标量类型固定忽略
        返回 profile id
        """
        kind = kind if kind in CREDENTIAL_KINDS else KIND_COOKIE
        pid = 'cred_' + hashlib.sha1(
            f'{kind}|{domain}|{name}'.encode('utf-8')).hexdigest()[:16]
        if kind in _SCALAR_KINDS:
            raw = (value if isinstance(value, str) else str(value)).encode('utf-8')
        else:
            raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self._cache['profiles'][pid] = {
            'id': pid,
            'kind': kind,
            'name': name,
            'domain': domain,
            'format': fmt if kind == KIND_COOKIE else 'raw',
            'secret': self._encrypt(raw),
            'note': note,
            'created_at': _now_iso(),
            'updated_at': _now_iso(),
        }
        self._save()
        return pid

    def get(self, pid: str) -> dict:
        self._reload_if_changed()
        rec = self._cache['profiles'].get(pid)
        if not rec:
            return None
        self._touch_used(pid)
        return self._decode(rec)

    def _touch_used(self, pid: str) -> None:
        """记录最近使用时间。

        有了它才能判断「长期没被用过」——一个从没被取用的凭证，
        很可能早已失效却没人发现（失效往往要等到某次任务失败才暴露）。
        失败不影响取用本身。
        """
        try:
            rec = self._cache['profiles'].get(pid)
            if rec is None:
                return
            rec['last_used_at'] = _now_iso()
            self._save()
        except Exception:
            pass

    def get_by_domain(self, domain: str, kind: str = None) -> dict:
        self._reload_if_changed()
        for rec in self._cache['profiles'].values():
            if rec.get('domain') == domain and (kind is None or rec.get('kind') == kind):
                return self._decode(rec)
        return None

    def get_by_name(self, name: str, kind: str = None) -> dict:
        self._reload_if_changed()
        for rec in self._cache['profiles'].values():
            if rec.get('name') == name and (kind is None or rec.get('kind') == kind):
                return self._decode(rec)
        return None

    def list_all(self) -> list:
        self._reload_if_changed()
        return [self._decode(rec) for rec in self._cache['profiles'].values()]

    def health(self) -> dict:
        """凭证健康度总览：按站点分组 + 每条给出状态。

        为什么需要主动体检：凭证失效通常要等到某次任务失败才被发现，
        那时排查成本很高。这里把「已过期 / 即将过期 / 从没用过」直接摆出来。

        返回 { groups: [{domain, items:[...]}], summary: {ok, expiring, expired, unknown} }
        items 只含元信息与状态，**不含任何明文**。
        """
        self._reload_if_changed()
        groups = {}
        summary = {'ok': 0, 'expiring': 0, 'expired': 0, 'unknown': 0}
        for rec in self._cache['profiles'].values():
            decoded = self._decode(rec)
            status, message, expires_at = evaluate_health(decoded)
            summary[status] = summary.get(status, 0) + 1
            domain = rec.get('domain') or '未分类'
            groups.setdefault(domain, []).append({
                'id': rec.get('id'),
                'name': rec.get('name'),
                'kind': rec.get('kind'),
                'note': rec.get('note'),
                'updated_at': rec.get('updated_at'),
                'last_used_at': rec.get('last_used_at'),
                'has_value': bool(decoded.get('value') or decoded.get('cookies')),
                'status': status,
                'message': message,
                'expires_at': expires_at,
            })
        out = []
        for domain in sorted(groups.keys()):
            items = sorted(groups[domain], key=lambda x: (x.get('name') or ''))
            # 整组取最差状态，便于在分组标题上一眼看到问题
            worst = 'ok'
            for it in items:
                if it['status'] == 'expired':
                    worst = 'expired'
                    break
                if it['status'] == 'expiring':
                    worst = 'expiring'
                elif it['status'] == 'unknown' and worst == 'ok':
                    worst = 'unknown'
            out.append({'domain': domain, 'status': worst, 'items': items})
        return {'groups': out, 'summary': summary}

    def delete(self, pid: str) -> bool:
        if pid in self._cache['profiles']:
            del self._cache['profiles'][pid]
            self._save()
            return True
        return False

    def _decode(self, rec: dict) -> dict:
        out = dict(rec)
        raw = self._decrypt(rec.get('secret', ''))
        if rec.get('kind') in _SCALAR_KINDS:
            out['value'] = raw.decode('utf-8', errors='replace')
        else:
            try:
                out['cookies'] = json.loads(raw.decode('utf-8', errors='replace'))
            except Exception:
                # JSON 解析失败（如 netscape 文本直接加密存储），保留原始明文
                out['cookies'] = []
                out['_raw'] = raw.decode('utf-8', errors='replace')
        return out

    # ---------- 标量凭证（token / password / apikey）便捷方法 ----------
    def set_secret(self, kind: str, domain: str, value: str,
                   name: str = None, note: str = '') -> str:
        """写入一个标量凭证（token/password/apikey），返回 id。"""
        if kind not in _SCALAR_KINDS:
            raise ValueError(f'不支持的标量凭证类型: {kind}')
        return self.add(kind, name or f'{kind}:{domain}', domain, value,
                        note=note, fmt='raw')

    def get_secret(self, kind: str, domain: str = None, name: str = None) -> str:
        """取标量凭证明文；优先按 domain，其次 name。不存在返回 None。"""
        rec = self.get_by_domain(domain, kind) if domain else None
        if not rec and name:
            rec = self.get_by_name(name, kind)
        return rec.get('value') if rec else None

    def set_token(self, domain: str, token: str, name: str = None, note: str = '') -> str:
        return self.set_secret(KIND_TOKEN, domain, token, name=name, note=note)

    def get_token(self, domain: str = None, name: str = None) -> str:
        return self.get_secret(KIND_TOKEN, domain=domain, name=name)

    def set_password(self, domain: str, password: str, name: str = None, note: str = '') -> str:
        return self.set_secret(KIND_PASSWORD, domain, password, name=name, note=note)

    def get_password(self, domain: str = None, name: str = None) -> str:
        return self.get_secret(KIND_PASSWORD, domain=domain, name=name)

    def set_apikey(self, domain: str, apikey: str, name: str = None, note: str = '') -> str:
        return self.set_secret(KIND_APIKEY, domain, apikey, name=name, note=note)

    def get_apikey(self, domain: str = None, name: str = None) -> str:
        return self.get_secret(KIND_APIKEY, domain=domain, name=name)

    # ---------- 物化（供子进程 / CLI 消费） ----------
    def materialize(self, pid: str, working_dir: str):
        """把凭证物化到 working_dir 临时文件，返回 (path, format)。

        cookie：按 rec.format 生成对应文件（netscape/json/header）。
        标量凭证（token/password/apikey）：写入单文件明文（供读取后注入环境变量）。
        """
        rec = self.get(pid)
        if not rec:
            raise KeyError(f'凭证不存在: {pid}')
        os.makedirs(working_dir, exist_ok=True)
        kind = rec.get('kind')
        if kind in _SCALAR_KINDS:
            path = os.path.join(working_dir, f'.{kind}_{pid}.txt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(rec.get('value', ''))
            return path, 'raw'
        # cookie 物化
        fmt = rec.get('format') or 'netscape'
        cookies = rec.get('cookies') or []
        if fmt == 'json':
            path = os.path.join(working_dir, f'cookies_{pid}.json')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            return path, 'json'
        if fmt == 'header':
            hdr = '; '.join(
                f'{c.get("name")}={c.get("value")}' for c in cookies
                if c.get("name"))
            path = os.path.join(working_dir, f'cookie_header_{pid}.txt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(hdr)
            return path, 'header'
        # 默认 netscape cookies.txt
        path = os.path.join(working_dir, f'cookies_{pid}.txt')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('# Netscape HTTP Cookie File\n')
        for c in cookies:
            f.write(self._netscape_line(c) + '\n')
        return path, 'netscape'

    @staticmethod
    def _netscape_line(c: dict) -> str:
        domain = c.get('domain', '')
        if domain and not domain.startswith('.'):
            domain = '.' + domain
        include_sub = 'TRUE' if c.get('domain', '').startswith('.') else 'FALSE'
        path = c.get('path', '/') or '/'
        secure = 'TRUE' if c.get('secure') else 'FALSE'
        expires = c.get('expirationDate') or c.get('expires') or 0
        try:
            expires = int(expires)
        except Exception:
            expires = 0
        name = c.get('name', '')
        val = c.get('value', '')
        return '\t'.join([domain, include_sub, path, secure, str(expires), name, val])


def evaluate_health(decoded: dict):
    """评估一条凭证的健康度（纯函数，便于单测）。

    入参是**已解码**的凭证（含 value / cookies）。返回 (status, message, expires_at)：
      ok       —— 有值且未过期
      expiring —— 7 天内过期
      expired  —— 已过期，或压根没有值
      unknown  —— 无法判定（标量凭证没有过期时间，且从未被取用过）

    说明：
    - Cookie 里带 expirationDate（Unix 秒，可能是小数或字符串）；
      会话 cookie 没有这个字段，按「未知」处理而不是误判为过期。
    - token / apikey / password 自身没有过期信息：只有在「从未被取用过」
      时才提示未知——用过就说明它此刻大概率是有效的。
    """
    now = time.time()
    kind = decoded.get('kind')

    if kind == KIND_COOKIE:
        cookies = decoded.get('cookies') or []
        if not cookies:
            return 'expired', '没有存任何 Cookie', None
        stamps = []
        for c in cookies:
            if not isinstance(c, dict):
                continue
            raw = c.get('expirationDate') or c.get('expires')
            if raw in (None, '', 0):
                continue
            try:
                stamps.append(float(raw))
            except (TypeError, ValueError):
                continue
        if not stamps:
            return 'unknown', '全是会话 Cookie，无法判断是否过期', None
        earliest = min(stamps)
        iso = datetime.fromtimestamp(earliest).isoformat() + 'Z'
        if earliest <= now:
            return 'expired', '已过期', iso
        if earliest - now <= 7 * 86400:
            days = int((earliest - now) // 86400) + 1
            return 'expiring', f'{days} 天内过期', iso
        return 'ok', '正常', iso

    has_value = bool(decoded.get('value'))
    if not has_value:
        return 'expired', '没有存值', None
    if not decoded.get('last_used_at'):
        return 'unknown', '从未被使用过，无法确认是否仍然有效', None
    return 'ok', '正常', None


def data_dir_for(vault_subdir: str = '') -> str:
    """解析通用保险库的数据目录（与运行时数据区一致）。"""
    env = os.environ.get('DBOX_DATA_DIR')
    if env:
        base = env
    else:
        pkg_dir = os.path.dirname(os.path.abspath(__file__))  # src/shared
        project_root = os.path.dirname(os.path.dirname(pkg_dir))
        base = os.path.join(project_root, 'data')
    if vault_subdir:
        return os.path.join(base, vault_subdir)
    return base
