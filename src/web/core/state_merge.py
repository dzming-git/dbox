"""用户状态合并策略（UserState 的冲突消解层）。

设计要点：不同状态各有其「天然的」合并语义，用一把 last-write-wins 硬套
必然丢数据。因此合并策略由写入方按键声明，服务端据此消解：

  lww          后写覆盖。适合「当前标签页」「游标」这类以最后一次意图为准的标量。
  max          单调取大。适合「已读边界」「播放进度」这类只应前进、不应被
               其它设备的旧值回退的量。
  union_by_id  列表并集去重后封顶。适合「浏览缓存」「历史」「最近使用」——
               两台设备各自拉到的条目应合并，而不是互相覆盖。

策略是可插拔的：新增语义只需在此注册一个函数，无需改动 API 与存储层。
"""
from datetime import datetime

# 列表合并时用于识别同一条目的候选 id 字段（按序优先命中）
DEFAULT_ID_KEYS = ('id', 'tweet_id', 'gid', 'hash', 'url', 'path')
DEFAULT_ORDER_KEY = 'created_at'
DEFAULT_CAP = 400


def _sortable_ts(value, order_key=DEFAULT_ORDER_KEY):
    """把条目/标量的时间字段转成可比较数值；无法解析时返回负无穷。"""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return float('-inf')
        # 纯数字字符串（如雪花 id）按数值比较
        try:
            return float(raw)
        except ValueError:
            pass
        # ISO 时间字符串
        candidate = raw[:-1] + '+00:00' if raw.endswith('Z') else raw
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            return float('-inf')
        return dt.timestamp()
    if isinstance(value, dict):
        return _sortable_ts(value.get(order_key), order_key)
    return float('-inf')


def _item_id(item, id_keys):
    if not isinstance(item, dict):
        return None
    for k in id_keys:
        v = item.get(k)
        if v not in (None, ''):
            return str(v)
    return None


def merge_lww(old, new, **_kw):
    """后写覆盖。"""
    return new, True


def merge_max(old, new, **_kw):
    """单调取大：仅当新值更大时才前进，避免被其它设备的旧值回退。"""
    new_key, old_key = _sortable_ts(new), _sortable_ts(old)
    if old is None:
        return new, True
    if new_key > old_key:
        return new, True
    return old, False


def merge_union_by_id(old, new, cap=DEFAULT_CAP, id_keys=None,
                      order_key=DEFAULT_ORDER_KEY, **_kw):
    """列表并集：按 id 去重（同 id 保留较新的一份），按时间倒序后封顶。"""
    keys = tuple(id_keys) if id_keys else DEFAULT_ID_KEYS
    merged, order = {}, []

    for lst in (old, new):
        if not isinstance(lst, list):
            continue
        for item in lst:
            if not isinstance(item, dict):
                continue
            iid = _item_id(item, keys)
            if iid is None:
                # 无 id 的条目无法去重，原样保留（放在末尾）
                order.append((None, item))
                continue
            if iid in merged:
                # 同 id 取较新的一份
                if _sortable_ts(item, order_key) >= _sortable_ts(merged[iid], order_key):
                    merged[iid] = item
            else:
                merged[iid] = item
                order.append((iid, None))

    items = [anon if anon is not None else merged[iid] for iid, anon in order]
    items.sort(key=lambda it: _sortable_ts(it, order_key), reverse=True)
    if isinstance(cap, int) and cap > 0:
        items = items[:cap]
    return items, True


# 策略注册表：name -> func(old, new, **kw) -> (merged_value, changed)
STRATEGIES = {
    'lww': merge_lww,
    'max': merge_max,
    'union_by_id': merge_union_by_id,
}

DEFAULT_STRATEGY = 'lww'


def resolve(name):
    return STRATEGIES.get((name or '').strip()) or STRATEGIES[DEFAULT_STRATEGY]


def merge(name, old, new, **kw):
    """按策略名合并新旧值，返回 (合并后的值, 是否发生变化)。"""
    return resolve(name)(old, new, **kw)
