"""外部脚本接口 API（Blueprint）。

- 除 notify 外，所有接口仅管理员可访问（与 main.py 的 admin_required 一致的 JWT 校验）。
- notify 由脚本进程回调，使用任务作用域一次性令牌鉴权，不要求用户会话。
"""
from functools import wraps
from flask import Blueprint, request, jsonify, g, Response

from authlib.jose import jwt
from core.models import UserRole

import os
import sys
import subprocess

# 与 backend.utils.jwt_authlib 完全一致：优先环境变量 DBOX_JWT_SECRET，回退内置默认密钥。
# 直接读取环境变量（而非依赖模块导入），避免在不同进程 / 导入顺序下拿到错误的密钥，
# 从而导致脚本接口 401 把用户踢出登录。
_DEFAULT_JWT_SECRET = 'dbox-jwt-secret-key-change-in-production-2024'


def _resolve_jwt_secrets():
    secrets = []
    env_secret = os.environ.get('DBOX_JWT_SECRET')
    if env_secret:
        secrets.append(env_secret)
    if _DEFAULT_JWT_SECRET not in secrets:
        secrets.append(_DEFAULT_JWT_SECRET)
    return secrets


_JWT_SECRETS = _resolve_jwt_secrets()

from .manager import mgr, ScriptJobManager

script_bp = Blueprint('script', __name__)


def init_script_engine(app):
    """由 main.py 在 app 创建后调用，初始化管理器。"""
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
        g.role = payload.get('role', 0)
        g.username = payload.get('username')
        if g.role < UserRole.ADMIN:
            return jsonify({'success': False, 'message': '需要管理员权限', 'code': 403}), 403
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


@script_bp.route('/api/scripts/<script_id>/run', methods=['POST'])
@admin_required
def run_script(script_id):
    data = request.get_json(silent=True) or {}
    params = data.get('params', {})
    job_id, err = mgr.run(script_id, params, g.user_id, request.url_root.rstrip('/'))
    if err:
        return jsonify({'success': False, 'message': err}), 400
    return jsonify({'success': True, 'job_id': job_id})


@script_bp.route('/api/scripts/jobs', methods=['GET'])
@admin_required
def list_jobs():
    return jsonify({'success': True, 'jobs': mgr.list_jobs()})


@script_bp.route('/api/scripts/jobs/<job_id>', methods=['GET'])
@admin_required
def get_job(job_id):
    job = mgr.get_job(job_id)
    if not job:
        return jsonify({'success': False, 'message': '任务不存在'}), 404
    return jsonify({'success': True, 'job': job})


@script_bp.route('/api/scripts/jobs/<job_id>/cancel', methods=['POST'])
@admin_required
def cancel_job(job_id):
    ok = mgr.cancel(job_id)
    return jsonify({'success': ok})


@script_bp.route('/api/scripts/<job_id>/notify', methods=['POST'])
def notify(job_id):
    """脚本回调：上报新资源入库。仅凭任务令牌鉴权。"""
    _auth = request.headers.get('Authorization', '')
    if _auth.startswith('Bearer '):
        token = _auth[7:].strip()
    else:
        token = request.args.get('token') or (request.get_json(silent=True) or {}).get('token')
    body = request.get_json(silent=True) or {}
    files = body.get('files', [])
    ok, msg = mgr.notify(job_id, token, files)
    if not ok:
        return jsonify({'success': False, 'message': msg}), 403
    return jsonify({'success': True, 'message': msg})


@script_bp.route('/api/scripts/jobs/<job_id>/input', methods=['GET'])
def get_input(job_id):
    """脚本长轮询用户输入，仅凭任务令牌鉴权。超时返回 204，由脚本重试。"""
    _auth = request.headers.get('Authorization', '')
    if _auth.startswith('Bearer '):
        token = _auth[7:].strip()
    else:
        token = request.args.get('token')
    value, err = mgr.get_input(job_id, token, timeout=30)
    if err == '任务不存在':
        return jsonify({'success': False, 'message': err}), 404
    if err == '令牌无效':
        return jsonify({'success': False, 'message': err}), 403
    if value is None:
        return jsonify({'success': True, 'value': None}), 204
    return jsonify({'success': True, 'value': value})


@script_bp.route('/api/scripts/jobs/<job_id>/respond', methods=['POST'])
@admin_required
def respond_job(job_id):
    """前端提交用户对脚本提问的答复。"""
    data = request.get_json(silent=True) or {}
    ok, msg = mgr.respond(job_id, data.get('value'))
    if not ok:
        return jsonify({'success': False, 'message': msg}), 400
    return jsonify({'success': True})


# ---------- 管理员：脚本管理 ----------
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
@admin_required
def list_extensions():
    """返回当前已启用且声明了 ui 的脚本 UI 元信息，供前端全局挂载悬浮面板/标签页。"""
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
            },
        })
    return jsonify({'success': True, 'extensions': out})


@script_bp.route('/api/ui-panel/<script_id>', methods=['GET'])
@admin_required
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
    return Response(content, mimetype='text/html; charset=utf-8')


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


# ---------- AI 助手对话（直接调用 CodeBuddy CLI，免 example 占位） ----------
# 复用与 feedback_ai 脚本一致的 CodeBuddy 接入方式：
#   - CLI 路径：环境变量 DBOX_BUDDYCN 或 %APPDATA%\npm\codebuddy.cmd
#   - 鉴权：从通用凭证保险库读取 codebuddy 域 token，注入 ANTHROPIC_API_KEY
#   - 调用：codebuddy -p -y --add-dir <项目根> --input-format text <prompt>
_ANTHROPIC_API_KEY_ENV = 'ANTHROPIC_API_KEY'
_CODEBUDDY_TOKEN_DOMAIN = 'codebuddy'


def _load_codebuddy_token() -> str:
    """从通用凭证保险库读取 codebuddy token（与 feedback_ai 一致）。"""
    env_token = os.environ.get(_ANTHROPIC_API_KEY_ENV)
    if env_token:
        return env_token.strip()
    try:
        sys_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..', 'common')
        if sys_path not in sys.path:
            sys.path.insert(0, sys_path)
        from credential_vault import CredentialVault, data_dir_for  # type: ignore
        vault = CredentialVault(data_dir_for())
        tok = vault.get_token(domain=_CODEBUDDY_TOKEN_DOMAIN)
        if tok:
            return tok.strip()
        for rec in vault.list_all():
            if rec.get('kind') == 'token' and 'codebuddy' in (rec.get('name') or '').lower():
                return (rec.get('value') or '').strip()
    except Exception:
        pass
    return ''


def _project_root() -> str:
    pkg_dir = os.path.dirname(os.path.abspath(__file__))         # src/web/script_engine
    return os.path.dirname(os.path.dirname(os.path.dirname(pkg_dir)))


def _is_auth_error(text: str) -> bool:
    t = (text or '').lower()
    return any(k in t for k in ('未登录', '认证失败', 'auth fail', 'unauthorized',
                                'invalid api key', 'login required', 'please login'))


@script_bp.route('/api/ai-chat', methods=['POST'])
@admin_required
def ai_chat():
    """AI 助手对话：后端调用 CodeBuddy CLI 返回纯文本，浏览器面板经此接口对话。

    请求体：{ message: str, history?: [{role,content}] }
    """
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'success': False, 'message': 'message 必填'}), 400

    buddy = os.environ.get('DBOX_BUDDYCN') or (
        os.path.expandvars(r'%APPDATA%\npm\codebuddy.cmd'))
    if not os.path.isfile(buddy):
        return jsonify({'success': False, 'message': '未找到 CodeBuddy CLI，请确认已安装'}), 502

    # 拼装 prompt：带简短系统约束，要求直接回答用户问题
    prompt = (
        '你是一个嵌入在媒体库管理后台里的 AI 助手，请用简体中文简洁回答用户问题。\n'
        '只输出回答内容本身，不要输出多余的解释或代码块标记。\n\n'
        '用户问题：' + message
    )

    env = dict(os.environ)
    token = _load_codebuddy_token()
    if token:
        env[_ANTHROPIC_API_KEY_ENV] = token

    try:
        proc = subprocess.run(
            [buddy, '-p', '-y', '--add-dir', _project_root(),
             '--input-format', 'text', prompt],
            input=prompt.encode('utf-8'),
            cwd=_project_root(),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=120,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'message': 'AI 响应超时，请稍后重试'}), 504

    raw = (proc.stdout or b'') + (proc.stderr or b'')
    text = None
    for enc in ('utf-8', 'gbk', 'utf-8-sig'):
        try:
            text = raw.decode(enc)
            break
        except Exception:
            text = raw.decode('utf-8', errors='replace')
    err_text = (proc.stderr or b'').decode('utf-8', errors='replace')
    if _is_auth_error(err_text):
        return jsonify({
            'success': False,
            'message': 'CodeBuddy 认证失败，请在凭证保险库配置 codebuddy token 或执行 codebuddy /login',
        }), 401
    return jsonify({'success': True, 'reply': (text or '').strip()})


# ---------- 管理员：脚本参数用户默认值 ----------
@script_bp.route('/api/admin/scripts/<script_id>/defaults', methods=['GET'])
@admin_required
def get_script_defaults(script_id):
    """读取当前管理员对该脚本参数的个人默认值。"""
    if script_id not in mgr.scripts:
        return jsonify({'success': False, 'message': '脚本不存在'}), 404
    defaults = mgr.get_param_defaults(script_id, g.user_id)
    return jsonify({'success': True, 'defaults': defaults})


@script_bp.route('/api/admin/scripts/<script_id>/defaults', methods=['PUT'])
@admin_required
def put_script_defaults(script_id):
    """保存当前管理员对该脚本参数的个人默认值。"""
    if script_id not in mgr.scripts:
        return jsonify({'success': False, 'message': '脚本不存在'}), 404
    data = request.get_json(silent=True) or {}
    defaults = data.get('defaults', {})
    if not isinstance(defaults, dict):
        return jsonify({'success': False, 'message': 'defaults 必须为对象'}), 400
    ok = mgr.save_param_defaults(script_id, g.user_id, defaults)
    if not ok:
        return jsonify({'success': False, 'message': '保存失败'}), 500
    return jsonify({'success': True})


# ---------- 管理员：通用凭证保险库 ----------
# 支持 cookie / token / password / apikey 多种类型，仅管理员可读写；落盘加密，
# 列表不回传 value。复用现有 /api/admin/cookies 路径，避免前端大改。
from common.credential_vault import CREDENTIAL_KINDS, KIND_COOKIE


def _sanitize_cred(rec):
    """把保险库记录裁剪成列表输出（剔除明文 value）。"""
    out = {k: rec.get(k) for k in ('id', 'kind', 'name', 'domain', 'format', 'note', 'updated_at')}
    return out


@script_bp.route('/api/admin/cookies', methods=['GET'])
@admin_required
def list_cookies():
    if not mgr.vault:
        return jsonify({'success': True, 'cookies': []})
    items = [_sanitize_cred(r) for r in mgr.vault.list_all()]
    return jsonify({'success': True, 'cookies': items})


@script_bp.route('/api/admin/cookies', methods=['POST'])
@admin_required
def create_cookie():
    if not mgr.vault:
        return jsonify({'success': False, 'message': 'vault 未初始化'}), 500
    data = request.get_json(silent=True) or {}
    kind = data.get('kind', KIND_COOKIE)
    name = data.get('name')
    domain = data.get('domain')
    value = data.get('value')
    note = data.get('note', '')
    if kind not in CREDENTIAL_KINDS:
        return jsonify({'success': False, 'message': f'不支持的凭证类型: {kind}'}), 400
    if not name or not domain or not value:
        return jsonify({'success': False, 'message': 'name / domain / value 必填'}), 400
    fmt = data.get('format') if kind == KIND_COOKIE else 'raw'
    if kind == KIND_COOKIE and fmt not in ('netscape', 'header', 'json'):
        return jsonify({'success': False, 'message': 'format 必须为 netscape / header / json'}), 400
    pid = mgr.vault.add(kind, name, domain, value, note=note, fmt=fmt)
    return jsonify({'success': True, 'id': pid})


@script_bp.route('/api/admin/cookies/<cid>', methods=['PUT'])
@admin_required
def update_cookie(cid):
    if not mgr.vault:
        return jsonify({'success': False, 'message': 'vault 未初始化'}), 500
    old = mgr.vault.get(cid)
    if not old:
        return jsonify({'success': False, 'message': '凭证配置不存在'}), 404
    data = request.get_json(silent=True) or {}
    kind = data.get('kind', old.get('kind', KIND_COOKIE))
    name = data.get('name', old.get('name'))
    domain = data.get('domain', old.get('domain'))
    value = data.get('value', old.get('value'))
    note = data.get('note', old.get('note', ''))
    if kind not in CREDENTIAL_KINDS:
        return jsonify({'success': False, 'message': f'不支持的凭证类型: {kind}'}), 400
    fmt = data.get('format') if (data.get('format') or kind == KIND_COOKIE) else old.get('format', 'raw')
    # 新 CredentialVault 无独立 update：删旧 + 按稳定 pid 覆盖（pid 由 kind|domain|name 派生）。
    # 若 key 未变则等于原地覆盖；若变了则旧记录被清、新记录生成，无孤儿。
    mgr.vault.delete(cid)
    pid = mgr.vault.add(kind, name, domain, value, note=note, fmt=fmt)
    return jsonify({'success': True, 'id': pid})


@script_bp.route('/api/admin/cookies/<cid>', methods=['DELETE'])
@admin_required
def delete_cookie(cid):
    if not mgr.vault:
        return jsonify({'success': False, 'message': 'vault 未初始化'}), 500
    # delete 返回 bool；兼容新旧签名（旧返回 dict，新返回 bool）
    res = mgr.vault.delete(cid)
    ok = res if isinstance(res, bool) else bool(res)
    if not ok:
        return jsonify({'success': False, 'message': '凭证配置不存在'}), 404
    return jsonify({'success': True})
