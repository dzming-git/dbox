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

    def get(self, url, **kw):
        import urllib.request
        return urllib.request.urlopen(url, timeout=kw.get('timeout', 10)).read()

    def post(self, url, **kw):
        import urllib.request
        import json as _json
        data = _json.dumps(kw.get('json', {})).encode('utf-8')
        req = urllib.request.Request(url, data=data,
                                     headers={'Content-Type': 'application/json'})
        return urllib.request.urlopen(req, timeout=kw.get('timeout', 10)).read()


class Host:
    """注入插件的宿主对象。字段均为稳定契约，内部实现可自由演进。"""

    def __init__(self, manifest, app):
        self.plugin_id = manifest.get('id')
        self.manifest = manifest
        self.config = manifest.get('backend', {}) or {}
        self.url_prefix = self.config.get('url_prefix') or ('/api/ext/' + self.plugin_id)
        # 插件私有数据目录：<data_dir>/plugins/<plugin_id>
        root = os.environ.get('DBOX_DATA_DIR')
        if not root:
            pkg_dir = os.path.dirname(os.path.abspath(__file__))
            root = os.path.join(os.path.dirname(os.path.dirname(pkg_dir)), 'data')
        self.data_dir = os.path.join(root, 'plugins', self.plugin_id)
        os.makedirs(self.data_dir, exist_ok=True)
        # 插件进程级状态容器（框架不干预内容）
        self.app_state = {}
        self.logger = logging.getLogger('plugin.' + self.plugin_id)
        self.vault = _VaultProxy()
        self.tasks = _TasksProxy(self.plugin_id)
        self.http = _HttpProxy()
        self._app = app

    # ---- 鉴权装饰器（框架处理 JWT，插件不碰 token）----
    def login_required(self, f):
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
            return f(*args, **kwargs)
        return decorated

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
