# -*- coding: utf-8 -*-
"""library_watcher 删除行为契约测试（静态，不依赖运行中的服务）。

背景（真实事故）：一次增量扫描把 218 条视频误判为「文件已删除」并**硬删**
（db.session.delete，不进回收站），只能靠重新扫描补回，历史/标签/合集关联
随之失效。修复有两层：
  1. 删除判定 —— 不能把「本次没枚举到」当成「磁盘上不存在」（_plan_orphan_deletions）；
  2. 删除动作 —— 即便判定缺失，也只能**软删除进回收站**（remove_video）。

这两条都极易被后续改动无意破坏，而破坏的代价是不可逆的数据丢失，
因此用契约测试固化。

运行：python tests/test_library_watcher_contract.py
"""
import os
import re
import sys
import unittest

_SRC_WEB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'web'))
if _SRC_WEB not in sys.path:
    sys.path.insert(0, _SRC_WEB)

FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'src', 'web', 'library_watcher.py'))
# 入库已收敛到唯一服务，回收站恢复等语义也随之落在服务里
INGEST_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'src', 'web', 'backend', 'resource_ingest.py'))


def _func_body(src, name, indent=4):
    """截取某个函数的完整定义体（按缩进匹配收尾）。"""
    m = re.search(r'^%sdef %s\(' % (' ' * indent, name), src, re.M)
    if not m:
        return None
    start = m.start()
    i = len(m.group(0)) - 1
    depth = 0
    while i < len(src):
        if src[i] == '(':
            depth += 1
        elif src[i] == ')':
            depth -= 1
            if depth == 0:
                break
        i += 1
    # 函数体：从 def 所在行开始，到下一个同缩进的顶层 def / class 之前
    m2 = re.search(r'^\s{4}def\s|\s{4}@', src[start + 1:], re.M)
    if m2:
        return src[start:start + 1 + m2.start()]
    return src[start:]


def _strip_docstrings(body):
    """去掉三引号文档字符串再检查。

    否则会闹乌龙：remove_video 的注释里正是用 "db.session.delete" 来说明
    「为什么不再硬删」，静态检查会误判成仍在硬删。
    """
    return re.sub(r'"""(?:.|\n)*?"""', '', body or '')


class TestDeleteContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FILE, encoding='utf-8') as f:
            cls.src = f.read()

    def test_remove_video_no_hard_delete(self):
        body = _strip_docstrings(_func_body(self.src, 'remove_video'))
        self.assertIsNotNone(body, '未找到 remove_video')
        self.assertNotIn('db.session.delete', body,
                         'remove_video 不得硬删记录（必须走回收站，保证可恢复）')

    def test_remove_video_uses_trash(self):
        body = _func_body(self.src, 'remove_video')
        self.assertIn('move_to_trash', body, 'remove_video 应移入回收站')

    def test_remove_video_guards_existing_file(self):
        body = _func_body(self.src, 'remove_video')
        self.assertIn('os.path.exists(path)', body,
                      '删除前必须确认文件确实不在（move_to_trash 会移动文件，必须绝对安全）')

    def test_upsert_releases_quarantine(self):
        # 入库已收敛：upsert_video 改为调用唯一入库服务，回收站恢复语义随之落在服务里。
        # 因此断言分两层——watcher 必须走该服务，服务本身必须处理 in_trash。
        body = _func_body(self.src, 'upsert_video')
        self.assertIsNotNone(body)
        self.assertIn('ingest_video_file', body,
                      'upsert_video 必须走唯一入库服务（否则又会漏写索引/归属行）')
        with open(INGEST_FILE, encoding='utf-8') as f:
            isrc = f.read()
        ibody = _func_body(isrc, 'ingest_video_file', indent=0)
        self.assertIsNotNone(ibody, '未找到 ingest_video_file')
        self.assertIn('in_trash', ibody, '文件重新出现时应自动从回收站恢复')

    def test_orphan_plan_confirms_on_disk(self):
        body = _func_body(self.src, '_plan_orphan_deletions', indent=0)
        self.assertIsNotNone(body)
        self.assertIn('exists(', body,
                      '孤儿清理必须以磁盘实际状态为准，不能只看"本次是否枚举到"')


if __name__ == '__main__':
    unittest.main(verbosity=2)
