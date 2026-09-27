#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提交前守卫：拦住「开发机上的真实信息」进版本库。

约定（红线）：入库内容里不允许出现开发机的真实环境信息——本机绝对路径（含用户名）、
本机工作目录名、私网 IP、开发账号/邮箱、以及临时脚本与截图。历史上这类内容混进过
提交（示例里直接抄了本机路径），清理要动历史、代价很大，所以前置拦截。

用法：
  python scripts/guard_private_data.py                # 扫「已暂存」内容（pre-commit 用）
  python scripts/guard_private_data.py --all          # 扫全部已跟踪文件
  python scripts/guard_private_data.py <file> [...]   # 只扫指定文件

某一行确实是「必须出现的示例」时，在该行加注释 `guard-allow` 显式放行（留痕，便于复核）。

装成 pre-commit 钩子（每个仓各装一次，钩子本身不入库）：把下面内容存成
`<仓库>/.git/hooks/pre-commit`（LF 换行）即可：::

    #!/bin/sh
    p=$(git rev-parse --show-toplevel 2>/dev/null)
    while [ -n "$p" ] && [ "$p" != "/" ]; do
      if [ -f "$p/scripts/guard_private_data.py" ]; then
        PY=$(command -v python || command -v python3); [ -n "$PY" ] || exit 0
        exec "$PY" "$p/scripts/guard_private_data.py"
      fi
      p=$(dirname "$p")
    done
    exit 0

退出码：0 通过；1 发现疑似泄露（提交会被拒绝）。
"""
import argparse
import os
import re
import subprocess
import sys

# 控制台可能是 GBK（中文 Windows），报告里又难免有非 GBK 字符：强制 UTF-8 输出，
# 免得「检测到泄露」这件事反而因为打印报错而看不见
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# (说明, 正则)。正则对**整行**匹配，命中即报告。
RULES = [
    ("本机用户目录绝对路径（含真实用户名）",
     r"[A-Za-z]:[\\/]+Users[\\/]+(?![Pp]ublic|[Dd]efault|All [Uu]sers|<|%|\*)"
     r"([A-Za-z0-9._]|%USERNAME%)"),
    ("本机工作目录名",
     r"<工作目录>"),  # guard-allow: 规则本身必须写出该字面量
    ("开发账号或邮箱",
     r"<用户ID>|dzm_work|dzming-git@"),  # guard-allow: 同上，规则里必须出现这些字面量
    ("私网 IP（真实内网地址；示例请用 203.0.113.x 这类文档地址）",
     r"\b(192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"),
    ("临时/调试产物（截图、*.tmp.*、临时日志）",
     r"(^|[\\/])shot[^\\/]*\.(png|jpg|js)$|\.tmp\.(js|py|ps1|txt|log|json)$|(^|[\\/])_?(test|debug)[^\\/]*\.tmp\."),
    ("长数字 ID（推文/雪花 ID 等真实记录标识）",
     r"\b\d{18,}\b"),  # guard-allow: 规则本身要匹配长数字
]

# 个人词表：本机私有词（真实标题、账号名、特定 ID…）无法用通用正则枚举，放到**不入库**的
# 本地文件里，一行一个（`#` 开头为注释）。提交信息与文件内容都会按字面量比对。
TERMS_FILE = os.path.join(os.path.expanduser('~'), '.dbox_guard_terms')

# 二进制/大文件不做文本扫描
SKIP_EXT = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.pdf', '.zip',
            '.gz', '.7z', '.rar', '.mp4', '.mp3', '.woff', '.woff2', '.ttf',
            '.pyc', '.db', '.exe', '.dll', '.so'}
SKIP_DIR = {'node_modules', 'venv', '.git', '__pycache__', '.pytest_cache'}
ALLOW_MARK = 'guard-allow'


def _iter_files(paths, tracked_all=False):
    if tracked_all:
        out = subprocess.run(['git', 'grep', '-l', '', '--', '.'], capture_output=True, text=True)
        paths = [p for p in out.stdout.splitlines() if p.strip()]
    for p in paths:
        p = p.strip()
        if not p or not os.path.isfile(p):
            continue
        if any(part in SKIP_DIR for part in p.replace('\\', '/').split('/')):
            continue
        if os.path.splitext(p)[1].lower() in SKIP_EXT:
            continue
        yield p


def load_terms():
    """读取本机私有词表（不入库）。"""
    terms = []
    try:
        with open(TERMS_FILE, 'r', encoding='utf-8', errors='replace') as fh:
            for line in fh:
                t = line.strip()
                if t and not t.startswith('#'):
                    terms.append(t)
    except Exception:
        pass
    return terms


def scan_text(label, text, pats, terms):
    """按规则 + 私人词表扫一段文本（文件内容或提交信息）。"""
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if ALLOW_MARK in line:
            continue
        matched = False
        for desc, rx in pats:
            if rx.search(line):
                hits.append((label, i, desc, line.strip()[:160]))
                matched = True
                break
        if matched:
            continue
        for t in terms:
            if t in line:
                hits.append((label, i, '命中本机私有词表', line.strip()[:160]))
                break
    return hits


def scan(paths, pats, terms):
    """返回 [(文件, 行号, 规则说明, 该行内容)]。"""
    hits = []
    for f in _iter_files(paths):
        try:
            with open(f, 'r', encoding='utf-8', errors='replace') as fh:
                hits.extend(scan_text(f, fh.read(), pats, terms))
        except Exception:
            continue
    return hits


def main():
    ap = argparse.ArgumentParser(description='检查入库内容是否含开发机真实信息')
    ap.add_argument('files', nargs='*', help='要检查的文件（默认取 git 已暂存文件）')
    ap.add_argument('--all', action='store_true', help='检查全部已跟踪文件')
    ap.add_argument('--msg-file', help='检查提交信息文件（commit-msg 钩子用）')
    args = ap.parse_args()

    pats = [(desc, re.compile(rx)) for desc, rx in RULES]
    terms = load_terms()

    # 提交信息模式：提交信息里同样不许出现本机信息与真实数据举例
    if args.msg_file:
        try:
            with open(args.msg_file, 'r', encoding='utf-8', errors='replace') as fh:
                text = fh.read()
        except Exception as e:
            print('[guard] 读不到提交信息（%s），跳过' % e)
            return 0
        hits = scan_text('提交信息', text, pats, terms)
        if not hits:
            print('[guard] 通过：提交信息未发现本机真实信息')
            return 0
        print('[guard] 拒绝提交：提交信息里出现本机真实信息（不要拿真实数据当例子）\n')
        for f, i, desc, t in hits:
            print('  %s:%d  [%s]\n      %s' % (f, i, desc, t))
        print('\n改成虚构示例；确需保留的整行用注释 %s 放行。' % ALLOW_MARK)
        return 1

    files = args.files
    if not files and not args.all:
        out = subprocess.run(['git', 'diff', '--cached', '--name-only', '--diff-filter=ACM'],
                             capture_output=True, text=True)
        files = [p for p in out.stdout.splitlines() if p.strip()]
        if not files:
            print('[guard] 没有暂存文件，跳过')
            return 0

    hits = scan(files, pats, terms) if not args.all else scan(list(_iter_files([], tracked_all=True)), pats, terms)
    if not hits:
        print('[guard] 通过：未发现开发机真实信息')
        return 0

    print('[guard] 拒绝提交：入库内容里出现开发机真实信息\n')
    for f, i, desc, text in hits:
        print('  %s:%d  [%s]\n      %s' % (f, i, desc, text))
    print('\n处理方式：换成占位符（项目根 / %%APPDATA%% / 203.0.113.7 等），'
          '或在该行加注释 %s 显式放行。' % ALLOW_MARK)
    return 1


if __name__ == '__main__':
    sys.exit(main())
