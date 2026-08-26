"""纯插件宿主：为插件后端提供稳定契约（host 对象）。

框架加载插件时，构造一个 Host 实例注入到插件的 create_blueprint(host) 工厂。
插件**只**通过本对象与框架交互，严禁 import extensions_host / shared / web 等内部包。

设计目标：
- 插件自包含：逻辑、路由、前端全在插件文件夹内；
- 框架零入侵：删除插件文件夹后，load_all 扫不到即跳过，框架不报错；
- 契约通信：插件依赖 host 的稳定接口，而非框架内部实现。
"""
import os
import logging

from functools import wraps
from flask import request, g, jsonify

from authlib.jose import jwt

# 复用 routes 中既有的 JWT 校验逻辑（框架自身的鉴权实现，插件不重复造轮子）。
from routes import _JWT_SECRETS, ADMIN_ROLE, _resolve_jwt_secrets

# 以下为框架能力，通过 host 暴露给插件（插件不再直接 import 这些内部模块）。
from shared.credential_vault import CredentialVault, data_dir_for
from shared.unified_tasks import (
    init_task_manager as _ut_init,
    create_task, update_task, delete_task, get_task, get_tasks,
)
from registry import (
    register_extension as _reg_register_extension,
    db_path as _reg_db_path,
    cache_path as _reg_cache_path,
    register_url as _reg_register_url,
    resolve as _reg_resolve,
)


class _VaultProxy:
    """插件凭证读写代理，封装 CredentialVault 实现细节。"""

    def __init__(self):
        self._vault = CredentialVault(data_dir_for())

    def get(self, domain):
        """按域名获取凭证明文：优先 token（标量），其次 cookie（netscape 格式）。"""
        v = self._vault
        # 1) 标量凭证（token/password/apikey）
        t = v.get_token(domain=domain)
        if t:
            return t
        # 2) cookie 凭证（非标量，需从解密后的 cookies 列表还原为头/Netscape 字符串）
        rec = v.get_by_domain(domain, kind='cookie')
        if not rec:
            return None
        fmt = (rec.get('format') or 'netscape').lower()
        cookies = rec.get('cookies') or []
        # 如果 cookies 列表为空但 secret 解密后是原始文本（netscape 格式直接存储），
        # 则从 _raw_secret 取明文
        if not cookies and '_raw' in rec:
            raw = rec['_raw']
            if isinstance(raw, bytes):
                raw = raw.decode('utf-8', errors='replace')
            # 原始文本就是 netscape 格式，直接返回
            if raw.strip():
                return raw
        if fmt == 'header':
            return '; '.join(f"{c.get('name','')}={c.get('value','')}" for c in cookies)
        # netscape / json → Netscape 格式文本（run.py 的 read_cookie_file 可处理）
        lines = []
        for c in cookies:
            name = c.get('name', '')
            value = c.get('value', '')
            if name and value:
                lines.append(f'{c.get("domain","")}\tTRUE\t/\t{c.get("path","/")}\t'
                             f'{c.get("secure", "FALSE")}\t0\t{name}\t{value}')
        return '\n'.join(lines)

    def set(self, domain, token):
        return self._vault.set_token(domain=domain, token=token)


class _TasksProxy:
    """统一任务表代理。插件以 kind='<plugin_id>' 注册自身任务。"""

    def __init__(self, plugin_id):
        self._kind = plugin_id
        try:
            _ut_init(data_dir_for())
        except Exception:
            pass

    def create(self, title, owner_id, status='pending',
               created_at=None, updated_at=None):
        return create_task('ext:' + self._kind + ':' + str(id(title)),
                           self._kind, title, owner_id=owner_id,
                           status=status, created_at=created_at,
                           updated_at=updated_at)

    def update(self, task_id, **kwargs):
        return update_task(task_id, **kwargs)

    def delete(self, task_id):
        return delete_task(task_id, is_admin=True)

    def get(self, task_id):
        return get_task(task_id)

    def list(self, role='admin', limit=200):
        return get_tasks(role=role, limit=limit)


class _HttpProxy:
    """外部 HTTP 客户端（带鉴权）。后续可接入 framework token 注入。"""

    def get(self, url, headers=None, **kw):
        import urllib.request
        req = urllib.request.Request(url, headers=headers or {})
        return urllib.request.urlopen(req, timeout=kw.get('timeout', 10)).read()

    def post(self, url, **kw):
        import urllib.request
        import json as _json
        data = _json.dumps(kw.get('json', {})).encode('utf-8')
        req = urllib.request.Request(url, data=data,
                                     headers={'Content-Type': 'application/json'})
        return urllib.request.urlopen(req, timeout=kw.get('timeout', 10)).read()


class Host:
    """注入插件的宿主对象。字段均为稳定契约，内部实现可自由演进。

    标识约定：key == 文件夹名（filesystem 唯一），作为数据库目录 / 缓存目录 /
    URL 前缀的命名空间。plugin_id 保留为兼容别名（恒等于 key）。
    """

    def __init__(self, manifest, app):
        # key 强制为文件夹名；manifest.id 已被 loader 强制为文件夹名，这里再显式取
        # 文件夹字段，确保即使 manifest 异常也不会偏离 filesystem 唯一标识。
        self.key = manifest.get('_folder') or manifest.get('id')
        self.plugin_id = self.key  # 向后兼容：旧插件仍可用 host.plugin_id
        self.manifest = manifest
        self.config = manifest.get('backend', {}) or {}
        self.url_prefix = self.config.get('url_prefix') or ('/api/ext/' + self.key)
        # 插件私有数据目录：<data_dir>/plugins/<key>
        root = os.environ.get('DBOX_DATA_DIR')
        if not root:
            pkg_dir = os.path.dirname(os.path.abspath(__file__))
            root = os.path.join(os.path.dirname(os.path.dirname(pkg_dir)), 'data')
        self.data_dir = os.path.join(root, 'plugins', self.key)
        os.makedirs(self.data_dir, exist_ok=True)
        # 插件进程级状态容器（框架不干预内容）
        self.app_state = {}
        self.logger = logging.getLogger('plugin.' + self.key)
        self.vault = _VaultProxy()
        self.tasks = _TasksProxy(self.key)
        self.http = _HttpProxy()
        self._app = app
        # 集中登记到资源注册表，供框架统一翻译真实地址（db / cache / url）。
        _reg_register_extension(self.key, self.key, self.data_dir)

    # ---- 鉴权装饰器（框架处理 JWT，插件不碰 token）----
    def _decode_token(self, token):
        """验证 JWT 返回 payload；失败返回 None。供 login_required / SSE 鉴权复用。"""
        if not token:
            return None
        payload = None
        for secret in _JWT_SECRETS:
            try:
                payload = jwt.decode(token, secret)
                break
            except Exception:
                continue
        if payload is None:
            return None
        if payload.get('type') != 'access':
            return None
        return payload

    def login_required(self, f):
        @wraps(f)
        def decorated(*args, **kwargs):
            _auth = request.headers.get('Authorization', '')
            token = _auth[7:] if _auth.startswith('Bearer ') else _auth
            payload = self._decode_token(token)
            if payload is None:
                return jsonify({'success': False, 'message': '未授权', 'code': 401}), 401
            g.user_id = payload.get('user_id')
            g.role = payload.get('role', 3)  # 未登录默认 GUEST(3)，数值越大权限越低
            g.username = payload.get('username')
            return f(*args, **kwargs)
        return decorated

    def auth_user(self, token):
        """校验 JWT，返回 (user_id, role, username)；失败返回 None。

        供插件在无法携带 Authorization header 的场景下（如 EventSource
        只能把 token 放在 query 参数里）做等价鉴权。插件不直接接触 jwt 密钥。
        """
        payload = self._decode_token(token)
        if payload is None:
            return None
        return (payload.get('user_id'), payload.get('role', 3), payload.get('username'))

    def admin_required(self, f):
        @wraps(f)
        def decorated(*args, **kwargs):
            _auth = request.headers.get('Authorization', '')
            token = _auth[7:] if _auth.startswith('Bearer ') else _auth
            if not token:
                return jsonify({'success': False, 'message': '未授权', 'code': 401}), 401
            payload = None
            last_err = None
            for secret in _JWT_SECRETS:
                try:
                    payload = jwt.decode(token, secret)
                    break
                except Exception as e:
                    last_err = e
            if payload is None:
                return jsonify({'success': False, 'message': f'无效的 token: {last_err}', 'code': 401}), 401
            if payload.get('type') != 'access':
                return jsonify({'success': False, 'message': 'token 类型错误', 'code': 401}), 401
            g.user_id = payload.get('user_id')
            g.role = payload.get('role', 3)  # 未登录默认 GUEST(3)，数值越大权限越低
            g.username = payload.get('username')
            if g.role > ADMIN_ROLE:
                return jsonify({'success': False, 'message': '需要管理员权限', 'code': 403}), 403
            return f(*args, **kwargs)
        return decorated

    # ---- 资源命名空间（数据库 / 缓存 / URL，均由框架统一翻译真实地址）----
    def db(self, name='main'):
        """返回该拓展下名为 name 的数据库文件真实路径（按需建目录）。

        允许多数据库：同一 key 下用不同 name 区分（如 host.db('chat') /
        host.db('stats')）。返回的是路径，插件自行打开 sqlite 等。
        """
        return _reg_db_path(self.key, name)

    def cache(self, name='main'):
        """返回该拓展下名为 name 的缓存目录真实路径（按需建目录）。

        允许多缓存：host.cache('thumb') / host.cache('tmp') 互不干扰。
        """
        return _reg_cache_path(self.key, name)

    def resolve(self, kind, name='main'):
        """真实地址翻译：kind ∈ {db, cache, url}。

        - db   -> 数据库文件路径
        - cache-> 缓存目录路径
        - url  -> 该 key 已注册的 URL 前缀（name 为索引或 'main'）
        集中走 registry，便于治理与排查。
        """
        return _reg_resolve(self.key, kind, name)

    def register_url(self, prefix):
        """登记一个额外的 URL 前缀（多 URL 能力）。

        插件可在 create_blueprint 中通过 host.register_blueprint(bp) 挂载
        多个 blueprint，每个使用不同前缀（均建议位于 /api/ext/<key>/ 下，
        以便主服务网关统一代理），并调用本方法登记以便框架感知。
        """
        _reg_register_url(self.key, prefix)

    def register_blueprint(self, bp):
        """由插件动态挂载额外的 Flask blueprint（支持多 URL）。

        传入的 blueprint 应自带 url_prefix（如 /api/ext/<key>/extra）；
        挂载后框架自动登记该前缀。返回 bp 以便链式调用。
        """
        if bp is not None and getattr(bp, 'url_prefix', None):
            self.register_url(bp.url_prefix)
        self._app.register_blueprint(bp)
        return bp

    # ---- 资源入库（把插件下载的文件纳入资源/图集库）----
    def ingest(self, library_id, path, kind=None, modes=('video', 'image'),
               hidden=False, meta=None, owner_id=None):
        """将磁盘上的文件登记进指定资源库。

        直接复用框架内部的 ingest_file，避免插件自行处理鉴权与入库细节。
        返回 ingest_file 的结果（资源记录或错误信息）。
        """
        try:
            from platform_client import ingest_file
            return ingest_file(
                library_id, path, kind=kind, modes=modes,
                hidden=hidden, meta=meta, user_id=owner_id,
            )
        except Exception as e:
            self.logger.error('ingest 失败: %s', e)
            return {'success': False, 'message': str(e)}

    def upsert_post_by_group(self, group_key, title=None, content='',
                             resource_index_ids=None, user_id=None,
                             display_modes=None, author_name=None,
                             author_url=None, source_url=None, library_id=None):
        """按 group_key 创建/更新帖子（X 下载器：把同一条推文的多文件聚合成一条帖子）。

        X 下载器把图片/视频聚合为一条帖子时调用，通过框架内部接口生成帖子。
        """
        try:
            from platform_client import upsert_post_by_group
            return upsert_post_by_group(
                group_key, title=title, content=content,
                resource_index_ids=resource_index_ids, user_id=user_id,
                display_modes=display_modes, author_name=author_name,
                author_url=author_url, source_url=source_url,
                library_id=library_id,
            )
        except Exception as e:
            self.logger.error('upsert_post_by_group 失败: %s', e)
            return {'success': False, 'message': str(e)}


def build_host(manifest, app):
    return Host(manifest, app)
