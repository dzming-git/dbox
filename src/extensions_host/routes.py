"""外部脚本接口 API（Blueprint）。

本模块运行于独立的拓展宿主进程（extensions_host），承载「拓展管理」的全部对外
接口：脚本执行引擎、脚本管理、UI 扩展面板、CodeBuddy对话、凭证保险库。与主 Web
服务（8080）完全解耦——本模块不直接 import 任何 src/web 业务代码，仅通过
platform_client 以 HTTP 调用主服务暴露的内部契约接口完成业务副作用。

- 脚本管理类接口（增删改、启用/禁用、参数默认值、执行、ui-proxy 等）仅管理员可访问
  （admin_required，与 main.py 一致的 JWT 角色校验）。
- 面向全体登录用户的 UI 注入类接口（扩展悬浮面板列表 / 面板内容、CodeBuddy对话等）仅要求
  已登录（login_required），普通用户也应能使用 CodeBuddy悬浮球，不应被管理员权限拦截。
- notify / input 由脚本进程回调，使用任务作用域一次性令牌鉴权，不要求用户会话。
"""
from functools import wraps
from flask import Blueprint, request, jsonify, g, Response, stream_with_context, current_app

from authlib.jose import jwt

import os
import re
import sys
import json
import subprocess

# 与 backend.utils.jwt_authlib 完全一致：优先环境变量 DBOX_JWT_SECRET，回退内置默认密钥。
# 直接读取环境变量（而非依赖模块导入），避免在不同进程 / 导入顺序下拿到错误的密钥，
# 从而导致脚本接口 401 把用户踢出登录。
_DEFAULT_JWT_SECRET = 'dbox-jwt-secret-key-change-in-production-2024'

# 角色阈值：本地常量，避免直接 import 主服务的 core.models。
# 必须与 core.models.UserRole 的数值保持一致（数值越小权限越高）：
#   ROOT=0, ADMIN=1, USER=2, GUEST=3。
# 判定用 g.role <= ADMIN_ROLE（数值越小权限越高），故 ROOT(0) 与 ADMIN(1) 均视为管理员。
ADMIN_ROLE = 1  # 对应 UserRole.ADMIN（数值越小权限越高）


def _resolve_jwt_secrets():
    secrets = []
    env_secret = os.environ.get('DBOX_JWT_SECRET')
    if env_secret:
        secrets.append(env_secret)
    if _DEFAULT_JWT_SECRET not in secrets:
        secrets.append(_DEFAULT_JWT_SECRET)
    return secrets


_JWT_SECRETS = _resolve_jwt_secrets()

from manager import mgr, ScriptJobManager

script_bp = Blueprint('script', __name__)


def init_script_engine(app):
    """由 extensions_host 应用工厂在 app 创建后调用，初始化管理器。"""
    mgr.init(app)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        _auth = request.headers.get('Authorization', '')
        token = _auth[7:] if _auth.startswith('Bearer ') else _auth
        if not token:
            return jsonify({'success': False, 'message': '未授权', 'code': 401}), 401
        # 仅校验鉴权；处理函数本身的异常（如业务 500）必须如实抛出，
        # 绝不能被这里吞掉伪装成「无效的 token: 401」。
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
        # 优先从主服务 DB 查最新 role（避免 stale JWT role）
        uid = payload.get('user_id')
        _db_role = None
        if uid:
            try:
                import os, sqlite3 as _sqlite
                _data_dir = os.environ.get('DBOX_DATA_DIR')
                if not _data_dir:
                    _pkg_dir = os.path.dirname(os.path.abspath(__file__))
                    _project_root = os.path.dirname(os.path.dirname(_pkg_dir))
                    _data_dir = os.path.join(_project_root, 'data')
                _main_db = os.path.join(_data_dir, 'databases', 'dbox.db')
                if os.path.exists(_main_db):
                    _conn = _sqlite.connect(_main_db)
                    _row = _conn.execute('SELECT role FROM users WHERE id=?', (uid,)).fetchone()
                    if _row is not None:
                        _db_role = int(_row[0])
                    _conn.close()
            except Exception:
                pass
        g.role = _db_role if _db_role is not None else payload.get('role', 3)
        g.username = payload.get('username')
        if g.role > ADMIN_ROLE:
            return jsonify({'success': False, 'message': '需要管理员权限', 'code': 403}), 403
        return f(*args, **kwargs)
    return decorated


def login_required(f):
    """仅校验 JWT 有效（用户已登录）即可访问，不限制角色。

    用于面向全体登录用户的 UI 注入类接口（扩展悬浮面板列表/面板内容、
    CodeBuddy对话等）——这些功能普通用户也应可用，不应要求管理员权限。
    管理员专属的脚本管理/代理能力仍使用 admin_required。
    """
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
        uid = payload.get('user_id')
        _db_role = None
        if uid:
            try:
                import os, sqlite3 as _sqlite
                _data_dir = os.environ.get('DBOX_DATA_DIR')
                if not _data_dir:
                    _pkg_dir = os.path.dirname(os.path.abspath(__file__))
                    _project_root = os.path.dirname(os.path.dirname(_pkg_dir))
                    _data_dir = os.path.join(_project_root, 'data')
                _main_db = os.path.join(_data_dir, 'databases', 'dbox.db')
                if os.path.exists(_main_db):
                    _conn = _sqlite.connect(_main_db)
                    _row = _conn.execute('SELECT role FROM users WHERE id=?', (uid,)).fetchone()
                    if _row is not None:
                        _db_role = int(_row[0])
                    _conn.close()
            except Exception:
                pass
        g.role = _db_role if _db_role is not None else payload.get('role', 3)
        g.username = payload.get('username')
        return f(*args, **kwargs)
    return decorated


def _public_script(sc, include_disabled=False):
    out = {
        'id': sc.get('id'),
        'name': sc.get('name'),
        'description': sc.get('description'),
        'runtime': sc.get('runtime'),
        'command': sc.get('command'),
        'interface': sc.get('interface'),
        'timeout': sc.get('timeout', 0),
        'enabled': bool(sc.get('enabled')),
        'params': sc.get('params', []),
        'required_cookies': sc.get('required_cookies', []),
        'ui': sc.get('ui'),
    }
    if include_disabled and sc.get('_error'):
        out['error'] = sc['_error']
    return out


# ---------- 管理员：插件管理 ----------
@script_bp.route('/api/admin/scripts', methods=['GET'])
@admin_required
def admin_list():
    return jsonify({'success': True, 'scripts': [_public_script(s, True) for s in mgr.scripts.values()]})


@script_bp.route('/api/admin/scripts/<script_id>/enable', methods=['POST'])
@admin_required
def enable_script(script_id):
    if not mgr.set_enabled(script_id, True):
        return jsonify({'success': False, 'message': '脚本不存在'}), 404
    return jsonify({'success': True})


@script_bp.route('/api/admin/scripts/<script_id>/disable', methods=['POST'])
@admin_required
def disable_script(script_id):
    if not mgr.set_enabled(script_id, False):
        return jsonify({'success': False, 'message': '脚本不存在'}), 404
    return jsonify({'success': True})


@script_bp.route('/api/admin/scripts/<script_id>/settings', methods=['GET'])
@admin_required
def get_script_settings(script_id):
    """读取插件独立设置（按 manifest.settings schema 回退默认值）。"""
    sc = mgr.scripts.get(script_id)
    if not sc:
        return jsonify({'success': False, 'message': '脚本不存在'}), 404
    schema = sc.get('settings', [])
    values = mgr.get_settings(script_id)
    return jsonify({
        'success': True,
        'script_id': script_id,
        'schema': schema,
        'values': values,
    })


@script_bp.route('/api/admin/scripts/<script_id>/settings', methods=['PUT'])
@admin_required
def update_script_settings(script_id):
    """保存插件独立设置（框架按 manifest.settings 过滤非法 key）。"""
    body = request.get_json(silent=True) or {}
    values = body.get('values')
    if not isinstance(values, dict):
        return jsonify({'success': False, 'message': 'values 必须是对象'}), 400
    if not mgr.set_settings(script_id, values):
        return jsonify({'success': False, 'message': '脚本不存在或保存失败'}), 404
    return jsonify({'success': True, 'values': mgr.get_settings(script_id)})


@script_bp.route('/api/admin/scripts/reload', methods=['POST'])
@admin_required
def reload_scripts():
    """重新扫描并真正重载插件 Blueprint（不仅刷新 manifest 字典）。

    采用「整进程重启」方式：经 nssm restart 整个 extensions 宿主进程，走经过验证的
    初始 load_all 路径，保证重载后蓝图状态干净（规避进程内手工 unregister 在
    Flask/Werkzeug 下残留路由索引的 KeyError 500，以及单插件错误污染全局 url_map）。
    单插件错误由启动期的 load_all_plugins 隔离（每个插件独立 try/except），不影响其他。
    """
    import subprocess, shutil, os as _os, sys as _sys
    try:
        svc = _os.environ.get('EXTENSIONS_HOST_SERVICE', 'dbox-extensions')
        nssm_bin = r'C:\Tools\nssm.exe'
        if not _os.path.isfile(nssm_bin):
            nssm_bin = shutil.which('nssm') or 'nssm'
        cmd = '"%s" restart %s' % (nssm_bin, svc)
        subprocess.Popen(cmd, shell=True,
                         creationflags=0x00000200,  # DETACHED_PROCESS
                         close_fds=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({'success': True, 'reloaded': 'restarting',
                        'message': '已请求重启 extensions 进程以加载新代码'})
    except Exception as e:
        _sys.stderr.write('[RELOAD] 重启请求失败: %s\n' % e)
        _sys.stderr.flush()
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------- 扩展 UI 注入 ----------
# 仅当脚本被管理员启用且 manifest 声明了 ui 段时，前端才会挂载其界面元素。
# 因此扩展 UI 天然只对管理员可见（与「只有管理员有权限」的要求一致）。
# 路由使用独立命名空间 /api/ui-*，避免与 /api/scripts/<script_id>/* 动态路由冲突。
@script_bp.route('/api/ui-extensions', methods=['GET'])
@login_required
def list_extensions():
    """返回当前已启用且声明了 ui 的脚本 UI 元信息，供前端全局挂载悬浮面板/标签页。

    注意：ui 段原样透传（不做字段白名单裁剪），以便插件通过 manifest 声明任意
    自定义能力字段（如 standalone_route、busy_poll），前端按字段动态渲染，框架
    不硬编码任何插件行为（零入侵原则）。
    """
    out = []
    for sc in mgr.scripts.values():
        if not sc.get('enabled'):
            continue
        ui = sc.get('ui')
        if not ui or not isinstance(ui, dict):
            continue
        # 全屏独立 URL：若插件在 manifest 显式声明了 standalone_route 则原样透传；
        # 否则只要有 ui.entry（即存在可独立渲染的面板），框架自动推导一个默认路由
        # /ext/<id>，使「全屏独立页」成为所有插件的默认能力，无需逐插件 opt-in。
        standalone_route = ui.get('standalone_route')
        if not standalone_route and ui.get('entry'):
            standalone_route = '/ext/%s' % sc.get('id')
        out.append({
            'id': sc.get('id'),
            'name': sc.get('name'),
            'ui': {
                'mount': ui.get('mount', 'floating'),
                'title': ui.get('title', sc.get('name', sc.get('id'))),
                'icon': ui.get('icon', '🔧'),
                'entry': ui.get('entry'),
                'needs_credential': bool(ui.get('needs_credential', False)),
                'sandbox': ui.get('sandbox', 'allow-scripts allow-same-origin allow-forms allow-popups'),
                # 透传插件声明的自定义能力字段（框架不感知其含义，纯数据下发）
                'standalone_route': standalone_route,
                'busy_poll': ui.get('busy_poll'),
            },
        })
    return jsonify({'success': True, 'extensions': out})


@script_bp.route('/api/ui-panel/<script_id>', methods=['GET'])
@login_required
def get_panel(script_id):
    """返回扩展脚本 UI 入口文件内容（位于脚本目录 ui/<entry>）。前端用 iframe 加载。"""
    sc = mgr.scripts.get(script_id)
    if not sc:
        return jsonify({'success': False, 'message': '脚本不存在'}), 404
    ui = sc.get('ui') or {}
    entry = ui.get('entry')
    if not entry:
        return jsonify({'success': False, 'message': '该脚本未声明 ui.entry'}), 404
    # 防目录穿越：仅允许 ui/ 子目录下的相对路径
    base_dir = sc.get('_dir') or os.path.dirname(sc.get('manifest_path', ''))
    target = os.path.normpath(os.path.join(base_dir, 'ui', entry))
    ui_dir = os.path.normpath(os.path.join(base_dir, 'ui'))
    if not target.startswith(ui_dir + os.sep) and target != ui_dir:
        return jsonify({'success': False, 'message': '非法路径'}), 400
    if not os.path.isfile(target):
        return jsonify({'success': False, 'message': 'UI 入口文件不存在'}), 404
    with open(target, 'r', encoding='utf-8') as f:
        content = f.read()
    # 框架提供的「真实地址翻译」：把与 key 相关的占位符替换为运行期真实值，
    # 使面板不再写死插件 id / 前缀（零入侵、可复用于任意拓展）。
    #   __EXT_KEY__          -> 拓展 key（=文件夹名）
    #   __EXT_API_PREFIX__   -> 后端 API 前缀（/api/ext/<key>/，含结尾斜杠）
    api_prefix = (sc.get('backend') or {}).get('url_prefix') or ('/api/ext/%s' % script_id)
    if not api_prefix.endswith('/'):
        api_prefix += '/'
    content = content.replace('__EXT_KEY__', script_id).replace(
        '__EXT_API_PREFIX__', api_prefix)
    # 面板由悬浮窗 iframe 加载、不走 vite HMR，浏览器可能缓存旧版本导致新功能不生效，
    # 故强制不缓存，保证每次打开都拉取最新 panel.html。
    return Response(content, mimetype='text/html; charset=utf-8',
                    headers={'Cache-Control': 'no-store'})


# ---------- 管理员：凭证保险库（cookie / token / password / apikey 统一管理）----------
# 独立于脚本引擎的通用能力：任何子系统（插件、下载器、CLI 免登录调用等）都通过
# 同一份加密落盘的凭证库读写凭证。仅管理员可读写；列表只回传元信息，不回传明文密文。


def _vault_public(rec):
    """凭证元信息（脱敏）：绝不下发明文 value/cookies 或 secret 密文。"""
    return {
        'id': rec.get('id'),
        'kind': rec.get('kind'),
        'name': rec.get('name'),
        'domain': rec.get('domain'),
        'format': rec.get('format'),
        'note': rec.get('note'),
        'created_at': rec.get('created_at'),
        'updated_at': rec.get('updated_at'),
        # 是否已存有凭证明文（供前端展示「已配置/未配置」状态，不泄露内容）
        'has_value': bool(rec.get('value') or rec.get('cookies')),
    }


def _parse_cookie_value(raw):
    """把用户粘贴的 cookie 文本解析为 list[dict]。

    支持两种输入：
    1. header 字符串：'auth_token=xxx; ct0=yyy; k=1; v=2' 或 'k=1; v=2'
    2. 已是 list[dict]（直接透传）
    """
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, str):
        return []
    cookies = []
    # 按分号切分，兼容 '; ' 与 ';'
    for part in raw.split(';'):
        part = part.strip()
        if not part:
            continue
        if '=' not in part:
            continue
        k, _, v = part.partition('=')
        cookies.append({'name': k.strip(), 'value': v.strip()})
    return cookies


def _vault_or_404():
    if not getattr(mgr, 'vault', None):
        return None
    return mgr.vault


@script_bp.route('/api/admin/cookies', methods=['GET'])
@admin_required
def vault_list():
    vault = _vault_or_404()
    if vault is None:
        return jsonify({'success': False, 'message': '凭证保险库未初始化'}), 500
    return jsonify({'success': True, 'cookies': [_vault_public(r) for r in vault.list_all()]})


@script_bp.route('/api/admin/cookies', methods=['POST'])
@admin_required
def vault_create():
    vault = _vault_or_404()
    if vault is None:
        return jsonify({'success': False, 'message': '凭证保险库未初始化'}), 500
    data = request.get_json(silent=True) or {}
    kind = data.get('kind') or 'cookie'
    name = (data.get('name') or '').strip()
    domain = (data.get('domain') or '').strip()
    if not domain:
        return jsonify({'success': False, 'message': 'domain 不能为空'}), 400
    if kind in ('token', 'password', 'apikey'):
        value = data.get('value')
        if not isinstance(value, str) or not value:
            return jsonify({'success': False, 'message': '标量凭证需提供非空 value'}), 400
    else:
        raw = data.get('cookies') if data.get('cookies') is not None else data.get('value')
        value = _parse_cookie_value(raw)
        if not value:
            return jsonify({'success': False, 'message': 'cookie 凭证需提供有效的 cookies 文本'}), 400
    pid = vault.add(kind, name, domain, value,
                    note=data.get('note') or '', fmt=data.get('format') or 'netscape')
    return jsonify({'success': True, 'id': pid})


@script_bp.route('/api/admin/cookies/<cid>', methods=['GET'])
@admin_required
def vault_detail(cid):
    """凭证详情（含明文，供编辑弹窗预填）。

    列表接口刻意脱敏（不下发明文），但编辑时需要把现有内容回填到表单，
    否则用户看到空框重新粘贴极易漏粘/粘错，导致存储残缺（已发生过的真实 case）。
    明文仅在管理员会话内返回，不落日志、不进列表响应。
    """
    vault = _vault_or_404()
    if vault is None:
        return jsonify({'success': False, 'message': '凭证保险库未初始化'}), 500
    rec = vault.get(cid)
    if not rec:
        return jsonify({'success': False, 'message': '凭证不存在'}), 404
    out = _vault_public(rec)
    # 明文仅在此详情接口返回
    if rec.get('kind') in ('token', 'password', 'apikey'):
        out['value'] = rec.get('value', '')
    else:
        cookies = rec.get('cookies') or []
        out['cookies_header'] = '; '.join(
            f"{c.get('name')}={c.get('value')}" for c in cookies if c.get('name'))
    return jsonify({'success': True, 'cookie': out})


@script_bp.route('/api/admin/cookies/<cid>', methods=['PUT'])
@admin_required
def vault_update(cid):
    vault = _vault_or_404()
    if vault is None:
        return jsonify({'success': False, 'message': '凭证保险库未初始化'}), 500
    existing = vault.get(cid)
    if not existing:
        return jsonify({'success': False, 'message': '凭证不存在'}), 404
    data = request.get_json(silent=True) or {}
    kind = data.get('kind') or existing.get('kind') or 'cookie'
    name = (data.get('name') if data.get('name') is not None else existing.get('name')) or ''
    domain = (data.get('domain') if data.get('domain') is not None else existing.get('domain')) or ''
    fmt = data.get('format') or existing.get('format') or 'netscape'
    note = data.get('note') if data.get('note') is not None else existing.get('note', '')
    if kind in ('token', 'password', 'apikey'):
        value = data.get('value')
        if value is None:
            value = existing.get('value', '')
    else:
        raw = data.get('cookies') if data.get('cookies') is not None else data.get('value')
        if raw is None:
            value = existing.get('cookies', [])
        else:
            value = _parse_cookie_value(raw)
            if not value:
                return jsonify({'success': False, 'message': 'cookie 凭证需提供有效的 cookies 文本'}), 400
    # 覆盖写入：先删后加（add 的 pid 由 kind|domain|name 哈希决定，同 key 会得到同 pid）
    vault.delete(cid)
    new_pid = vault.add(kind, name, domain, value, note=note, fmt=fmt)
    return jsonify({'success': True, 'id': new_pid})


@script_bp.route('/api/admin/cookies/<cid>', methods=['DELETE'])
@admin_required
def vault_delete(cid):
    vault = _vault_or_404()
    if vault is None:
        return jsonify({'success': False, 'message': '凭证保险库未初始化'}), 500
    if not vault.delete(cid):
        return jsonify({'success': False, 'message': '凭证不存在'}), 404
    return jsonify({'success': True})


# ---------- 扩展 UI 代理已由插件 backend 蓝图替代，/api/ui-proxy 路由已移除 ----------


