"""用户状态服务的读写层（被 HTTP 接口与插件宿主契约共用）。

分层模型（优先级低 -> 高）：global < user < device
  读取：各层按键合并，越具体的层覆盖越通用的层。
  写入：只写调用者自己的层，借助 state_merge 的策略与同层已有值消解。

这样既保证「账号级设置跨设备共享」，又保证「滚动位置等按设备隔离」，
且任何一层都不会因整块覆盖而丢数据。
"""
from flask import request

from core.models import db, UserState
from core import state_merge

DEFAULT_NS = 'core'
VALID_SCOPES = ('global', 'user', 'device')


def device_of(req=None):
    """解析设备标识：优先 X-Dbox-Device-Id 头，回退 device_id 查询参数。

    归属用户（owner）由调用方从登录用户取，不在此解析，避免误用空 owner。
    """
    r = req if req is not None else request
    try:
        return (r.headers.get('X-Dbox-Device-Id')
                or r.args.get('device_id') or '').strip()
    except Exception:
        return ''


def _row(ns, scope, owner, device_id, key):
    return UserState.query.filter_by(
        ns=ns, scope=scope, owner=owner, device_id=device_id, key=key).first()


def merge_read(ns, owner, device_id='', only_keys=None):
    """按 global < user < device 合并读取某命名空间下的状态。"""
    device_id = device_id or ''
    layers = (
        ('global', '', ''),
        ('user', owner, ''),
        ('device', owner, device_id) if device_id else (None, None, None),
    )
    out = {}
    for scope, own, dev in layers:
        if scope is None:
            continue
        q = UserState.query.filter_by(ns=ns, scope=scope, owner=own, device_id=dev)
        if only_keys:
            q = q.filter(UserState.key.in_(list(only_keys)))
        for row in q.all():
            # 越具体的层后处理，自然覆盖通用层
            out[row.key] = {
                'value': row.get_value(),
                'rev': row.rev,
                'v': row.v,
                'scope': row.scope,
                'strategy': row.strategy,
                'updated_at': row.updated_at.isoformat() if row.updated_at else None,
            }
    return out


def read_layer(ns, key, scope='user', owner='', device_id=''):
    """读取指定层的单个键值（不做层合并），返回 (value, row)。

    settings 这类接口需要把 global / user 各层「分别」返回、由前端自行合并，
    因此不能用 merge_read（它会把多层折叠成一个值）。
    """
    if scope == 'global':
        owner, device_id = '', ''
    elif scope == 'user':
        device_id = ''
    row = _row(ns, scope, owner, device_id, key)
    return (row.get_value() if row else None), row


def write_key(ns, key, value, scope='user', owner='', device_id='',
              strategy=None, v=1, cap=None, base_rev=None,
              lease_key=None, lease_rev=None):
    """写入（合并）单个键。返回 {value, rev, v, strategy, changed, conflict, stale}。

    base_rev 提供乐观并发：传入且不等于当前 rev 时拒绝写入，避免
    客户端基于过期快照覆盖他人改动。

    lease_key / lease_rev 提供**主控栅栏（fencing）**：写入前校验调用方持有的
    租约版本号是否仍是最新。租约由 acquire（对该键的一次 lww 写入）单调递增 rev，
    若服务端 rev 已更大（说明主控权被其它设备抢占），则拒绝本次写入并返回
    stale=True——避免过期设备把陈旧状态回写、覆盖主控设备刚同步的较新状态。
    未传 lease_key 时完全不校验，旧客户端与无需门控的键行为不变。

    union_by_id 的记录约定为 { id, order, ...载荷 }（见 state_merge），
    字段映射由各入口边界完成，故此处不再接收任何插件字段名。
    """
    if scope not in VALID_SCOPES:
        scope = 'user'
    if scope == 'global':
        owner, device_id = '', ''
    elif scope == 'user':
        device_id = ''

    row = _row(ns, scope, owner, device_id, key)
    if row is None:
        row = UserState(ns=ns, scope=scope, owner=owner, device_id=device_id,
                        key=key, value='null', strategy=state_merge.DEFAULT_STRATEGY,
                        v=v, rev=0)
        db.session.add(row)

    strat = (strategy or row.strategy or state_merge.DEFAULT_STRATEGY)
    if strat not in state_merge.STRATEGIES:
        strat = state_merge.DEFAULT_STRATEGY

    old_value = row.get_value()
    if base_rev is not None and row.rev != int(base_rev) and row.rev != 0:
        # 乐观并发冲突：返回当前服务端值，不写入
        return {'value': old_value, 'rev': row.rev, 'v': row.v,
                'strategy': strat, 'changed': False, 'conflict': True}

    # 主控栅栏：租约键不存在（无人持有主控权）或调用方版本落后于服务端 → 拒绝写入。
    # 与 base_rev 的区别：base_rev 由调用方自己重读即可绕过，租约则必须由服务端
    # 签发（acquire）才能抬高，因此能真正挡住「过期设备持续回写」。
    if lease_key:
        lease_row = _row(ns, 'user', owner, '', str(lease_key))
        try:
            got_rev = int(lease_rev)
        except (TypeError, ValueError):
            got_rev = -1
        if lease_row is None or got_rev < (lease_row.rev or 0):
            return {'value': old_value, 'rev': row.rev, 'v': row.v,
                    'strategy': strat, 'changed': False, 'conflict': False,
                    'stale': True}

    kw = {}
    if strat == 'union_by_id':
        kw['cap'] = cap if isinstance(cap, int) and cap > 0 else state_merge.DEFAULT_CAP
    merged, changed = state_merge.merge(strat, old_value, value, **kw)

    row.strategy = strat
    row.v = v
    if changed:
        row.value = _dump(merged)
        row.rev = (row.rev or 0) + 1
    db.session.commit()
    return {'value': row.get_value(), 'rev': row.rev, 'v': row.v,
            'strategy': strat, 'changed': changed, 'conflict': False}


def delete_key(ns, key, scope='user', owner='', device_id=''):
    if scope == 'global':
        owner, device_id = '', ''
    elif scope == 'user':
        device_id = ''
    row = _row(ns, scope, owner, device_id, key)
    if not row:
        return False
    db.session.delete(row)
    db.session.commit()
    return True


def _dump(value):
    import json
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return 'null'
