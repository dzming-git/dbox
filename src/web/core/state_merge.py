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

# 列表合并封顶条数
DEFAULT_CAP = 400

# union_by_id 的规范记录契约：每条记录必须是 dict，且带
#   id    : 字符串，去重主键（不同设备/来源的同一条目用同一个 id）
#   order : 可排序值（数字或 ISO 时间串），用于「同 id 取较新一份」与整体倒序
# 任意其它字段都是载荷，合并层不关心其含义——因此通用状态层彻底与插件
# 的字段命名解耦（不会再有 tweet_id / illustId / create_date 这类名字
# 泄漏进核心）。字段映射（domain -> {id, order}）由各入口边界负责。



def _sortable_ts(value):
    """把可排序值（数字或 ISO 时间串）转成可比较数值；无法解析时返回负无穷。"""
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
    return float('-inf')


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


def merge_union_by_id(old, new, cap=DEFAULT_CAP, **_kw):
    """列表并集：按 id 去重（同 id 保留 order 较新的一份），按 order 倒序后封顶。

    记录约定为 { id: str, order: 可排序值(数字/ISO时间), ...任意载荷 }。
    合并层只看 id / order，不关心载荷里是什么字段——这样通用状态层与
    各插件的字段命名完全解耦（瀑布流缓存、历史、最近使用都复用同一逻辑）。
    """
    merged, order = {}, []

    for lst in (old, new):
        if not isinstance(lst, list):
            continue
        for item in lst:
            if not isinstance(item, dict):
                continue
            iid = item.get('id')
            if iid in (None, ''):
                # 无 id 的条目无法去重，原样保留（放在末尾）
                order.append((None, item))
                continue
            iid = str(iid)
            if iid in merged:
                # 同 id 取较新的一份
                if _sortable_ts(item.get('order')) >= _sortable_ts(merged[iid].get('order')):
                    merged[iid] = item
            else:
                merged[iid] = item
                order.append((iid, None))

    items = [anon if anon is not None else merged[iid] for iid, anon in order]
    items.sort(key=lambda it: _sortable_ts(it.get('order')), reverse=True)
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
