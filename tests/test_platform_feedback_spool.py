# -*- coding: utf-8 -*-
"""针对 AI 助手「结构性保证反馈中心建单」的耐久化测试。

核心验证：主服务（8080）不可达时，建单请求经过重试后落地本地 spool，
绝不静默丢单；主服务恢复后 flush_feedback_spool 能补建并清理 spool。
"""
import os
import sys
import json
import shutil
import tempfile
import unittest
from unittest import mock

# 让导入解析到 src/extensions_host
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', 'src', 'extensions_host'))

import platform_client as pc


class FeedbackSpoolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='fbspl_')
        os.environ['DBOX_DATA_DIR'] = self.tmp
        # 清空可能存在的 spool，确保用例隔离
        self.spool_dir = pc._feedback_spool_dir()
        if os.path.isdir(self.spool_dir):
            shutil.rmtree(self.spool_dir)
        os.makedirs(self.spool_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop('DBOX_DATA_DIR', None)

    def _spool_files(self):
        if not os.path.isdir(self.spool_dir):
            return []
        return [f for f in os.listdir(self.spool_dir)
                if f.startswith('fb_') and f.endswith('.json')]

    def test_network_down_retries_then_spools(self):
        """主服务不可达：重试 3 次后落 spool，返回 None 但不丢单。"""
        with mock.patch.object(pc, '_post', return_value={
                'success': False, 'message': '平台调用失败: [WinError 10061] 拒绝连接'
        }) as m:
            rid = pc.file_feedback('bug', '标题', '内容',
                                   extra={'git_commit': 'abc'}, status='pending_verification')
        self.assertIsNone(rid)
        self.assertEqual(m.call_count, pc._FB_MAX_RETRIES)
        files = self._spool_files()
        self.assertEqual(len(files), 1)
        # spool 内容完整，含 extra/status
        with open(os.path.join(self.spool_dir, files[0]), 'r', encoding='utf-8') as f:
            payload = json.load(f)
        self.assertEqual(payload['type'], 'bug')
        self.assertEqual(payload['status'], 'pending_verification')
        self.assertEqual(payload['extra']['git_commit'], 'abc')

    def test_validation_error_not_spooled(self):
        """业务校验错误（非网络）：不重试、不落 spool，直接返回 None。"""
        with mock.patch.object(pc, '_post', return_value={
                'success': False, 'message': '标题和内容不能同时为空'
        }) as m:
            rid = pc.file_feedback('bug', '', '')
        self.assertIsNone(rid)
        self.assertEqual(m.call_count, 1)   # 不可重试，仅调用一次
        self.assertEqual(len(self._spool_files()), 0)

    def test_flush_creates_ticket_and_cleans_spool(self):
        """主服务恢复后，flush 补建单号并删除 spool 文件。"""
        # 先把一条请求落 spool
        with mock.patch.object(pc, '_post', return_value={
                'success': False, 'message': '平台调用失败: 连接被拒'
        }):
            pc.file_feedback('suggestion', '建议标题', '建议内容', status='open')
        self.assertEqual(len(self._spool_files()), 1)

        with mock.patch.object(pc, '_post', return_value={
                'success': True, 'issue_id': '202608130001'
        }) as m:
            created = pc.flush_feedback_spool()
        self.assertEqual(created, ['202608130001'])
        self.assertEqual(len(self._spool_files()), 0)  # spool 已清理
        # flush 时 POST 的正是 spool 里的同一份 payload
        args, _ = m.call_args
        self.assertEqual(args[0], '/feedback')
        self.assertEqual(args[1]['title'], '建议标题')

    def test_flush_keeps_failed_spool(self):
        """主服务仍不可达时，flush 不影响 spool，留待下次重试。"""
        with mock.patch.object(pc, '_post', return_value={
                'success': False, 'message': '平台调用失败: 连接被拒'
        }):
            pc.file_feedback('bug', 't', 'c')
        with mock.patch.object(pc, '_post', return_value={
                'success': False, 'message': '平台调用失败: 连接被拒'
        }):
            created = pc.flush_feedback_spool()
        self.assertEqual(created, [])
        self.assertEqual(len(self._spool_files()), 1)

    def test_success_no_spool(self):
        """主服务正常：一次成功，直接返回单号，不落 spool。"""
        with mock.patch.object(pc, '_post', return_value={
                'success': True, 'issue_id': '202608130002'
        }) as m:
            rid = pc.file_feedback('bug', 't', 'c')
        self.assertEqual(rid, '202608130002')
        self.assertEqual(m.call_count, 1)
        self.assertEqual(len(self._spool_files()), 0)


if __name__ == '__main__':
    unittest.main()
