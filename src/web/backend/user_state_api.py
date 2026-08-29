"""统一用户状态服务（UserState）的 HTTP 接口。

为 core 与所有插件提供同一个跨设备状态原语：
  分层（global < user < device）+ 按键粒度 + 可声明合并语义。

命名空间 ns：'core' 或插件 id。插件侧不直接调本接口，而是通过宿主契约
host.state（见 extensions_host/plugin_host.py）经内部转发访问，保证
ns 自动隔离、无法越权读写别人的命名空间。

设备标识 device_id：由客户端 SDK 生成并持久化，经 X-Dbox-Device-Id 头或
device_id 参数传入；用于 device 作用域（滚动位置等不该跨设备串台的状态）。
"""
from flask import Blueprint, request, jsonify, g

from core.models import db, UserState
from core import state_merge
from backend.access import resolve_identity, admin_required
from backend.user_state_service import (
    merge_read, write_key, delete_key, device_of,
)

bp = Blueprint('user_state', __name__, url_prefix='/api/user-state')


def _require_user():
    """解析登录用户 id。

    用 resolve_identity()（解 Bearer / session 的统一入口）而非 resolve_user()：
    后者依赖全局 JWT 中间件注入 g.user_id，而该中间件（setup_auth_middleware）
    当前并未注册，纯 resolve_user 在 Bearer 场景下会拿不到用户。
    """
    user_id, _role = resolve_identity()
    if not user_id:
        return None, (jsonify({'success': False, 'message': '未授权', 'code': 401}), 401)
    return str(user_id), None


@bp.route('/<ns>', methods=['GET'])
def list_state(ns):
    """列出当前身份在某命名空间下的全部状态（已按 global<user<device 合并）。"""
    user_id, err = _require_user()
    if err:
        return err
    uid, dev = user_id, device_of(request)
    keys = request.args.get('keys')
    only = {k.strip() for k in keys.split(',') if k.strip()} if keys else None
    return jsonify({'success': True, 'ns': ns,
                    'data': merge_read(ns, uid, dev, only_keys=only)})


@bp.route('/<ns>/<key>', methods=['GET'])
def get_state(ns, key):
    user_id, err = _require_user()
    if err:
        return err
    uid, dev = user_id, device_of(request)
    merged = merge_read(ns, uid, dev, only_keys={key})
    item = merged.get(key)
    return jsonify({'success': True, 'key': key,
                    'value': item['value'] if item else None,
                    'rev': item['rev'] if item else 0,
                    'v': item['v'] if item else 1})


@bp.route('/<ns>/<key>', methods=['PUT'])
def put_state(ns, key):
    """写入单个状态：按声明的合并策略与已有值消解后落库。

    body: { value: 任意 JSON, strategy?: 'lww'|'max'|'union_by_id',
            v?: 数据 schema 版本, scope?: 'user'|'device'|'global',
            cap?: union_by_id 封顶条数, base_rev?: 乐观并发基线 }
    """
    user_id, err = _require_user()
    if err:
        return err
    uid, dev = user_id, device_of(request)
    body = request.get_json(silent=True) or {}
    if 'value' not in body:
        return jsonify({'success': False, 'message': '缺少 value'}), 400

    scope = (body.get('scope') or 'user').strip()
    if scope == 'global':
        # 全局层影响所有用户，仅管理员可写
        return admin_required(lambda: _do_put(ns, key, body, uid, dev, scope))()
    if scope not in ('user', 'device'):
        return jsonify({'success': False, 'message': '非法的 scope'}), 400
    return _do_put(ns, key, body, uid, dev, scope)


def _do_put(ns, key, body, uid, dev, scope):
    result = write_key(
        ns=ns, key=key, value=body.get('value'),
        scope=scope, owner=uid, device_id=dev,
        strategy=(body.get('strategy') or '').strip() or None,
        v=body.get('v') if isinstance(body.get('v'), int) else 1,
        cap=body.get('cap'), base_rev=body.get('base_rev'),
    )
    return jsonify({'success': True, 'key': key, **result})


@bp.route('/<ns>/<key>', methods=['DELETE'])
def remove_state(ns, key):
    user_id, err = _require_user()
    if err:
        return err
    uid, dev = user_id, device_of(request)
    scope = (request.args.get('scope') or 'user').strip()
    ok = delete_key(ns=ns, key=key, scope=scope, owner=uid, device_id=dev)
    return jsonify({'success': True, 'deleted': ok})


@bp.route('/<ns>/sync', methods=['POST'])
def sync_state(ns):
    """批量同步：一次往返完成「拉取全量 + 推送多键」，减少移动端往返开销。

    body: { put?: { key: { value, strategy?, v?, cap? } }, delete?: [key] }
    返回: 合并后的完整状态快照。
    """
    user_id, err = _require_user()
    if err:
        return err
    uid, dev = user_id, device_of(request)
    body = request.get_json(silent=True) or {}

    results = {}
    for key, payload in (body.get('put') or {}).items():
        if not isinstance(payload, dict) or 'value' not in payload:
            continue
        scope = (payload.get('scope') or 'user').strip()
        if scope not in ('user', 'device'):
            scope = 'user'
        results[key] = write_key(
            ns=ns, key=key, value=payload.get('value'), scope=scope,
            owner=uid, device_id=dev,
            strategy=(payload.get('strategy') or '').strip() or None,
            v=payload.get('v') if isinstance(payload.get('v'), int) else 1,
            cap=payload.get('cap'), base_rev=payload.get('base_rev'),
        )
    for key in (body.get('delete') or []):
        delete_key(ns=ns, key=str(key), scope='user', owner=uid, device_id=dev)

    return jsonify({'success': True, 'ns': ns, 'pushed': results,
                    'data': merge_read(ns, uid, dev)})
