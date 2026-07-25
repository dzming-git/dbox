"""外部脚本接口 API（Blueprint）。

- 除 notify 外，所有接口仅管理员可访问（与 main.py 的 admin_required 一致的 JWT 校验）。
- notify 由脚本进程回调，使用任务作用域一次性令牌鉴权，不要求用户会话。
"""
from functools import wraps
from flask import Blueprint, request, jsonify, g

from authlib.jose import jwt
from core.models import UserRole

from .manager import mgr, ScriptJobManager

# 必须与 main.py 中 admin_required 使用的密钥保持一致
_JWT_SECRET = 'dplayer-jwt-secret-key-change-in-production-2024'

script_bp = Blueprint('script', __name__)


def init_script_engine(app):
    """由 main.py 在 app 创建后调用，初始化管理器。"""
    mgr.init(app)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '')
        if token.startswith('Bearer '):
            token = token[7:]
        if not token:
            return jsonify({'success': False, 'message': '未授权', 'code': 401}), 401
        try:
            payload = jwt.decode(token, _JWT_SECRET)
            if payload.get('type') != 'access':
                return jsonify({'success': False, 'message': 'token 类型错误', 'code': 401}), 401
            g.user_id = payload.get('user_id')
            g.role = payload.get('role', 0)
            g.username = payload.get('username')
            if g.role < UserRole.ADMIN:
                return jsonify({'success': False, 'message': '需要管理员权限', 'code': 403}), 403
            return f(*args, **kwargs)
        except Exception as e:
            return jsonify({'success': False, 'message': f'无效的 token: {e}', 'code': 401}), 401
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


# ---------- 管理员：Cookie 保险库 ----------
# cookie 是网站登录凭证，仅管理员可读写；落盘加密，列表不回传 value。
@script_bp.route('/api/admin/cookies', methods=['GET'])
@admin_required
def list_cookies():
    return jsonify({'success': True, 'cookies': mgr.vault.list() if mgr.vault else []})


@script_bp.route('/api/admin/cookies', methods=['POST'])
@admin_required
def create_cookie():
    if not mgr.vault:
        return jsonify({'success': False, 'message': 'vault 未初始化'}), 500
    data = request.get_json(silent=True) or {}
    name = data.get('name')
    domain = data.get('domain')
    fmt = data.get('format')
    value = data.get('value')
    if not name or not domain or not value:
        return jsonify({'success': False, 'message': 'name / domain / value 必填'}), 400
    if fmt not in ('netscape', 'header'):
        return jsonify({'success': False, 'message': 'format 必须为 netscape 或 header'}), 400
    pid = mgr.vault.add(name, domain, fmt, value)
    return jsonify({'success': True, 'id': pid})


@script_bp.route('/api/admin/cookies/<cid>', methods=['PUT'])
@admin_required
def update_cookie(cid):
    if not mgr.vault:
        return jsonify({'success': False, 'message': 'vault 未初始化'}), 500
    data = request.get_json(silent=True) or {}
    ok = mgr.vault.update(
        cid,
        name=data.get('name'),
        domain=data.get('domain'),
        fmt=data.get('format'),
        value=data.get('value'),
    )
    if not ok:
        return jsonify({'success': False, 'message': 'cookie 配置不存在'}), 404
    return jsonify({'success': True})


@script_bp.route('/api/admin/cookies/<cid>', methods=['DELETE'])
@admin_required
def delete_cookie(cid):
    if not mgr.vault:
        return jsonify({'success': False, 'message': 'vault 未初始化'}), 500
    ok = mgr.vault.delete(cid)
    if not ok:
        return jsonify({'success': False, 'message': 'cookie 配置不存在'}), 404
    return jsonify({'success': True})
