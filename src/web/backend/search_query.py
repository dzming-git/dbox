# -*- coding: utf-8 -*-
"""搜索筛选语法解析。

用户可以在搜索框里直接写条件，而不必去翻筛选面板：

    tag:猫              —— 带某个标签
    library:movie       —— 属于某个资源库（名称，支持部分匹配）
    type:video          —— 限定资源类型（video / gallery / post / text）
    date:2026-09        —— 某个时间范围内加入的（2026 / 2026-09 / 2026-09-14）
    duration:>20min     —— 时长条件（> < >= <=，单位 s / min / h）

未被识别的部分保留为自由文本（按标题匹配），因此
`猫 tag:动物 duration:>10min` 这样的混写也能正常工作。

解析是**纯函数**（不碰数据库、不依赖 Flask），便于单测与各列表接口复用。
"""
import re

# 形如 key:value，value 不含空白；若是 >20min 这类，符号也允许紧随冒号
_TOKEN_RE = re.compile(r'(\w+):([<>=!]*)([^\s:]+)')

_DURATION_UNIT = {
    's': 1,
    'sec': 1,
    'm': 60,
    'min': 60,
    'h': 3600,
    'hour': 3600,
}


def parse_duration(value: str):
    """把 '20min' / '1.5h' / '90s' 解析成秒；失败返回 None。"""
    if not value:
        return None
    m = re.match(r'^(\d+(?:\.\d+)?)\s*([a-zA-Z]*)$', value.strip())
    if not m:
        return None
    num = float(m.group(1))
    unit = (m.group(2) or 's').lower()
    factor = _DURATION_UNIT.get(unit)
    if factor is None:
        return None
    return num * factor


def parse_date(value: str):
    """把 '2026' / '2026-09' / '2026-09-14' 解析成 (起始, 结束) 时间戳元组。

    结束时间按开区间处理（如 2026-09 → 到 2026-10-01 为止）。
    """
    from datetime import datetime

    v = (value or '').strip()
    for fmt, granularity in (('%Y-%m-%d', 'day'), ('%Y-%m', 'month'), ('%Y', 'year')):
        try:
            start = datetime.strptime(v, fmt)
        except ValueError:
            continue
        if granularity == 'day':
            end = start.replace(day=start.day) + _oneday()
        elif granularity == 'month':
            end = _next_month(start)
        else:
            end = start.replace(year=start.year + 1)
        return start, end
    return None


def _oneday():
    from datetime import timedelta
    return timedelta(days=1)


def _next_month(dt):
    if dt.month == 12:
        return dt.replace(year=dt.year + 1, month=1, day=1)
    return dt.replace(month=dt.month + 1, day=1)


def parse_query(text: str):
    """把搜索词拆成结构化条件 + 剩余自由文本。

    返回 dict：
      text        —— 去掉条件后剩下的自由文本（可能为空）
      tags        —— 标签名列表
      library     —— 资源库名（部分匹配）
      kind        —— 资源类型
      date        —— (start, end) 或 None
      duration_min / duration_max —— 秒；None 表示不限
    """
    out = {
        'text': '',
        'tags': [],
        'library': None,
        'kind': None,
        'date': None,
        'duration_min': None,
        'duration_max': None,
    }
    if not text:
        return out

    rest = []

    def _take(m):
        key = m.group(1).lower()
        op = m.group(2) or ''
        val = m.group(3)
        if key == 'tag' and val:
            out['tags'].append(val)
            return True
        if key in ('library', 'lib') and val:
            out['library'] = val
            return True
        if key in ('type', 'kind') and val:
            out['kind'] = val.lower()
            return True
        if key == 'date' and val:
            rng = parse_date(val)
            if rng:
                out['date'] = rng
                return True
            return False
        if key in ('duration', 'dur', 'length') and val:
            secs = parse_duration(val.lstrip('<>=!'))
            if secs is None:
                return False
            if op in ('>', '>='):
                # 「>20分钟」含 20 分钟本身更符合直觉，故 >= 与 > 同义
                out['duration_min'] = secs
            elif op in ('<', '<='):
                out['duration_max'] = secs
            else:
                out['duration_min'] = secs
            return True
        return False

    pos = 0
    for m in _TOKEN_RE.finditer(text):
        rest.append(text[pos:m.start()])
        pos = m.end()
        if not _take(m):
            # 认不出的条件当作普通文本，别让用户觉得"输了个寂寞"
            rest.append(m.group(0))
    rest.append(text[pos:])

    out['text'] = ' '.join(x for x in rest if x).strip()
    return out
