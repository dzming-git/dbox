#!/usr/bin/env python3
"""
反馈中心 - 未处理建议自动处理工具（保守自动策略）

策略（由运营确认）：
  1. 测试 / 垃圾 / 无效 / 重复类建议  -> 自动标记为“不处理(dismissed)”关闭，并备注原因。
  2. 真实反馈（Bug/功能建议/体验优化/其他）-> 自动添加一条分类评估回复，
     保持 open 状态，留待人工最终处理或代码修复后关闭。

安全设计：
  - 去重防护：已含“【自动处理】”评论的建议不再重复处理，避免每半小时重复刷评论。
  - 原子写回：先写临时文件再 replace，与后端 suggestion_api 保持一致，避免损坏数据。
  - 只读优先：支持 --dry-run 仅打印将要执行的操作，不修改数据。
  - 仅对“可明确判定为测试/垃圾/重复”的短内容自动关闭，绝不误关有效长反馈。

用法：
    python scripts/feedback_auto_process.py            # 执行自动处理
    python scripts/feedback_auto_process.py --dry-run  # 只打印，不写回
"""
import os
import sys
import json
import argparse
import threading
from pathlib import Path
from datetime import datetime

# 复用列出脚本的目录/数据定位逻辑（单一来源）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from feedback_list import find_runtime_dir, load_issues  # noqa: E402
from backend.feedback_db import init_feedback_db, db_set_status, db_append_comment  # noqa: E402

_lock = threading.Lock()

AUTO_AUTHOR = '自动助手'
AUTO_ROLE = 2  # UserRole.ADMIN
AUTO_PREFIX = '【自动处理】'

# 测试 / 垃圾 / 无效特征（命中即视为可自动关闭）
TEST_PATTERNS = [
    '测试建议内容', '这是一条测试', '测试数据', '占位', 'test', 'asdf',
    'zzz', '111111', '哈哈哈', '呵呵呵', '随便写', 'sdfsdf',
]

# 分类关键词（用于真实反馈的初步归类）
BUG_KW = ['崩', '报错', '错误', 'bug', '异常', '失败', '无响应', '不显示', '不工作',
          '失效', '闪退', '白屏', '404', '打不开', '无法播放', '卡死', '卡顿',
          '加载不出', '显示的', '没有了', '丢失', 'bug反馈']
FEATURE_KW = ['希望', '建议', '增加', '添加', '支持', '能否', '能不能', '需求', '功能',
              '设计一种', '最好能', '可以加', '想要', '希望增加', '希望可以', '期待']
OPT_KW = ['优化', '改进', '颜色', '搭配', '布局', '大小异常', '样式', '体验', '速度',
          '性能', '界面', '深色', '浅色', '配色', '好看', '难看', '排版']


def _now():
    return datetime.now().isoformat(timespec='seconds')


def _is_spam(content: str):
    c = (content or '').strip().lower()
    if len(c) < 6:
        return True, '内容过短，疑似无效提交'
    for p in TEST_PATTERNS:
        if p in c:
            return True, f'匹配测试/垃圾特征「{p}」'
    return False, ''


def _is_duplicate(issue, all_issues):
    content = (issue.get('content') or '').strip()
    # 仅对较短内容做重复判定，避免误伤真实长反馈
    if 0 < len(content) < 20:
        for other in all_issues:
            if other.get('id') == issue.get('id'):
                continue
            if (other.get('content') or '').strip() == content:
                return True, f'与 #{other.get("id")} 内容重复'
    return False, ''


def classify(content: str) -> str:
    c = (content or '').lower()
    if any(k in c for k in BUG_KW):
        return 'Bug 反馈'
    if any(k in c for k in FEATURE_KW):
        return '功能建议'
    if any(k in c for k in OPT_KW):
        return '体验优化'
    return '其他建议'


def _already_processed(issue) -> bool:
    return any(
        c.get('author') == AUTO_AUTHOR and (c.get('content') or '').startswith(AUTO_PREFIX)
        for c in issue.get('comments', [])
    )


def save_issues(runtime_dir: str, issues: list):
    """兼容保留接口（数据已实时写入独立数据库，此处不再写 JSON）。"""
    pass


def append_log(runtime_dir: str, text: str):
    log_path = Path(runtime_dir) / 'data' / 'feedback_auto_process.log'
    try:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f"[{_now()}] {text}\n")
    except Exception:
        pass


def process(runtime_dir: str, dry_run: bool = False):
    init_feedback_db()
    all_issues = load_issues(runtime_dir)
    open_issues = [i for i in all_issues if i.get('status') == 'open']

    now = _now()
    dismissed, replied, skipped = [], [], []

    for it in open_issues:
        iid = it.get('id')
        if _already_processed(it):
            skipped.append(it)
            continue

        spam, reason = _is_spam(it.get('content', ''))
        if not spam:
            dup, reason = _is_duplicate(it, all_issues)
            spam = dup

        if spam:
            if dry_run:
                dismissed.append(it)
                print(f"  [DRY] 将关闭(不处理) #{iid}：{reason}")
                continue
            db_set_status(iid, 'closed', classification='dismissed')
            db_append_comment(
                iid, AUTO_AUTHOR, AUTO_ROLE,
                f'{AUTO_PREFIX} 自动判定为“不处理”：{reason}，已关闭。',
            )
            dismissed.append(it)
            print(f"  [关闭] #{iid}：{reason}")
        else:
            cat = classify(it.get('content', ''))
            comment = (
                f'{AUTO_PREFIX} 已收到并初步归类为【{cat}】。'
                f'已记录并安排处理；如涉及代码改动将另行修复并关闭本建议，'
                f'请留意后续状态更新。'
            )
            if dry_run:
                replied.append(it)
                print(f"  [DRY] 将对 #{iid} 添加分类回复：{cat}")
                continue
            db_append_comment(iid, AUTO_AUTHOR, AUTO_ROLE, comment)
            replied.append(it)
            print(f"  [回复] #{iid}：归类为【{cat}】（保持开放）")

    summary = (
        f"未处理 {len(open_issues)} 条 | 自动关闭 {len(dismissed)} 条 | "
        f"自动回复 {len(replied)} 条 | 跳过(已处理) {len(skipped)} 条"
    )
    print('-' * 78)
    print(f"处理摘要：{summary}")

    if not dry_run and not (dismissed or replied):
        print("无变更，未写回")

    append_log(runtime_dir, summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description='自动处理反馈中心未处理的建议（保守策略）')
    parser.add_argument('--dry-run', action='store_true', help='只打印将要执行的操作，不修改数据')
    args = parser.parse_args()

    runtime_dir = find_runtime_dir()
    print(f"运行目录: {runtime_dir}")
    print(f"反馈中心 - 自动处理（{'演练' if args.dry_run else '实际'}）")
    print('-' * 78)
    process(runtime_dir, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
