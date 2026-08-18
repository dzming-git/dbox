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
# 需与 core.models.UserRole.ADMIN 的数值保持一致（管理员=100）。
ADMIN_ROLE = 100


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
from ai_chat import ai_mgr, list_models
import plan_manager

script_bp = Blueprint('script', __name__)


def init_script_engine(app):
    """由 extensions_host 应用工厂在 app 创建后调用，初始化管理器。"""
    mgr.init(app)
    # 初始化 AI 助手对话队列管理器（独立 data 目录，与脚本引擎一致）
    try:
        import os as _os
        env = _os.environ.get('DBOX_DATA_DIR')
        if env:
            _data_dir = env
        else:
            pkg_dir = _os.path.dirname(_os.path.abspath(__file__))
            _data_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(pkg_dir))), 'data')
        ai_mgr.init(_data_dir)
        plan_manager.init(_data_dir)
    except Exception as e:
        print('[extensions_host] 初始化 AI 对话管理器失败: %s' % e)


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
        if g.role < ADMIN_ROLE:
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
        g.role = payload.get('role', 0)
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
@login_required
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


# ---------- AI 助手对话（底层 FIFO 队列 + UI 无状态） ----------
# 设计：
#   - UI 无状态：不持有历史，仅做渲染与下发；对话上下文由服务端持久化。
#   - 底层用 FIFO 队列堆积未处理任务，单 worker 串行执行 CodeBuddy CLI。
#   - 三个逻辑队列（pending / active / history）由一张表（data/ai_chat.db）承载。
# 接口：
#   POST /api/ai-chat                      -> 仅入队，返回 { task_id }（立即返回，不阻塞）
#   GET  /api/ai-chat/tasks                -> 返回 pending + active + 最近 history
#   GET  /api/ai-chat/history?cursor=&limit -> 分页获取更早历史（展开更多）
#   GET  /api/ai-chat/tasks/<id>/stream    -> 按 task_id 订阅 SSE（token/done/error/queued/status）
#   DELETE /api/ai-chat/tasks/<id>         -> 取消排队中的任务 / 取消正在处理的任务 / 删除终态历史
#   POST /api/ai-chat/clear                -> 清空全部对话（重置上下文）


@script_bp.route('/api/ai-chat', methods=['POST'])
@login_required
def ai_chat_enqueue():
    """入队一条用户消息，立即返回 task_id（不阻塞、不流式）。"""
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'success': False, 'message': 'message 必填'}), 400
    # 工作流选择：用户通过前端按钮显式指定时带 workflow_id + manual；
    # 否则留空，由后端实时推断（技术可行时）或回落 chat。
    wf_id = (data.get('workflow_id') or '').strip() or None
    manual = bool(data.get('manual'))
    plan_mode = bool(data.get('plan_mode', False))
    model = (data.get('model') or '').strip() or None
    task_id, err = ai_mgr.enqueue(message, g.user_id, workflow_id=wf_id, manual=manual,
                                  plan_mode=plan_mode, model=model)
    if err:
        return jsonify({'success': False, 'message': err}), 400
    return jsonify({'success': True, 'task_id': task_id})


@script_bp.route('/api/ai-chat/models', methods=['GET'])
@login_required
def ai_chat_models():
    """返回 AI 助手可选模型列表。"""
    return jsonify({'success': True, 'models': list_models()})


@script_bp.route('/api/ai-chat/workflows', methods=['GET'])
@login_required
def ai_chat_workflows():
    """返回全部工作流元信息，供前端渲染「工作流选择」按钮浮层。"""
    try:
        return jsonify({'success': True, 'workflows': ai_mgr.list_workflows()})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@script_bp.route('/api/ai-chat/tasks/<task_id>/answer', methods=['POST'])
@login_required
def ai_chat_answer(task_id):
    """应答工作流中的 ask 步骤（如「继续」时选择要续接的问题单）。"""
    data = request.get_json(silent=True) or {}
    step_id = (data.get('step_id') or '').strip()
    choice = (data.get('choice') or '').strip()
    if not step_id or not choice:
        return jsonify({'success': False, 'message': 'step_id 与 choice 必填'}), 400
    ok = ai_mgr.answer_task(task_id, step_id, choice)
    if not ok:
        return jsonify({'success': False, 'message': '任务不存在或无需应答'}), 404
    return jsonify({'success': True})


@script_bp.route('/api/ai-chat/tasks', methods=['GET'])
@login_required
def ai_chat_tasks():
    """返回当前任务全景：排队中（FIFO）、正在处理、最近历史。"""
    try:
        limit = int(request.args.get('limit', 10))
    except (TypeError, ValueError):
        limit = 10
    out = ai_mgr.list_tasks(history_limit=max(1, min(limit, 50)))
    return jsonify({'success': True, **out})


@script_bp.route('/api/ai-chat/history', methods=['GET'])
@login_required
def ai_chat_history():
    """分页获取更早的历史（展开更多）。cursor 为上一页末条 created_at。"""
    try:
        limit = int(request.args.get('limit', 10))
    except (TypeError, ValueError):
        limit = 10
    cursor = request.args.get('cursor')
    if cursor:
        try:
            cursor = float(cursor)
        except (TypeError, ValueError):
            cursor = None
    out = ai_mgr.history_page(cursor=cursor, limit=max(1, min(limit, 50)))
    return jsonify({'success': True, **out})


@script_bp.route('/api/ai-chat/tasks/<task_id>/stream', methods=['GET'])
@login_required
def ai_chat_stream(task_id):
    """按 task_id 订阅该任务流式输出（SSE）。支持多端订阅与刷新重连。"""
    return Response(stream_with_context(ai_mgr.subscribe(task_id)),
                    mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@script_bp.route('/api/ai-chat/tasks/<task_id>', methods=['DELETE'])
@login_required
def ai_chat_delete(task_id):
    """删除/取消任务：排队中->取消排队；处理中->取消执行；终态->从历史删除。"""
    ok = ai_mgr.delete_task(task_id)
    if ok is None:
        return jsonify({'success': False, 'message': '任务取消中'}), 409
    if ok is False:
        return jsonify({'success': False, 'message': '任务不存在'}), 404
    return jsonify({'success': True})


@script_bp.route('/api/ai-chat/tasks/<task_id>/changes', methods=['GET'])
@login_required
def ai_chat_task_changes(task_id):
    """查询任务自开始到当前的代码改动（提交 + 未提交文件），供停止后展示与撤销决策。"""
    return jsonify(ai_mgr.get_task_changes(task_id))


@script_bp.route('/api/ai-chat/tasks/<task_id>/rollback', methods=['POST'])
@login_required
def ai_chat_task_rollback(task_id):
    """停止/完成后撤销本次改动：回退仓库到任务开始时的 HEAD（破坏性，需前端二次确认）。"""
    return jsonify(ai_mgr.rollback_task(task_id))


@script_bp.route('/api/ai-chat/clear', methods=['POST'])
@login_required
def ai_chat_clear():
    """清空全部对话（含排队与历史），重置多轮上下文。"""
    ai_mgr.clear()
    return jsonify({'success': True})


# ---------- AI 回复中的资源引用解析 ----------
# AI 在回复里用 [显示名](dbox://resource/<类型>/<标识>) 引用媒体库资源，前端渲染后可点击跳转。
# 该接口把 (类型, 标识) 解析为可跳转的 SPA 路径与封面，供面板渲染资源卡片。
# <标识> 支持三种形态：64 位 hex（视频/图集的 hash）、纯数字（帖子/文本 id）、或其它字符串（按标题模糊匹配）。
# 解析逻辑驻留在主服务（backend/internal_api 的 /internal/resource-resolve），本接口经
# platform_client 回调，避免拓展宿主直接 import 主服务的 core.models。
@script_bp.route('/api/ai-chat/resource-resolve', methods=['GET'])
@login_required
def ai_chat_resource_resolve():
    """根据 AI 回复中的资源引用 (type, ref) 解析出可跳转详情页路径与封面。"""
    rtype = (request.args.get('type') or '').strip().lower()
    ref = (request.args.get('ref') or '').strip()
    if not ref:
        return jsonify({'success': True, 'found': False})
    from platform_client import resource_resolve
    r = resource_resolve(rtype, ref)
    if isinstance(r, dict) and r.get('success'):
        return jsonify(r)
    return jsonify({'success': True, 'found': False})


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
from shared.credential_vault import CREDENTIAL_KINDS, KIND_COOKIE


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


# ---------- AI 助手 Plan 模式 ----------
# Plan 模式下 AI 仅生成可执行的修改计划文档（md），不实际改动代码；
# 用户可在 UI 中逐条点评，满意后点「执行」才触发真正的代码改动。
@script_bp.route('/api/ai-chat/plans', methods=['GET'])
@login_required
def list_ai_plans():
    """列出全部计划（摘要：不含正文，含状态）。"""
    return jsonify({'success': True, 'plans': plan_manager.list_plans()})


@script_bp.route('/api/ai-chat/plans/<plan_id>', methods=['GET'])
@login_required
def get_ai_plan(plan_id):
    """获取单个计划详情（含正文与用户点评）。"""
    plan = plan_manager.get_plan(plan_id)
    if plan is None:
        return jsonify({'success': False, 'message': '计划不存在'}), 404
    return jsonify({'success': True, 'plan': plan})


@script_bp.route('/api/ai-chat/plans/<plan_id>/comment', methods=['POST'])
@login_required
def comment_ai_plan(plan_id):
    """追加一条用户点评到计划文档的「用户点评」段。"""
    data = request.get_json(silent=True) or {}
    comment = (data.get('comment') or '').strip()
    if not comment:
        return jsonify({'success': False, 'message': '点评内容不能为空'}), 400
    ok = plan_manager.add_comment(plan_id, comment, owner_id=g.user_id)
    if not ok:
        return jsonify({'success': False, 'message': '计划不存在或写入失败'}), 400
    return jsonify({'success': True})


@script_bp.route('/api/ai-chat/plans/<plan_id>/execute', methods=['POST'])
@login_required
def execute_ai_plan(plan_id):
    """用户确认计划后，把计划正文作为执行指令重新提交（AI 真正改代码）。

    该步骤才会实际改动代码——plan 阶段只产出 md，绝不调用 shell / git。
    """
    plan = plan_manager.get_plan(plan_id)
    if plan is None:
        return jsonify({'success': False, 'message': '计划不存在'}), 404
    if plan['status'] == plan_manager.STATUS_EXECUTED:
        return jsonify({'success': False, 'message': '该计划已执行过'}), 400
    exec_msg = (
        '请基于以下已确认的修改计划，实际执行代码改动（可读取/修改文件、'
        '运行必要命令并验证）：\n\n' + plan['content']
    )
    data = request.get_json(silent=True) or {}
    model = (data.get('model') or '').strip() or None
    task_id, err = ai_mgr.enqueue(exec_msg, g.user_id, workflow_id=None, manual=True, model=model)
    if err:
        return jsonify({'success': False, 'message': err}), 400
    plan_manager.set_status(plan_id, plan_manager.STATUS_EXECUTED)
    return jsonify({'success': True, 'task_id': task_id})


@script_bp.route('/api/ai-chat/plans/<plan_id>', methods=['DELETE'])
@login_required
def delete_ai_plan(plan_id):
    """删除一个计划文档。"""
    ok = plan_manager.delete_plan(plan_id)
    if not ok:
        return jsonify({'success': False, 'message': '计划不存在'}), 404
    return jsonify({'success': True})

