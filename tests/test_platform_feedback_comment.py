# -*- coding: utf-8 -*-
"""向已有反馈单追加「自动助手」留言的通道测试（platform_client.add_feedback_comment）。

验证：内容非空时调用 /internal/feedback/comment 并返回成功；空内容/主服务不可达
时返回 False，不抛异常、不落 spool（与建单不同，回复类留言由调用方提示稍后重试）。
"""
import os
import sys
from unittest import mock

_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'extensions_host'))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import platform_client as pc


def test_add_feedback_comment_success():
    with mock.patch.object(pc, '_post', return_value={'success': True}):
        assert pc.add_feedback_comment('202608130018', '分析：根因为 X') is True


def test_add_feedback_comment_empty_skips_post():
    with mock.patch.object(pc, '_post') as m:
        assert pc.add_feedback_comment('202608130018', '   ') is False
        m.assert_not_called()


def test_add_feedback_comment_network_error_returns_false():
    with mock.patch.object(pc, '_post',
                           return_value={'success': False, 'message': 'x',
                                         'network_error': True}):
        assert pc.add_feedback_comment('202608130018', '解决说明') is False


if __name__ == '__main__':
    import unittest
    unittest.main()
