# -*- coding: utf-8 -*-
"""验证 AI 助手自动建单的结构：标题=概括、内容=问题描述、留言=AI 处理动作。

此前自动跟踪单的标题是「AI 处理：<原始诉求首行>」、内容里混入了「AI 做了什么」，
且完全没有留言。本测试确认：
- 标题为对问题的概括（剥离命令词/截断），不再照抄原始诉求；
- 内容为问题描述（用户诉求原文）；
- AI 的处理说明作为「自动助手」身份的首条留言写入 feedback_comments。
"""
import os
import sys
import json
import tempfile
import importlib
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', 'src', 'extensions_host'))
sys.path.insert(0, os.path.join(_HERE, '..', 'src', 'web', 'backend'))

import ai_chat as ac
import platform_client as pc


def test_make_ticket_title_summarizes():
    # 剥离开头命令词，保留问题本质
    assert ac._make_ticket_title('你来解决这个问题：下载服务状态显示异常') == '下载服务状态显示异常'
    # 按断句截断到首句
    assert ac._make_ticket_title('图集列表空白。点赞收藏页也空白') == '图集列表空白'
    # 空诉求兜底
    assert ac._make_ticket_title('   ') == 'AI 处理任务'
    # 超长截断
    long_p = '稍后再看的视频反复复活且' + '很长的描述' * 20
    t = ac._make_ticket_title(long_p)
    assert len(t) <= 41 and t.endswith('…')


def test_tracking_ticket_structure_mocked():
    """不落库：确认 _maybe_create_tracking_ticket 把标题/内容/留言正确传给建单接口。"""
    captured = {}

    def fake_file_feedback(ftype, title, content, extra=None, status='open', comment=None):
        captured['call'] = dict(ftype=ftype, title=title, content=content,
                                extra=extra, status=status, comment=comment)
        return '202608130001'

    prompt = '你来解决这个问题：稍后再看里有个很早的视频删了无数次还反复出现'
    reply = ('已完成修复并提交 git。\n'
             '## 问题根因\n硬删除 + 列表按可见性隐藏导致复活。\n'
             '## 修复内容\n改为服务端软删除。')

    with mock.patch.object(pc, 'file_feedback', fake_file_feedback), \
         mock.patch.object(ac, '_git_rev_head', return_value='newcommit123'):
        out_reply, track_id = ac._maybe_create_tracking_ticket(
            'task-1', prompt, 'owner-1', reply, None, head_before='oldcommit',
            git_clean=True)

    assert track_id == '202608130001'
    call = captured['call']
    # 标题应为概括，而非 "AI 处理：<原始首行>"
    assert not call['title'].startswith('AI 处理：')
    assert call['title'] == '稍后再看里有个很早的视频删了无数次还反复出现'
    # 内容=问题描述（用户诉求原文）
    assert call['content'] == prompt
    # 留言=AI 的处理动作（来自回复），且以自动助手身份写入
    assert call['comment'] == reply
    assert call['status'] == 'pending_verification'
    assert call['extra']['git_commit'] == 'newcommit123'
    assert call['extra']['git_clean'] is True
    # 回复末尾被追加了跟踪单提示
    assert '📋 已创建处理跟踪单：#202608130001' in out_reply


def test_tracking_ticket_writes_comment_to_db():
    """落库：确认建单后 feedback_comments 存在一条「自动助手」留言，内容为 AI 的处理动作。"""
    tmp = tempfile.mkdtemp()
    os.environ['DBOX_DATA_DIR'] = tmp
    import feedback_db
    importlib.reload(feedback_db)
    feedback_db.init_feedback_db()

    captured = {}

    def fake_file_feedback(ftype, title, content, extra=None, status='open', comment=None):
        # 模拟主服务内部接口：直接落库（含留言）
        captured['call'] = dict(title=title, content=content, comment=comment, status=status)
        issue_id = feedback_db.db_create_issue(
            title=title, content=content, category=ftype,
            submitter='自动助手', source='ai_assistant', auto_classified=True,
            status=status, extra=extra, comment=comment)
        return issue_id

    prompt = '反馈中心自动建单逻辑有问题，标题应该是概括'
    reply = '已修复：标题改为概括、内容改为问题描述、处理动作写入留言。'

    with mock.patch.object(pc, 'file_feedback', fake_file_feedback), \
         mock.patch.object(ac, '_git_rev_head', return_value='commitabc'):
        out_reply, track_id = ac._maybe_create_tracking_ticket(
            'task-2', prompt, 'owner-2', reply, None, head_before='commitold',
            git_clean=True)

    assert track_id
    # 在 session 内读取，避免 detached 懒加载报错
    with feedback_db.get_session() as session:
        from feedback_db import FeedbackIssue
        issue = session.get(FeedbackIssue, track_id)
        assert issue is not None
        # 概括：剥离命令词、按句号截断、超长截断；此处不足 40 字故保留原诉求
        assert issue.title == '反馈中心自动建单逻辑有问题，标题应该是概括'
        assert issue.content == prompt                  # 问题描述
        comments = list(issue.comments)                 # 触发懒加载并物化
    assert len(comments) == 1
    c = comments[0]
    assert c.author == '自动助手'
    assert c.author_role == 2
    assert c.content == reply                          # 留言=AI 的处理动作
    # 清理临时库
    try:
        os.remove(feedback_db.FEEDBACK_DB_PATH)
    except Exception:
        pass
