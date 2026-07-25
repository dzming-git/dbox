#!/usr/bin/env python3
"""
反馈中心 - 未处理建议列出工具

读取反馈中心数据文件（data/issues.json），列出当前所有“未处理(open)”的建议。
纯只读，不修改任何数据，可安全频繁运行。

用法：
    python scripts/feedback_list.py            # 列出未处理建议（默认）
    python scripts/feedback_list.py --all      # 列出全部建议（含已关闭）
    python scripts/feedback_list.py --json     # 以 JSON 格式输出
    python scripts/feedback_list.py --csv      # 以 CSV 格式输出

数据文件定位优先级：
    1. 环境变量 DPLAYER_RUNTIME 指向的目录
    2. 脚本所在目录向上查找含 data/issues.json 或 install.json 的目录
    3. 当前工作目录
"""
import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime


def find_runtime_dir() -> str:
    """定位运行目录（与后端 api.system_api.get_runtime_dir 保持一致的优先级）"""
    env = os.environ.get('DPLAYER_RUNTIME')
    if env and os.path.isdir(env):
        return env

    here = Path(__file__).resolve()
    candidates = [here.parent, here.parent.parent, Path.cwd()]
    # 向上再扩展几层，覆盖更多部署结构
    for lvl in range(1, 5):
        candidates.append(here.parents[min(lvl, len(here.parents) - 1)])

    for c in candidates:
        if (c / 'data' / 'issues.json').exists():
            return str(c)
    for c in candidates:
        inj = c / 'install.json'
        if inj.exists():
            try:
                data = json.loads(inj.read_text(encoding='utf-8'))
                rd = data.get('runtime_dir')
                if rd and os.path.isdir(rd):
                    return rd
            except Exception:
                pass
    return os.getcwd()


def load_issues(runtime_dir: str) -> list:
    path = Path(runtime_dir) / 'data' / 'issues.json'
    if not path.exists():
        return []
    try:
        # 使用 utf-8-sig 兼容带 BOM 的文件（Windows 工具可能写出 BOM）
        with open(path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _fmt_date(iso: str) -> str:
    if not iso:
        return ''
    try:
        d = datetime.fromisoformat(iso)
        return d.strftime('%Y-%m-%d %H:%M')
    except Exception:
        return iso


def _short(text: str, n: int = 50) -> str:
    text = (text or '').replace('\n', ' ').strip()
    return text[:n] + ('…' if len(text) > n else '')


def main():
    parser = argparse.ArgumentParser(description='列出反馈中心未处理的建议')
    parser.add_argument('--all', action='store_true', help='列出全部建议（含已关闭）')
    parser.add_argument('--json', action='store_true', help='以 JSON 格式输出')
    parser.add_argument('--csv', action='store_true', help='以 CSV 格式输出')
    args = parser.parse_args()

    runtime_dir = find_runtime_dir()
    issues = load_issues(runtime_dir)

    if args.all:
        target = issues
        label = '全部'
    else:
        target = [i for i in issues if i.get('status') == 'open']
        label = '未处理(open)'

    target.sort(key=lambda x: x.get('created_at', ''), reverse=True)

    if args.json:
        print(json.dumps({'count': len(target), 'issues': target}, ensure_ascii=False, indent=2))
        return

    if args.csv:
        print('id,title,author,status,created_at,comments')
        for it in target:
            print(','.join([
                str(it.get('id', '')),
                f'"{_short(it.get("title", ""), 200)}"',
                str(it.get('author', '')),
                str(it.get('status', '')),
                _fmt_date(it.get('created_at', '')),
                str(len(it.get('comments', []))),
            ]))
        return

    print(f'运行目录: {runtime_dir}')
    print(f'反馈中心 - {label}建议: 共 {len(target)} 条')
    print('-' * 78)
    if not target:
        print('  （暂无建议）')
        return
    for it in target:
        print(f"  #{it.get('id')}  [{it.get('status')}]  {_short(it.get('title', ''), 60)}")
        print(f"       作者: {it.get('author')}   创建: {_fmt_date(it.get('created_at', ''))}   回复: {len(it.get('comments', []))}")
    print('-' * 78)


if __name__ == '__main__':
    main()
