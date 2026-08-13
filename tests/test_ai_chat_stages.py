# -*- coding: utf-8 -*-
"""AI 助手分阶段进度（stage 事件）测试。

验证：宿主进程在 _process 管线各阶段向订阅者发射 stage 事件，
聊天窗口可据此分阶段反馈处理进展（而非长时间无反馈）。

通过伪造 subprocess.Popen，使 _process 在不依赖真实 buddy CLI 的情况下
跑通「加载上下文 -> 做事前核查 -> 启动执行 -> 收尾建单/核查」全链路，
并断言至少发射了一个 stage 事件、任务最终 completed。

运行：python tests/test_ai_chat_stages.py
"""
import os
import sys
import io
import json
import queue
import tempfile
import unittest
from unittest import mock

_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'extensions_host'))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import ai_chat as m


class IntentClassifyTest(unittest.TestCase):
    """意图判定（建议 / 缺陷 / 继续 / 闲聊）确定性测试。"""
    def test_defect(self):
        self.assertEqual(m._classify_intent('稍后再看里有个视频删了又出现，排查一下'), 'defect')
        self.assertEqual(m._classify_intent('下载服务异常，状态显示不正确'), 'defect')

    def test_suggestion(self):
        self.assertEqual(m._classify_intent('建议增加一个批量导出功能'), 'suggestion')
        self.assertEqual(m._classify_intent('希望优化一下脚本流程'), 'suggestion')

    def test_continue(self):
        self.assertEqual(m._classify_intent('继续上面的修复'), 'continue')
        self.assertEqual(m._classify_intent('刚才那个问题再处理一下'), 'continue')

    def test_chat(self):
        self.assertEqual(m._classify_intent('你好'), 'chat')
        self.assertEqual(m._classify_intent('谢谢'), 'chat')

    def test_work_category_from_intent(self):
        # 反馈中心类型应复用意图判定：缺陷 -> bug，建议 -> suggestion
        self.assertEqual(m._classify_work_category('下载服务异常，排查一下'), 'bug')
        self.assertEqual(m._classify_work_category('建议增加批量导出'), 'suggestion')
        self.assertEqual(m._classify_work_category('继续上面的修复'), 'other')


class _FakeProc:
    """极简伪进程：stdout 吐一行文本、退出码 0，使 _process 正常走完。"""
    def __init__(self):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO('已处理完成\n'.encode('utf-8'))
        self.stderr = io.BytesIO(b'')
        self.returncode = 0
        self.pid = 1

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass

    def communicate(self, *a, **k):
        return b'', b''


class StageEmitTest(unittest.TestCase):
    def test_process_emits_stage_events(self):
        mgr = m.AIChatManager()
        tmp = tempfile.mkdtemp()
        mgr.init(tmp)

        with mock.patch.object(m.subprocess, 'Popen', lambda *a, **k: _FakeProc()), \
             mock.patch.object(m, '_resolve_buddy_cli', lambda: 'codebuddy'):
            # 直接插入任务（不走 enqueue，避免 worker 线程重复执行 _process 干扰事件捕获）
            import uuid
            tid = 'ai_' + uuid.uuid4().hex[:16]
            mgr._insert_task(tid, '测试分阶段进度', None, m.AIChatManager.STATUS_PENDING)

            # 注册订阅者队列以捕获 _process 发射的事件
            q = queue.Queue()
            with mgr._lock:
                mgr._subscribers[tid] = [q]

            mgr._process(tid)

            events = []
            while True:
                try:
                    item = q.get(timeout=2)
                except queue.Empty:
                    break
                events.append(item)

        stage_labels = [d for (k, d) in events if k == 'stage']
        self.assertTrue(stage_labels, '应至少发射一个 stage 事件')
        # 阶段应按处理顺序出现：首项为「判断用户意图」（结构化 JSON，含结论）、
        # 末项为处理完成，且中间覆盖做事前核查与启动执行等关键阶段。
        self.assertIn('判断用户意图', stage_labels[0])
        self.assertIn('处理完成', stage_labels[-1])
        self.assertTrue(any('检查 git 仓库状态' in s for s in stage_labels), '应含做事前核查阶段')
        self.assertTrue(any('启动 AI 执行' in s for s in stage_labels), '应含启动执行阶段')
        # 意图判断阶段应为结构化 JSON，并携带结论
        first = json.loads(stage_labels[0])
        self.assertEqual(first['text'], '判断用户意图（建议 / 缺陷 / 继续 / 闲聊）')
        self.assertIn('判断结果', first.get('conclusion', ''))
        # 任务应正常完成
        self.assertEqual(mgr.get_task(tid)['status'], m.AIChatManager.STATUS_COMPLETED)

    def test_sse_block_stage_format(self):
        block = m._sse_block('stage', '做事前核查：检查 git 仓库状态')
        self.assertIn('event: stage', block)
        self.assertIn('data: 做事前核查：检查 git 仓库状态', block)


if __name__ == '__main__':
    unittest.main()
