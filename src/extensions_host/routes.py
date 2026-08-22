"""外部脚本接口 API（Blueprint）。

本模块运行于独立的拓展宿主进程（extensions_host），承载「拓展管理」的全部对外
接口：脚本执行引擎、脚本管理、UI 扩展面板、AI 助手对话、凭证保险库。与主 Web
服务（8080）完全解耦——本模块不直接 import 任何 src/web 业务代码，仅通过
platform_client 以 HTTP 调用主服务暴露的内部契约接口完成业务副作用。

- 脚本管理类接口（增删改、启用/禁用、参数默认值、执行、ui-proxy 等）仅管理员可访问
  （admin_required，与 main.py 一致的 JWT 角色校验）。
- 面向全体登录用户的 UI 注入类接口（扩展悬浮面板列表 / 面板内容、AI 助手对话等）仅要求
  已登录（login_required），普通用户也应能使用 AI 助手悬浮球，不应被管理员权限拦截。
- notify / input 由脚本进程回调，使用任务作用域一次性令牌鉴权，不要求用户会话。
"""
from functools import wraps
from flask import Blueprint, request, jsonify, g, Response, stream_with_context

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
    AI 助手对话等）——这些功能普通用户也应可用，不应要求管理员权限。
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


@script_bp.route('/api/scripts', methods=['GET'])
@admin_required
def list_scripts():
    include = request.args.get('all') == '1'
    out = []
    for sc in mgr.scripts.values():
        if not include and not sc.get('enabled'):
            continue
        out.append(_public_script(sc, include))
    return jsonify({'success': True, 'scripts': out})


# ---------- 管理员：脚本/插件管理 ----------
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
    count = mgr.reload()
    return jsonify({'success': True, 'count': count})


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
                'standalone_route': ui.get('standalone_route'),
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
    # 面板由悬浮窗 iframe 加载、不走 vite HMR，浏览器可能缓存旧版本导致新功能不生效，
    # 故强制不缓存，保证每次打开都拉取最新 panel.html。
    return Response(content, mimetype='text/html; charset=utf-8',
                    headers={'Cache-Control': 'no-store'})


@script_bp.route('/api/ui-proxy', methods=['POST'])
@admin_required
def ui_proxy():
    """扩展 UI（iframe 内）调用外部服务的代理。可选注入管理员 token 到下游请求头。
    请求体：{ url, method?, headers?, body?, inject_token? }
    """
    import requests as _requests
    data = request.get_json(silent=True) or {}
    url = data.get('url')
    if not url:
        return jsonify({'success': False, 'message': 'url 必填'}), 400
    method = (data.get('method') or 'POST').upper()
    headers = dict(data.get('headers') or {})
    body = data.get('body')
    if data.get('inject_token'):
        headers['Authorization'] = request.headers.get('Authorization', '')
    try:
        resp = _requests.request(
            method, url, headers=headers,
            json=body if isinstance(body, (dict, list)) else None,
            data=body if isinstance(body, str) else None,
            timeout=30, verify=False,
        )
        # 透传下游响应（限制体积，避免超大响应）
        text = resp.text
        if len(text) > 5 * 1024 * 1024:
            text = text[:5 * 1024 * 1024]
        return Response(text, status=resp.status_code,
                        mimetype=resp.headers.get('Content-Type', 'application/json'))
    except Exception as e:
        return jsonify({'success': False, 'message': f'代理请求失败: {e}'}), 502


