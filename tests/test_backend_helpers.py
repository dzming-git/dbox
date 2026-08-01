# -*- coding: utf-8 -*-
"""backend.*_helpers 纯函数单元测试。

仅覆盖不依赖数据库会话的纯逻辑，验证下沉后的辅助函数行为正确。
运行：python tests/test_backend_helpers.py
"""
import os
import sys
import unittest

# 将 src/web 与 src 加入模块搜索路径：backend.*/core.* 在 src/web，liblog 在 src
_SRC_WEB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'web'))
_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src'))
for _p in (_SRC_WEB, _SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backend.helpers import _build_tag_tree, _resolve_post_refs  # noqa: E402
from backend.library_helpers import _INVALID_NAME_RE  # noqa: E402


class TestBuildTagTree(unittest.TestCase):
    def test_flat_no_parent(self):
        tags = [
            {'id': 1, 'parent_id': None, 'name': 'A'},
            {'id': 2, 'parent_id': None, 'name': 'B'},
        ]
        tree = _build_tag_tree(tags)
        self.assertEqual(len(tree), 2)
        self.assertEqual(tree[0]['name'], 'A')
        self.assertEqual(tree[1]['name'], 'B')

    def test_nested_hierarchy(self):
        tags = [
            {'id': 1, 'parent_id': None, 'name': '动物'},
            {'id': 2, 'parent_id': 1, 'name': '狗'},
            {'id': 3, 'parent_id': 2, 'name': '哈士奇'},
        ]
        tree = _build_tag_tree(tags)
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0]['name'], '动物')
        children = tree[0]['children']
        self.assertEqual(children[0]['name'], '狗')
        self.assertEqual(children[0]['children'][0]['name'], '哈士奇')

    def test_dangling_parent_treated_as_root(self):
        # parent_id 指向不存在的节点，应退化为根
        tags = [
            {'id': 2, 'parent_id': 999, 'name': '狗'},
        ]
        tree = _build_tag_tree(tags)
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0]['name'], '狗')

    def test_preserves_original_fields(self):
        tags = [{'id': 5, 'parent_id': None, 'name': 'X', 'category': '类型', 'extra': 1}]
        tree = _build_tag_tree(tags)
        self.assertEqual(tree[0]['extra'], 1)
        self.assertEqual(tree[0]['category'], '类型')


class TestInvalidNameRe(unittest.TestCase):
    def test_detects_illegal_chars(self):
        for ch in ['\\', '/', ':', '*', '?', '"', '<', '>', '|']:
            self.assertIsNotNone(_INVALID_NAME_RE.search('abc' + ch + 'def'),
                                 f"应检出非法字符 {ch}")

    def test_accepts_valid_name(self):
        self.assertIsNone(_INVALID_NAME_RE.search('我的资源库 2024'))


class TestResolvePostRefs(unittest.TestCase):
    def test_empty_refs_returns_empty(self):
        self.assertEqual(_resolve_post_refs(None), [])
        self.assertEqual(_resolve_post_refs([]), [])

    def test_skips_non_dict_entries(self):
        # 非 dict 元素应被跳过且不抛异常（不触发 DB 查询分支）
        refs = [None, "not-a-dict", 123]
        result = _resolve_post_refs(refs)
        self.assertEqual(result, [])

    def test_skips_ref_without_resource_index_id(self):
        # 缺少 resource_index_id 且无 type/id 映射的 dict 应被跳过
        refs = [{'note': 'x'}, {'type': 'unknown', 'id': 5}]
        result = _resolve_post_refs(refs)
        self.assertEqual(result, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
