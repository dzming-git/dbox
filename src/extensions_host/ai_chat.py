"""AI 助手对话队列管理器

将 AI 助手对话改造为「底层排队 + UI 无状态」模型：

- 用户发送的消息以任务（task）形式入队，后端立即返回 task_id，不阻塞；
- 底层用 FIFO 队列堆积「未处理」任务，单 worker 串行执行 CodeBuddy CLI；
- 任务状态机：pending（排队中）-> running（正在处理）-> completed / failed / cancelled；
- 对话上下文（多轮）由服务端持久化，前端不持有历史，仅做渲染与下发；
- 已处理任务保留为历史队列，列表接口默认返回最近 N 条，前端可「展开更多」翻页；
- 任意任务可经 task_id 订阅 SSE，支持多端同时订阅与刷新后重连（任务仍在执行时续接流式输出）。

数据落在 data/ai_chat.db（独立表 ai_tasks），并轻量镜像到统一任务表（kind='ai_chat'），
使全局任务管理器也能看到正在处理的 AI 任务。

本模块运行于独立的拓展宿主进程（extensions_host），不直接 import 主服务的业务模块：
- 反馈中心的建单经由 platform_client 以 HTTP 转发给主服务的内部接口完成；
- codebuddy 凭证经由共享库 shared.credential_vault 读取（中立、无业务依赖）。
"""
import os
import sys
import re
import json
import time
import uuid
import signal
import queue
import threading
import subprocess
import sqlite3

import logging
_logger = logging.getLogger('extensions_host.ai_chat')

try:
    from subprocess import CREATE_NEW_PROCESS_GROUP
except ImportError:
    CREATE_NEW_PROCESS_GROUP = 0

# 单个 AI 任务的最大执行时长（秒）。超时则由看门狗强制结束进程树，
# 防止 CodeBuddy 拉起子进程后 stdout 管道不关闭导致 worker 永久阻塞、队列卡死。
_MAX_TASK_SECONDS = 600

# ----------------------------------------------------------------------------
# CLI 辅助函数（原 routes.py 中的 AI 专用逻辑迁移至此）
# ----------------------------------------------------------------------------
_ANTHROPIC_API_KEY_ENV = 'ANTHROPIC_API_KEY'
_CODEBUDDY_TOKEN_DOMAIN = 'codebuddy'


def _load_codebuddy_token() -> str:
    """从通用凭证保险库读取 codebuddy token（与 feedback_ai 一致）。"""
    env_token = os.environ.get(_ANTHROPIC_API_KEY_ENV)
    if env_token:
        return env_token.strip()
    try:
        from shared.credential_vault import CredentialVault, data_dir_for
        vault = CredentialVault(data_dir_for())
        tok = vault.get_token(domain=_CODEBUDDY_TOKEN_DOMAIN)
        if tok:
            return tok.strip()
        for rec in vault.list_all():
            if rec.get('kind') == 'token' and 'codebuddy' in (rec.get('name') or '').lower():
                return (rec.get('value') or '').strip()
    except Exception:
        pass
    return ''


def _project_root() -> str:
    pkg_dir = os.path.dirname(os.path.abspath(__file__))         # src/extensions_host
    return os.path.dirname(os.path.dirname(pkg_dir))             # 向上两级 -> 项目根 (dbox)


def _resolve_buddy_cli() -> str:
    """定位 codebuddy CLI 绝对路径。

    服务可能以不同用户（如 LocalSystem）运行，%APPDATA% 解析到的目录
    并不含 npm，故需在常见位置逐一回退；找不到时再尝试 PATH 搜索。
    """
    cands = []
    env_buddy = os.environ.get('DBOX_BUDDYCN')
    if env_buddy:
        cands.append(env_buddy)
    appdata = os.environ.get('APPDATA')
    if appdata:
        cands.append(os.path.join(appdata, 'npm', 'codebuddy.cmd'))
    # 常见用户绝对路径（与本项目实际运行用户一致）
    for uname in ('71555',):
        cands.append(r'C:\Users\%s\AppData\Roaming\npm\codebuddy.cmd' % uname)
        cands.append(r'C:\Users\%s\AppData\Local\npm\codebuddy.cmd' % uname)
    # 项目内的 codebuddy（若在 PATH 或本地）
    try:
        import shutil
        on_path = shutil.which('codebuddy.cmd') or shutil.which('codebuddy')
        if on_path:
            cands.append(on_path)
    except Exception:
        pass
    seen = set()
    for c in cands:
        if not c or c in seen:
            continue
        seen.add(c)
        if os.path.isfile(c):
            return c
    return ''


def _codebuddy_user_home() -> str:
    """返回存放 CodeBuddy 登录会话的交互用户家目录。

    主服务可能以 SYSTEM/服务账户运行，其本地登录会话位于交互用户（如 71555）
    的 ~/.codebuddy 下。优先用环境变量 DBOX_BUDDYCN_HOME 指定，否则回退到
    硬编码的常见用户名家目录；找不到则返回空串（沿用调用方环境）。
    """
    env_home = os.environ.get('DBOX_BUDDYCN_HOME')
    if env_home and os.path.isdir(env_home):
        return env_home
    for uname in ('71555',):
        home = r'C:\Users\%s' % uname
        if os.path.isdir(home):
            return home
    return ''


def _is_auth_error(text: str) -> bool:
    t = (text or '').lower()
    return any(k in t for k in ('未登录', '认证失败', 'auth fail', 'unauthorized',
                                'invalid api key', 'login required', 'please login'))


def _build_reply(out_lines, err_text, returncode):
    """从 stdout 行与 stderr 文本构造最终回复，返回 (reply, fell_back_stdout)。

    - stdout 有内容时优先采用；
    - stdout 为空、退出码正常、且 stderr 承载了助手正文时，回退采用 stderr，
      避免聊天框出现「（任务已执行完成，无文本输出）」占位。buddy 在部分运行
      环境（非 TTY 管道）下会把最终回复写到 stderr 而非 stdout，此前只读 stdout
      导致正文被丢弃、频繁出现空输出。
    - 认证错误 / 崩溃栈已由调用方在 returncode 非 0 或 _is_auth_error 时拦截，
      此处 stderr 内容即助手正文，可直接采用。
    """
    reply = '\n'.join(out_lines or []).strip()
    if reply:
        return reply, False
    if returncode in (0, None) and err_text and not _is_auth_error(err_text):
        err_reply = err_text.strip()
        if err_reply:
            return err_reply, True
    return '', False


def _sse_block(event: str, data) -> str:
    """构造一段合规的 SSE 文本块。

    data 中的换行会被拆成多行 `data:` 字段，避免破坏 SSE 协议
    （否则含换行的回复会导致事件解析错位、前端拿不到完整回复）。
    """
    data = '' if data is None else str(data)
    lines = data.split('\n')
    return 'event: %s\n' % event + ''.join('data: ' + ln + '\n' for ln in lines) + '\n'


def _parse_phases(raw):
    """把存库的 phases JSON 字符串解析为阶段列表；缺失/损坏时回退空列表。"""
    if not raw:
        return None
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else None
    except Exception:
        return None


def _file_feedback(ftype: str, title: str, content: str, extra: dict = None,
                  status: str = 'open', comment: str = None):
    """在反馈中心建一条反馈单，返回新单号；失败返回 None。

    仅由 _maybe_file_feedback / _maybe_create_tracking_ticket 调用。
    身份遵循项目准则：反馈中心交互使用「自动助手」身份
    （submitter='自动助手'、source='ai_assistant'、auto_classified=True）。
    建单经 platform_client 转发给主服务的内部接口 /internal/feedback 完成，
    使本模块无需直接依赖主服务的 backend.feedback_db。
    extra / status 用于 AI 处理完成后的「跟踪单」（关联提交哈希、置待验证）。
    """
    try:
        from platform_client import file_feedback
        if ftype not in ('bug', 'suggestion', 'other'):
            ftype = 'suggestion'
        title = (title or '').strip()
        content = (content or '').strip()
        if not title and not content:
            return None
        return file_feedback(ftype, title, content, extra=extra, status=status,
                             comment=comment)
    except Exception as e:
        try:
            import logging
            logging.getLogger('extensions_host').warning('AI 助手建单失败: %s' % e)
        except Exception:
            pass
        return None


def _maybe_file_feedback(reply: str):
    """若 AI 回复内含 feedback-request 块，则建单并回填单号、剥离该块。

    返回 (处理后的回复文本, 新建单号或 None)。解析/建单失败时保留原回复、仅剥离块，
    单号返回 None。
    """
    if not reply:
        return reply, None
    m = _FB_RE.search(reply)
    if not m:
        return reply, None
    issue_id = None
    try:
        data = json.loads(m.group(1).strip())
        ftype = data.get('type')
        title = data.get('title')
        content = data.get('content')
        if isinstance(ftype, str) and isinstance(title, str) and isinstance(content, str):
            issue_id = _file_feedback(ftype, title, content)
    except Exception:
        issue_id = None
    # 剥离 feedback-request 围栏块（避免在前端露出原始 JSON）
    reply = (reply[:m.start()] + reply[m.end():]).strip()
    if issue_id:
        token = '#(待分配)'
        if token in reply:
            reply = reply.replace(token, '#' + issue_id, 1)
        else:
            reply = reply + ('\n\n📋 已提交反馈单：#%s' % issue_id)
    return reply, issue_id


def _git_rev_head(repo: str) -> str:
    """返回仓库当前 HEAD 提交哈希；非 git 仓库或出错返回空串。"""
    try:
        out = subprocess.run(
            ['git', 'rev-parse', 'HEAD'], cwd=repo,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20,
        ).stdout.decode('utf-8', errors='replace').strip()
        return out
    except Exception:
        return ''


def _git_status_porcelain(repo: str):
    """返回 `git status --porcelain` 的解码输出；非 git 仓库 / 出错返回 None。"""
    try:
        out = subprocess.run(
            ['git', 'status', '--porcelain'], cwd=repo,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20,
        ).stdout.decode('utf-8', errors='replace')
        return out
    except Exception:
        return None


def _git_dirty_files(repo: str):
    """返回当前工作树中「未提交」文件集合（含未跟踪与已修改/已暂存）。

    用于做事后比对：只有「基线集合之外的新增脏文件」才可归因于本次 AI 运行。
    非 git 仓库或无法判定时返回 None。
    """
    out = _git_status_porcelain(repo)
    if out is None:
        return None
    files = set()
    for line in out.splitlines():
        line = line.rstrip('\n')
        if not line.strip():
            continue
        # porcelain 前两字符为 XY 状态，其后为空格 + 路径（重命名形如 "a -> b"）
        body = line[3:].strip() if len(line) > 3 else line.strip()
        if ' -> ' in body:
            body = body.split(' -> ', 1)[1]
        if body:
            files.add(body)
    return files


# 符合项目规范、可被安全自动清理的临时文件名特征（避免误删真实改动）。
_TEMP_NAME_HINTS = ('_commit_msg', '.tmp', '.bak', '.orig', '~',
                    'tmp_', 'scratch', 'test_tmp')


def _looks_temporary(path: str) -> bool:
    base = os.path.basename(path).lower()
    if base in ('_commit_msg.txt',):
        return True
    for h in _TEMP_NAME_HINTS:
        if h in base:
            return True
    return False


def _verify_and_report_clean(repo: str, baseline_dirty, head_before, reply: str):
    """做事后结构核查：保证本次 AI 运行没有在仓库留下未提交的脏文件。

    返回 (reply, clean_bool)。逻辑：
    - 非 git 仓库 / 无法判定：跳过重构，返回 clean=True；
    - 计算「新增脏文件」= 当前脏文件 − 运行前基线脏文件（仅这些可归因于本次运行）；
    - 对符合项目规范的可丢弃临时文件（_commit_msg.txt / *.tmp 等）先自动清理；
    - 若清理后仍有残留脏文件：在回复中追加告警，列出文件，提示人工提交或清理；
    - 若运行前就存在、运行后依旧脏的基线文件：仅作温和提醒（不归因于本次）。

    该检查与「模型是否自觉提交」无关，由进程客观比对仓库状态，从而在结构上
    保证 git 仓库干净——即使模型漏提交/漏清理临时脚本，也会被兜底发现并处置。
    """
    if baseline_dirty is None:
        return reply, True
    current = _git_dirty_files(repo)
    if current is None:
        return reply, True

    new_dirty = current - baseline_dirty           # 本次运行新增的可疑脏文件
    leftover_baseline = baseline_dirty & current     # 运行前已脏、运行后依旧脏

    if not new_dirty and not leftover_baseline:
        return reply, True

    # 先尝试清理符合项目规范的临时文件
    removed = []
    for f in list(new_dirty):
        full = os.path.join(repo, f)
        if _looks_temporary(f) and os.path.isfile(full):
            try:
                os.remove(full)
                new_dirty.discard(f)
                removed.append(f)
            except Exception:
                pass

    parts = []
    if not new_dirty:
        msg = '⚠️ 检测到本次任务产生了未提交文件，已按项目规范自动清理临时文件：' \
              + '、'.join(removed) + '。仓库现已恢复干净。'
        parts.append(msg)
    else:
        msg = ('⚠️ git 仓库未保持干净：本次任务遗留了未提交的改动/文件，'
               '请人工确认并提交或清理（不要遗留临时脚本）：')
        msg += '\n' + '\n'.join('- ' + f for f in sorted(new_dirty))
        if removed:
            msg += '\n（已自动清理临时文件：' + '、'.join(removed) + '）'
        parts.append(msg)

    if leftover_baseline:
        parts.append('（提示：任务开始前仓库即存在未提交改动，仍遗留：'
                     + '、'.join(sorted(leftover_baseline))
                     + '；这些不归因于本次任务，建议另行处理）')

    reply = (reply or '') + '\n\n' + '\n'.join(parts)
    return reply, (len(new_dirty) == 0)


# 用户意图四类：建议 / 缺陷 / 继续 / 闲聊（用于分阶段进度展示与模型对齐参考）。
_INTENT_LABELS = {
    'suggestion': '建议',
    'defect': '缺陷',
    'continue': '继续',
    'chat': '闲聊',
}


def _classify_intent(prompt: str) -> str:
    """确定性判断用户诉求的意图类别，供阶段进度展示与模型对齐参考。

    返回 'suggestion'（建议）/ 'defect'（缺陷）/ 'continue'（继续）/ 'chat'（闲聊）。
    优先级：继续 > 缺陷 > 建议 > 闲聊。纯问候 / 无实质任务视为闲聊。
    该判断由宿主进程基于关键词客观完成（不依赖模型输出），从而在结构上保证
    「每条消息先判断意图」这一环节必然发生并被展示，不靠提示词兜底。
    """
    p = (prompt or '').lower()
    continue_kw = ('继续', '接着', '然后呢', '还有呢', '再处理', '上一个', '刚才那个',
                   '之前那个', '刚刚说的', '上面那个', '进一步', '再帮我')
    defect_kw = ('bug', '错误', '异常', '故障', '失败', '崩溃', '不显示', '空白',
                 '不动', '修复', '排查', '报错', '卡死', '不对', '没反应', '没生效',
                 '不行', '问题', '出现', '闪退')
    suggestion_kw = ('建议', '功能', '特性', '优化', '新增', '支持', '需求', '实现',
                    '增强', '希望', '能不能', '能否', '最好', '应该')
    chat_kw = ('你好', '您好', 'hi', 'hello', '在吗', '谢谢', '感谢', '哈哈', '哦', '嗯', '好的')
    if any(k in p for k in continue_kw):
        return 'continue'
    if any(k in p for k in defect_kw):
        return 'defect'
    if any(k in p for k in suggestion_kw):
        return 'suggestion'
    if not p or len(p) < 6 or any(k in p for k in chat_kw):
        return 'chat'
    return 'chat'


def _classify_work_category(prompt: str) -> str:
    """将用户诉求映射为反馈中心类型（bug / suggestion / other），供跟踪单归类。

    直接复用意图判定结果：缺陷 -> bug，建议 -> suggestion，其余 -> other。
    """
    intent = _classify_intent(prompt)
    return {'defect': 'bug', 'suggestion': 'suggestion'}.get(intent, 'other')


# 标题提炼时去除的开头命令/填充词（这些不属于「问题概括」本身）。
_TITLE_LEAD_FILLERS = (
    '你来解决这个问题', '你来解决', '你来处理', '排查一下', '排查', '修复一下', '修复',
    '优化一下', '优化', '改一下', '改下', '看一下', '看看', '继续', '帮我', '请',
    '现在', '稍后', '我怀疑', '你说', '刚才', '当前', '最近', '这个', '那个',
)


def _make_ticket_title(prompt: str) -> str:
    """从用户诉求中结构化提炼一句话「概括」作为反馈单标题（不依赖模型输出）。

    反馈单标题应是对问题的概括，而非原始诉求的整段照抄。本函数取首行首句、
    剥离开头命令/填充词、截断到合适长度，得到一个干净的问题概括标题。
    """
    if not prompt or not prompt.strip():
        return 'AI 处理任务'
    # 取首行，并按首个断句符截断到更紧凑的概括
    line = prompt.strip().split('\n', 1)[0].strip()
    for sep in ('。', '；', ';', '？', '?', '！', '!'):
        if sep in line:
            line = line.split(sep, 1)[0].strip()
            break
    # 去掉开头的命令/填充词，保留问题本质
    for f in _TITLE_LEAD_FILLERS:
        if line.startswith(f):
            line = line[len(f):].strip()
            break
    # 剥离开头残留的冒号/标点（如「你来解决这个问题：...」）
    line = line.lstrip('：: ').strip()
    line = line.strip(' ，,。.：:')
    if not line:
        line = prompt.strip().split('\n', 1)[0].strip()
    if len(line) > 40:
        line = line[:40] + '…'
    return line or 'AI 处理任务'


def _maybe_create_tracking_ticket(task_id, prompt, owner_id, reply, filed_id, head_before,
                                   git_clean=True, intent=None):
    """结构性保证：当 AI 本回合实际改动代码（产生新提交，HEAD 变化）且未通过
    feedback-request 建单时，于反馈中心创建一张「跟踪单」（状态 pending_verification），
    记录处理动作与提交哈希，供管理员验证后手动关闭。返回 (reply, track_id)。

    该逻辑不依赖模型是否「主动」输出反馈块，而是由仓库状态客观判定，从而在结构上
    保证「AI 处理新特性或问题」必有反馈中心单跟踪——即使模型漏提反馈块也不会漏单。
    git_clean 标记本回合结束后仓库是否干净（见 _verify_and_report_clean），一并写入
    跟踪单 extra，便于管理员验证时核对。
    """
    repo = _project_root()
    head_after = _git_rev_head(repo)
    # 仅在确有新提交（HEAD 变化）时视为「处理了一个新特性/问题」
    if not head_after or head_after == head_before:
        return reply, None
    # 本回合已通过反馈块建单，则不再重复建跟踪单
    if filed_id:
        return reply, None
    # 标题=对问题的概括（结构性提炼，不照抄原始诉求）；
    # 内容=问题描述（用户诉求原文）；
    # 留言（comment）= AI 实际做了什么/修复内容（来自本次回复）。
    title = _make_ticket_title(prompt)
    content = (prompt or '').strip() or '(无问题描述)'
    # 处理说明：以「自动助手」身份写入首条留言，承载 AI 的修复/处理动作。
    # 去掉末尾追加的「已创建跟踪单」提示，避免留言里出现自引用。
    action_note = ('\n\n📋 已创建处理跟踪单' in (reply or ''))
    comment_src = (reply or '').strip()
    if action_note:
        comment_src = comment_src.split('\n\n📋 已创建处理跟踪单')[0].strip()
    if len(comment_src) > 4000:
        comment_src = comment_src[:4000] + '…（已截断）'
    # 反馈中心类型复用意图判定：缺陷 -> bug，建议 -> suggestion，其余 -> other。
    ftype = {'defect': 'bug', 'suggestion': 'suggestion'}.get(intent, _classify_work_category(prompt))
    extra = {'git_commit': head_after, 'task_id': task_id,
             'owner_id': owner_id, 'track': True, 'git_clean': git_clean}
    track_id = _file_feedback(
        ftype, title, content,
        extra=extra, status='pending_verification', comment=comment_src)
    if track_id:
        note = '\n\n📋 已创建处理跟踪单：#%s（状态：待验证，可在反馈中心查看）' % track_id
        reply = (reply or '') + note
    else:
        # file_feedback 已对「主服务暂不可达」做本地 spool 兜底，待其恢复后自动补建；
        # 此处仅做透明提示，避免用户误以为处理丢失。
        reply = (reply or '') + '\n\n（⚠️ 处理已完成，已尝试在反馈中心建立跟踪单；'
        '若主服务暂不可达，将自动重试建单，稍后可在反馈中心查看。）'
    return reply, track_id


# 对话系统约束：本助手具备真实执行能力，要求直接动手而非只描述。
_SYSTEM_PROMPT = (
    '你是一个嵌入在媒体库管理后台里的 AI 助手，拥有读写文件、运行命令的真实能力。\n'
    '当用户布置具体任务（如修改代码、创建/删除文件、执行命令等）时，请直接动手完成，'
    '不要只罗列步骤或描述做法；完成后用简体中文简要说明你做了什么。\n'
    '完成后必须保持 git 仓库干净：改动要提交（提交消息用文件方式写 UTF-8 中文，'
    '保持原有提交身份，不要改成「自动助手」），临时脚本/截图/中间产物必须删除，'
    '不得遗留未提交文件。\n'
    '若只是闲聊或提问，则正常简洁回答即可。\n'
    '\n'
    '【提交反馈】当用户的消息是在向本产品提交一条新的反馈（例如报告一个 bug、或提出一个'
    '建议 / 功能诉求）时：\n'
    '- 不要把它当作「需要你去修复或实现的任务」，也不要只描述做法；\n'
    '- 把反馈整理为简洁的 title 与 content，并在你回复的【最末尾】追加一个如下格式的围栏代码块：\n'
    '  ```feedback-request\n'
    '  {"type":"bug 或 suggestion","title":"一句话标题","content":"反馈的详细描述"}\n'
    '  ```\n'
    '- 在你的正文里用占位符 #(待分配) 表示反馈单号，并告知用户已提交、可在反馈中心查看；'
    '例如：「已为你提交反馈单 #(待分配)（类型：bug），我们会跟进处理。」\n'
    '- 若用户只是普通提问、闲聊，或让你执行某项任务，则按正常规则处理，不要输出 feedback-request 块。\n'
    '- 若用户引用了某个已有反馈单（形如 #202608120001），正常与其讨论该问题即可，该单号可被点击跳转。\n'
    '\n'
    '【引用资源库资源】当你的回复涉及本媒体库里的具体资源（视频 / 图集 / 帖子 / 文本），'
    '请用 Markdown 链接形式引用，用户点击即可跳转到该资源详情页：\n'
    '  [资源显示名](dbox://resource/<类型>/<标识>)\n'
    '<类型> 为 video / gallery / post / text 之一；<标识> 优先用资源的真实标识——'
    '视频/图集用其 hash（64 位十六进制字符串，videos/galleries 表的 hash 列），帖子/文本用整数 id（posts/texts 表的 id 列）。'
    '若你只知道资源标题，也可把 <标识> 写成标题关键字，系统会按标题模糊匹配解析。\n'
    '要在库里查找资源的真实标识，可用 Bash 工具直接查询媒体库数据库（Python 内置 sqlite3，无需额外依赖）。\n'
    '【重要】你「能看到的资源列表必须与资源管理器一致」：只能引用归属「已激活资源库」的资源，'
    '不得暴露已停用（is_active=0）资源库里的内容。因此查询必须 JOIN 已激活库并排除隐藏/已删除资源，例如：\n'
    '  python -c "import sqlite3,os; p=os.path.join(os.environ.get(\'DBOX_DATA_DIR\',\'data\'),\'databases\',\'dbox.db\'); c=sqlite3.connect(p); [print(r) for r in c.execute(\"SELECT v.hash, v.title FROM videos v JOIN resource_index ri ON v.resource_index_id=ri.id JOIN resource_libraries rl ON ri.library_id=rl.id WHERE rl.is_active=1 AND ri.hidden=0 AND v.in_trash=0 AND v.title LIKE \'%关键字%\' LIMIT 5\")]"\n'
    '（图集表 galleries 同构，把 v 换成 g、v.resource_index_id 换成 g.resource_index_id 即可；'
    '帖子表 posts 用 p.library_id 关联 resource_libraries 且 p.in_trash=0，文本表 texts 经 resource_index 关联；'
    '所有查询都务必带 rl.is_active=1 这一条件。）\n'
    '仅在确实引用到某个具体资源时才使用此链接；闲聊或泛泛而谈时不要编造引用；'
    '若某资源归属的库已停用，不要引用它。'
)


# 解析 AI 回复中的 feedback-request 围栏块（AI 用其对反馈中心提单，后端执行建单并回填单号）。
# 容忍围栏内可选的空白/换行差异，降低模型格式偏差导致漏单的概率。
_FB_RE = re.compile(r'```\s*feedback-request\s*\n?(.*?)```', re.DOTALL)


class AIChatManager:
    # 任务状态
    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_CANCELLED = 'cancelled'

    def __init__(self):
        self._db = None
        self._db_path = None
        self._lock = threading.RLock()
        self._queue = queue.Queue()          # FIFO：仅存待执行的 task_id
        self._worker = None
        self._procs = {}                      # task_id -> subprocess.Popen（用于取消）
        self._cancel = {}                    # task_id -> True（取消标记）
        self._skip = set()                   # 已在排队但被用户删除的 task_id
        self._subscribers = {}               # task_id -> [queue.Queue, ...]（SSE 订阅者）
        self._buffers = {}                    # task_id -> [token, ...]（运行期已产出的 token，供重连续接）
        self._phase_log = {}                  # task_id -> [phase dict, ...]（运行期各阶段的状态日志，
                                             #   phase dict = {index,label,kind,state,conclusion,body}，
                                             #   作为 SSE 重连与 2s 轮询重建「每阶段一个气泡」时间线的唯一可信源，
                                             #   根治「早期阶段在 SSE 连上前已发射而丢失」的问题）
        self._cur_phase = {}                  # task_id -> 当前阶段 index（token 流式填充归属该阶段气泡）
        self._initialized = False
        # 统一任务表镜像（轻量，仅状态展示）
        self._ut = None

    # ---------- 初始化 ----------
    def init(self, data_dir):
        if self._initialized and self._db_path:
            return
        os.makedirs(data_dir, exist_ok=True)
        self._db_path = os.path.join(data_dir, 'ai_chat.db')
        self._db = sqlite3.connect(self._db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._init_db()
        # 启动 worker（幂等）
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker.start()
        # 启动时把残留的 running/pending 任务复位，避免死任务卡住队列
        self._recover_stale_tasks()
        # 启动反馈建单 spool 的兜底重放：主服务若此前离线，积压的「AI 处理跟踪单 /
        # 用户反馈单」在此立即补建一次，并由周期任务持续重试，直到主服务恢复。
        self._start_feedback_spool_flusher()
        # 尝试挂接统一任务管理器（失败不影响对话功能）
        try:
            from shared.unified_tasks import init_task_manager as _init_tm
            _init_tm(data_dir)
            self._ut = True
        except Exception:
            self._ut = None
        self._initialized = True

    def _init_db(self):
        with self._lock:
            self._db.execute('''CREATE TABLE IF NOT EXISTS ai_tasks (
                task_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                prompt TEXT NOT NULL,
                reply TEXT,
                error TEXT,
                owner_id INTEGER,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )''')
            # 分阶段气泡：将每个阶段（标签 + 结论/正文）以 JSON 存储，
            # 使历史回看也能逐阶段还原为独立气泡，而非仅剩模型的一段最终文本。
            try:
                self._db.execute('ALTER TABLE ai_tasks ADD COLUMN phases TEXT')
            except Exception:
                pass
            self._db.execute('CREATE INDEX IF NOT EXISTS idx_ai_tasks_status ON ai_tasks(status)')
            self._db.execute('CREATE INDEX IF NOT EXISTS idx_ai_tasks_created ON ai_tasks(created_at)')
            self._db.commit()

    def _start_feedback_spool_flusher(self):
        """启动反馈建单 spool 的周期重放：确保主服务离线期间积压的跟踪单/反馈单
        在其恢复后被自动补建，从而在结构上保证「AI 处理必有反馈中心单跟踪」不丢单。"""
        try:
            from platform_client import flush_feedback_spool, _internal_secret
        except Exception:
            return

        # 启动即诊断内部密钥是否可发现：若读不到密钥，所有 /internal/* 调用都会 401，
        # 建单会全部静默失败。明确告警，避免再次出现「机制完全不生效却无提示」。
        if not _internal_secret():
            _logger.error(
                '反馈建单诊断：未找到主服务内部密钥（.dbox_internal_key）。'
                '拓展宿主与主服务数据目录不一致会导致 /internal/* 调用被 401 拒绝，'
                'AI 处理将无法正常在反馈中心建单。请检查 DBOX_DATA_DIR 或 '
                '%s\\Dbox\\data 下的密钥文件。' % (os.environ.get('ProgramData', 'C:\\ProgramData'))
            )

        def _loop():
            while True:
                try:
                    created = flush_feedback_spool()
                    if created:
                        _logger.info('反馈 spool 重放成功，补建单号：%s', ','.join(created))
                except Exception:
                    pass
                time.sleep(60)

        # 启动时先补建一次，再起守护线程周期重试
        try:
            created = flush_feedback_spool()
            if created:
                _logger.info('反馈 spool 启动补建成功，单号：%s', ','.join(created))
        except Exception:
            pass
        t = threading.Thread(target=_loop, daemon=True)
        t.start()

    def _recover_stale_tasks(self):
        """服务重启后，把未完成（pending/running）的任务复位为 cancelled/failed，防止 worker 卡死。"""
        now = time.time()
        with self._lock:
            rows = self._db.execute(
                'SELECT task_id, status FROM ai_tasks WHERE status IN (?, ?)',
                (self.STATUS_PENDING, self.STATUS_RUNNING)).fetchall()
            for r in rows:
            # pending 直接取消；running（进程已不在）标记为失败
                new = self.STATUS_CANCELLED if r['status'] == self.STATUS_PENDING else self.STATUS_FAILED
                self._db.execute(
                    'UPDATE ai_tasks SET status=?, error=?, updated_at=? WHERE task_id=?',
                    (new, '服务重启，任务已重置' if new == self.STATUS_CANCELLED else '服务重启，任务中断',
                     now, r['task_id']))
            self._db.commit()

    # ---------- 内部 DB 辅助 ----------
    def _now(self):
        return time.time()

    def _row_to_dict(self, row):
        if not row:
            return None
        d = dict(row)
        return d

    def get_task(self, task_id):
        with self._lock:
            row = self._db.execute('SELECT * FROM ai_tasks WHERE task_id=?', (task_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def _insert_task(self, task_id, prompt, owner_id, status):
        now = self._now()
        with self._lock:
            self._db.execute(
                'INSERT INTO ai_tasks (task_id, status, prompt, reply, error, owner_id, created_at, updated_at) '
                'VALUES (?,?,?,NULL,NULL,?,?,?)',
                (task_id, status, prompt, owner_id, now, now))
            self._db.commit()
        self._sync_to_unified(task_id, prompt, owner_id, status, now, now)

    def _set_status(self, task_id, status, reply=None, error=None, phases=None):
        now = self._now()
        with self._lock:
            if reply is not None:
                if phases is not None:
                    self._db.execute('UPDATE ai_tasks SET status=?, reply=?, phases=?, updated_at=? WHERE task_id=?',
                                     (status, reply, phases, now, task_id))
                else:
                    self._db.execute('UPDATE ai_tasks SET status=?, reply=?, updated_at=? WHERE task_id=?',
                                     (status, reply, now, task_id))
            elif error is not None:
                self._db.execute('UPDATE ai_tasks SET status=?, error=?, updated_at=? WHERE task_id=?',
                                 (status, error, now, task_id))
            else:
                self._db.execute('UPDATE ai_tasks SET status=?, updated_at=? WHERE task_id=?',
                                 (status, now, task_id))
            self._db.commit()
        self._sync_to_unified_by_id(task_id, status)

    # ---------- 统一任务表镜像（轻量，仅展示状态/标题） ----------
    def _sync_to_unified(self, task_id, prompt, owner_id, status, created_at, updated_at):
        if not self._ut:
            return
        try:
            from shared.unified_tasks import create_task
            title = (prompt or '').strip().replace('\n', ' ')
            if len(title) > 60:
                title = title[:60] + '…'
            title = title or 'AI 对话'
            create_task('ai:' + task_id, 'ai_chat', title, owner_id=owner_id,
                        status=status, created_at=created_at, updated_at=updated_at)
        except Exception:
            pass

    def _sync_to_unified_by_id(self, task_id, status):
        if not self._ut:
            return
        try:
            from shared.unified_tasks import update_task, get_task as ut_get
            ut_id = 'ai:' + task_id
            if ut_get(ut_id) is None:
                t = self.get_task(task_id)
                if t:
                    self._sync_to_unified(task_id, t['prompt'], t['owner_id'], status, t['created_at'], t['updated_at'])
                return
            update_task(ut_id, status=status)
        except Exception:
            pass

    def _remove_from_unified(self, task_id):
        if not self._ut:
            return
        try:
            from shared.unified_tasks import delete_task
            delete_task('ai:' + task_id, is_admin=True)
        except Exception:
            pass

    # ---------- 入队 ----------
    def enqueue(self, message, owner_id=None):
        """把一条用户消息作为任务入队，立即返回 task_id（不阻塞）。"""
        msg = (message or '').strip()
        if not msg:
            return None, 'message 必填'
        task_id = 'ai_' + uuid.uuid4().hex[:16]
        self._insert_task(task_id, msg, owner_id, self.STATUS_PENDING)
        self._queue.put(task_id)
        return task_id, None

    # ---------- worker ----------
    def _terminate(self, proc):
        """强制结束进程及其子进程树（Windows 用 taskkill /T，类 Unix 用 killpg）。"""
        if not proc:
            return
        pid = proc.pid
        try:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            else:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass

    def _worker_loop(self):
        while True:
            task_id = self._queue.get()
            if task_id is None:
                break
            with self._lock:
                if task_id in self._skip:
                    self._skip.discard(task_id)
                    self._set_status(task_id, self.STATUS_CANCELLED, error='已取消')
                    continue
            try:
                self._process(task_id)
            except Exception as e:
                self._set_status(task_id, self.STATUS_FAILED, error='处理异常: ' + str(e))
                self._emit(task_id, 'error', '处理异常: ' + str(e))

    def _context_turns(self, exclude_id=None, limit=20):
        """构建多轮上下文：取已完成且含回复的任务，按时间正序，最近 limit 轮。"""
        with self._lock:
            rows = self._db.execute(
                "SELECT prompt, reply FROM ai_tasks WHERE status=? AND reply IS NOT NULL "
                "AND reply != '' ORDER BY created_at ASC",
                (self.STATUS_COMPLETED,)).fetchall()
        turns = [(r['prompt'], r['reply']) for r in rows if r['prompt']]
        if exclude_id:
            # exclude 仅影响排序语义，这里简单保留全部（exclude 多属 pending/running，本就不会进上下文）
            pass
        if limit and len(turns) > limit:
            turns = turns[-limit:]
        return turns

    def _build_prompt(self, message, intent=None, phase=None, analysis=None):
        parts = [_SYSTEM_PROMPT]
        turns = self._context_turns()
        if turns:
            parts.append('以下是之前的对话记录，供你理解上下文：')
            for up, ar in turns:
                parts.append('用户：' + up)
                parts.append('助手：' + ar)
            parts.append('')
        parts.append('用户问题：' + message)
        # 注入宿主进程判定出的意图，帮助模型与「分阶段判断」的结论对齐（仅供参考）。
        if intent:
            label = _INTENT_LABELS.get(intent, intent)
            parts.append('（系统初步判定本条用户意图为：%s，供你参考）' % label)
        # 分阶段控制：宿主脚本驱动处理流程，每个阶段只让 AI 产出该阶段内容（即「给出分支」）。
        # 这样一条命令会被拆成「分析定位 -> 执行处理」等多个可见阶段，而非一次性抛出大段文本。
        if phase == 'analyze':
            parts.append('【本阶段任务：仅做分析与定位，不要修改任何文件】'
                         '请基于用户问题定位根因、列出涉及的代码文件、给出修复方案，'
                         '用简体中文条理清晰地说明。不要执行任何写操作。')
        elif phase == 'execute':
            if analysis:
                parts.append('【本阶段任务：执行修改】以下为上一阶段（分析定位）的结论，'
                             '请直接据此执行修改：\n' + analysis)
            parts.append('请执行修改（必要时创建/编辑文件、运行命令验证），完成后提交 git'
                         '（提交消息用文件方式写 UTF-8 中文、保持原有提交身份、清理临时脚本），'
                         '并用简体中文简要说明你做了什么。')
        elif phase == 'chat':
            parts.append('【本阶段任务：生成回复】用户为闲聊或普通提问，直接简洁回答即可。')
        return '\n'.join(parts)

    def _run_cli(self, prompt, task_id, max_turns):
        """运行一次 buddy CLI（一个处理阶段），实时把产出 token 推送给订阅者。

        返回 (reply, fell_back, err_text, returncode, cancelled)。脚本驱动的阶段状态机
        对每个需要智能的阶段分别调用本方法：分析定位阶段只读取、执行处理阶段才改代码，
        从而把一条用户命令拆成多个可见阶段，AI 在每个阶段只给出该阶段的内容（分支）。

        看门狗与子进程清理逻辑沿用原 _process 的单次调用实现，避免 worker 因 CLI 拉起
        子进程导致 stdout 管道不关闭而卡死。
        """
        buddy = _resolve_buddy_cli()
        if not buddy:
            return None, False, '未找到 CodeBuddy CLI', 1, False
        env = dict(os.environ)
        token = _load_codebuddy_token()
        if token:
            env[_ANTHROPIC_API_KEY_ENV] = token
        _home = _codebuddy_user_home()
        if _home and os.path.isdir(_home):
            env['USERPROFILE'] = _home
            env['HOME'] = _home
            env['APPDATA'] = os.path.join(_home, 'AppData', 'Roaming')
            env['LOCALAPPDATA'] = os.path.join(_home, 'AppData', 'Local')

        cmd = [
            buddy, '-p', '-y',
            '--permission-mode', 'bypassPermissions',
            '--allowedTools', 'Read,Edit,Write,Glob,Grep,Bash',
            '--max-turns', str(max_turns),
            '--add-dir', _project_root(),
            '--input-format', 'text',
        ]

        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, cwd=_project_root(), env=env,
                creationflags=(CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0),
            )
            with self._lock:
                self._procs[task_id] = proc

            def _watchdog():
                self._cancel[task_id] = True
                self._terminate(proc)
            watchdog = threading.Timer(_MAX_TASK_SECONDS, _watchdog)
            watchdog.daemon = True
            watchdog.start()

            try:
                proc.stdin.write(prompt.encode('utf-8'))
                proc.stdin.close()
            except Exception:
                pass

            full = []
            for raw_line in proc.stdout:
                if self._cancel.get(task_id):
                    self._terminate(proc)
                    break
                try:
                    line = raw_line.decode('utf-8')
                except Exception:
                    try:
                        line = raw_line.decode('gbk')
                    except Exception:
                        line = raw_line.decode('utf-8', errors='replace')
                if not line:
                    continue
                piece = line.rstrip('\n')
                full.append(piece)
                self._append_token(task_id, piece)
            proc.stdout.close()
            err_text = ''
            try:
                err_text = proc.stderr.read().decode('utf-8', errors='replace') or ''
            except Exception:
                pass
            proc.stderr.close()
            try:
                proc.wait(timeout=30)
            except Exception:
                pass
            finally:
                watchdog.cancel()
                self._terminate(proc)

            cancelled = bool(self._cancel.get(task_id))
            reply, fell_back = _build_reply(full, err_text, proc.returncode)
            return reply, fell_back, err_text, proc.returncode, cancelled
        except Exception as e:
            return None, False, '调用失败: ' + str(e), 1, False

    def _process(self, task_id):
        """脚本驱动的阶段状态机：每条用户命令被拆成多个可见「阶段气泡」，每个阶段由
        宿主进程显式发射 phase 事件（开始 -> 结束，结束带一句 conclusion）；需要智能的
        阶段由宿主分阶段调用 CLI（先「分析定位」、再「执行处理」），AI 在每个阶段只产出
        该阶段内容（即给出分支）。

        每个阶段 = 聊天窗口里一个独立气泡：
          1. 分析用户意图（建议 / 缺陷 / 继续 / 闲聊）—— 宿主确定性判定，结论一句话气泡
          2. 核查运行环境（git 仓库状态）—— 宿主，结论一句话气泡
          3. AI 分析定位问题 —— CLI（只读），气泡承载分析正文
          4. AI 执行处理（修改与验证）—— CLI，气泡承载执行说明
          5. 收尾核查（git 仓库干净度）—— 宿主，结论一句话气泡
          6. 创建处理跟踪单（待验证）—— 宿主（确有新提交时），结论一句话气泡
        闲聊/普通提问：仅阶段 1 + 单个「生成回复」气泡，不触发 git 核查与建单。
        """
        task = self.get_task(task_id)
        if not task:
            return
        with self._lock:
            self._buffers[task_id] = []
            self._phase_log[task_id] = []
            self._cur_phase.pop(task_id, None)
            self._set_status(task_id, self.STATUS_RUNNING)
            self._emit(task_id, 'status', 'running')

        # 阶段序号由闭包维护，确保自增且与前端按 index 对齐重建气泡顺序。
        _pi = [0]

        def begin(label, kind):
            idx = _pi[0]
            _pi[0] += 1
            self._begin_phase(task_id, idx, label, kind)
            return idx

        def end(idx, conclusion='', body=None):
            self._end_phase(task_id, idx, conclusion, body)

        def _cli(label, prompt, max_turns):
            """运行一次 CLI 阶段：自行打开一个 phase（running），正文随 token 走
            phase_chunk 流式填充该阶段气泡，失败/取消时直接收尾并返回取消标记。
            返回 (phase_index, reply, cancelled)。"""
            idx = begin(label, 'cli')
            reply, _, err, rc, cancelled = self._run_cli(prompt, task_id, max_turns)
            if cancelled:
                self._set_status(task_id, self.STATUS_CANCELLED, error='已取消')
                self._emit(task_id, 'error', '任务已取消')
                self._finish_emit(task_id, 'cancelled')
                return idx, None, True
            if _is_auth_error(err or ''):
                self._set_status(task_id, self.STATUS_FAILED, error='CodeBuddy 认证失败')
                self._emit(task_id, 'error', 'CodeBuddy 认证失败，请在凭证保险库配置 codebuddy token 或执行 codebuddy /login')
                self._finish_emit(task_id, 'failed')
                return idx, None, True
            if rc not in (0, None):
                self._set_status(task_id, self.STATUS_FAILED, error='AI 执行出错（退出码 %s）' % rc)
                self._emit(task_id, 'error', 'AI 执行出错（退出码 %s）' % rc)
                self._finish_emit(task_id, 'failed')
                return idx, None, True
            return idx, reply, False

        # ---- 阶段 1：分析用户意图（建议 / 缺陷 / 继续 / 闲聊）----
        # 宿主基于关键词确定性判定（不依赖模型输出），结论作为首个阶段气泡直接呈现，
        # 满足「判断过程中显示当前阶段、判断成功后回复本阶段结论」。
        intent = _classify_intent(task['prompt'])
        is_task = intent in ('defect', 'suggestion', 'continue')
        idx = begin('分析用户意图（建议 / 缺陷 / 继续 / 闲聊）', 'host')
        end(idx, conclusion='分析用户意图：这是一条【%s】反馈' % _INTENT_LABELS.get(intent, '其他'))

        if not is_task:
            # 闲聊/普通提问：单个 AI 回复气泡即可，不做 git 核查与建单。
            ci, reply, cancelled = _cli('生成回复',
                self._build_prompt(task['prompt'], intent=intent, phase='chat'), 30)
            if cancelled:
                return
            if not reply:
                reply = '（任务已执行完成，无文本输出）'
            reply, _ = _maybe_file_feedback(reply)
            end(ci, body=reply)
            self._finish_completed(task_id)
            return

        # ---- 阶段 2：核查运行环境（git 仓库状态）----
        repo = _project_root()
        head_before = _git_rev_head(repo)
        baseline_dirty = _git_dirty_files(repo)
        idx = begin('核查运行环境（git 仓库状态）', 'host')
        if baseline_dirty is None:
            s_pre = '做事前检查：仓库非 git 或状态不可判定，跳过干净度核查'
        elif not baseline_dirty:
            s_pre = '做事前检查：git 仓库干净，无未提交改动'
        else:
            s_pre = '做事前检查：仓库已存在 %d 项未提交改动（不归因于本次任务）' % len(baseline_dirty)
        end(idx, conclusion=s_pre)

        # ---- 阶段 3：AI 分析定位问题（只读，不修改文件）----
        ci, reply, cancelled = _cli('AI 分析定位问题',
            self._build_prompt(task['prompt'], intent=intent, phase='analyze'), 40)
        if cancelled:
            return
        analysis = reply or '（分析阶段无文本输出）'
        end(ci, body=analysis, conclusion='AI 已完成分析定位')

        # ---- 阶段 4：AI 执行处理（修改与验证）----
        ci, reply, cancelled = _cli('AI 执行处理（修改与验证）',
            self._build_prompt(task['prompt'], intent=intent, phase='execute', analysis=analysis), 50)
        if cancelled:
            return
        if not reply:
            reply = '（任务已执行完成，无文本输出）'
        # 若 AI 在回复中携带 feedback-request 块（罕见，任务中误判为提交反馈），则建单、
        # 回填真实单号并剥离该块，再存库与下发。
        reply, filed_id = _maybe_file_feedback(reply)
        end(ci, body=reply, conclusion='AI 已完成执行处理')

        # ---- 阶段 5：收尾核查（git 仓库干净度）----
        idx = begin('收尾核查（git 仓库状态）', 'host')
        reply, git_clean = _verify_and_report_clean(repo, baseline_dirty, head_before, reply)
        s_post = ('做事后检查：git 仓库已保持干净'
                  if git_clean else
                  '做事后检查：git 仓库未完全干净，存在遗留未提交改动，请人工处理（见上文）')
        end(idx, conclusion=s_post)

        # ---- 阶段 6：创建处理跟踪单（待验证，确有新提交时）----
        head_after = _git_rev_head(repo)
        if head_after and head_after != head_before and not filed_id:
            idx = begin('创建处理跟踪单（待验证）', 'host')
            reply, track_id = _maybe_create_tracking_ticket(
                task_id, task['prompt'], task.get('owner_id'),
                reply, filed_id, head_before, git_clean=git_clean, intent=intent)
            if track_id:
                s_ticket = None  # 跟踪单提示已由 _maybe_create_tracking_ticket 追加进 reply
            elif filed_id:
                s_ticket = '已在反馈中心提交反馈单（本回合用户反馈路径）'
            else:
                s_ticket = '（处理已完成，已尝试在反馈中心建立跟踪单；若主服务暂不可达将自动重试建单）'
            end(idx, conclusion=s_ticket)

        self._finish_completed(task_id)

    def _finish_completed(self, task_id):
        """把当前阶段日志组装为分阶段回复并标记完成、下发 done、结束 SSE。"""
        with self._lock:
            phases = [dict(p) for p in self._phase_log.get(task_id, [])]
        # 存库的最终回复：各阶段「结论优先、正文兜底」拼接，保证无 phases 客户端也能单气泡回看。
        final_reply = '\n\n'.join(
            (p.get('conclusion') or p.get('body') or '').strip()
            for p in phases if (p.get('conclusion') or p.get('body')))
        self._set_status(task_id, self.STATUS_COMPLETED, reply=final_reply,
                         phases=json.dumps(phases, ensure_ascii=False))
        self._emit(task_id, 'done', final_reply)
        self._finish_emit(task_id, 'completed')

    # ---------- SSE 发布订阅 ----------
    def _append_token(self, task_id, piece):
        """追加一个 token：写入缓冲区，并（若存在当前阶段）归属到该阶段气泡的正文，
        同时推送给所有订阅者（token 与 phase_chunk 各一份，前端以前者做保底、以后者填充气泡）。"""
        with self._lock:
            self._buffers.setdefault(task_id, []).append(piece)
            idx = self._cur_phase.get(task_id)
            if idx is not None:
                for p in self._phase_log.get(task_id, []):
                    if p['index'] == idx:
                        p['body'] += piece
                        break
            subs = list(self._subscribers.get(task_id, []))
        for q in subs:
            try:
                q.put(('token', piece))
                if idx is not None:
                    q.put(('phase_chunk',
                           json.dumps({'index': idx, 'text': piece}, ensure_ascii=False)))
            except Exception:
                pass

    def _emit(self, task_id, etype, data):
        with self._lock:
            subs = list(self._subscribers.get(task_id, []))
        for q in subs:
            try:
                q.put((etype, data))
            except Exception:
                pass

    # ---- 阶段气泡事件（结构层面，不依赖提示词）----
    # 每个处理阶段 = 聊天窗口里的一个独立气泡。阶段开始发射 phase（state=running），
    # CLI 阶段的正文随 token 走 phase_chunk 流式填充，阶段结束发射 phase（state=done，
    # 含 conclusion 一句结论）。这样「一条命令」会被拆成多个可见气泡，且每阶段结束都
    # 回一句结论，而非挤在一个气泡里加进度条。
    def _begin_phase(self, task_id, index, label, kind):
        phase = {'index': index, 'label': label, 'kind': kind,
                 'state': 'running', 'conclusion': '', 'body': ''}
        with self._lock:
            self._phase_log.setdefault(task_id, []).append(phase)
            self._cur_phase[task_id] = index
        self._emit(task_id, 'phase',
                   json.dumps({'index': index, 'label': label, 'kind': kind,
                               'state': 'running'}, ensure_ascii=False))

    def _end_phase(self, task_id, index, conclusion='', body=None):
        label = ''
        with self._lock:
            for p in self._phase_log.get(task_id, []):
                if p['index'] == index:
                    p['state'] = 'done'
                    label = p.get('label', '')
                    if conclusion is not None:
                        p['conclusion'] = conclusion
                    if body is not None:
                        p['body'] = body
                    break
            self._cur_phase.pop(task_id, None)
        payload = {'index': index, 'label': label, 'state': 'done',
                   'conclusion': conclusion or ''}
        if body is not None:
            payload['body'] = body
        self._emit(task_id, 'phase', json.dumps(payload, ensure_ascii=False))

    def _finish_emit(self, task_id, _status):
        """通知所有订阅者任务结束（推送终止哨兵）并清理缓冲区。"""
        with self._lock:
            subs = list(self._subscribers.get(task_id, []))
            self._subscribers.pop(task_id, None)
            self._buffers.pop(task_id, None)
            self._phase_log.pop(task_id, None)
            self._cur_phase.pop(task_id, None)
            self._procs.pop(task_id, None)
        for q in subs:
            try:
                q.put(('__end__', ''))
            except Exception:
                pass

    def subscribe(self, task_id):
        """返回一个生成 SSE 文本块的生成器，按 task_id 订阅该任务的流式输出。

        - 已完成/失败/取消：立即回放最终结果并结束（支持刷新重连后直接拿到完整回复）；
        - 排队中（pending）：先下发 queued 事件，再等待被 worker 取出后推送 running 与 token；
        - 正在处理（running）：先回放已产出的阶段气泡日志（self._phase_log），再续接后续实时事件。
        """
        task = self.get_task(task_id)
        if task is None:
            yield _sse_block('error', '任务不存在')
            return

        status = task['status']
        if status == self.STATUS_COMPLETED:
            yield _sse_block('done', task['reply'] or '')
            return
        if status == self.STATUS_FAILED:
            yield _sse_block('error', task['error'] or '执行失败')
            return
        if status == self.STATUS_CANCELLED:
            yield _sse_block('error', '任务已取消')
            return

        # pending 或 running：注册订阅者
        q = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(task_id, []).append(q)
            phases = [dict(p) for p in self._phase_log.get(task_id, [])]
            cur = self._db.execute(
                'SELECT status FROM ai_tasks WHERE task_id=?', (task_id,)).fetchone()
            cur_status = cur['status'] if cur else status

        if cur_status == self.STATUS_PENDING:
            yield _sse_block('queued', '')

        # 先重放持久化缓冲的「阶段气泡」日志：每个阶段按当前状态（running/done）
        # 整体下发，前端据 index 重建为独立气泡。这些阶段可能在 SSE 连上前就已发射，
        # 此前只重放 token 导致早期阶段被静默丢弃，表现为聊天窗口长期只显示「正在处理」。
        # 以 self._phase_log 为唯一可信源重建，根治该问题。
        for p in phases:
            payload = {'index': p['index'], 'label': p.get('label', ''),
                       'kind': p.get('kind', ''), 'state': p.get('state', 'done'),
                       'conclusion': p.get('conclusion', '')}
            if p.get('body'):
                payload['body'] = p['body']
            yield _sse_block('phase', json.dumps(payload, ensure_ascii=False))

        idle = 0
        while True:
            try:
                item = q.get(timeout=15)
            except queue.Empty:
                # 心跳保活，避免代理断开长连接；同时设上限，防止 worker 异常卡死导致连接永生
                idle += 1
                if idle > 40:  # 约 10 分钟无进展则主动断开
                    return
                yield ': keepalive\n\n'
                continue
            etype, data = item
            if etype == '__end__':
                return
            if etype == 'phase':
                yield _sse_block('phase', data)
            elif etype == 'phase_chunk':
                yield _sse_block('phase_chunk', data)
            elif etype == 'token':
                yield _sse_block('token', data)
            elif etype == 'status':
                yield _sse_block('status', data)
            elif etype == 'queued':
                yield _sse_block('queued', '')
            elif etype == 'done':
                yield _sse_block('done', data)
                return
            elif etype == 'error':
                yield _sse_block('error', data)
                return

    # ---------- 列表 / 历史 ----------
    def list_tasks(self, history_limit=10):
        """返回 pending（FIFO 正序）+ active（running 的任务，含当前缓冲）+ 最近 history。"""
        with self._lock:
            pending_rows = self._db.execute(
                'SELECT task_id, prompt, status, created_at FROM ai_tasks '
                'WHERE status=? ORDER BY created_at ASC', (self.STATUS_PENDING,)).fetchall()
            active_rows = self._db.execute(
                'SELECT task_id, prompt, status, created_at FROM ai_tasks '
                'WHERE status=? ORDER BY created_at DESC LIMIT 1', (self.STATUS_RUNNING,)).fetchall()
            hist_rows = self._db.execute(
                "SELECT task_id, prompt, reply, status, error, phases, created_at FROM ai_tasks "
                "WHERE status IN (?, ?, ?) ORDER BY created_at DESC LIMIT ?",
                (self.STATUS_COMPLETED, self.STATUS_FAILED, self.STATUS_CANCELLED,
                 history_limit + 1)).fetchall()

        pending = [{'id': r['task_id'], 'prompt': r['prompt'], 'status': r['status'],
                    'created_at': r['created_at']} for r in pending_rows]

        active = None
        if active_rows:
            r = active_rows[0]
            with self._lock:
                buf = ''.join(self._buffers.get(r['task_id'], []))
                phases = [dict(p) for p in self._phase_log.get(r['task_id'], [])]
            active = {'id': r['task_id'], 'prompt': r['prompt'], 'status': r['status'],
                      'created_at': r['created_at'], 'stream': buf, 'phases': phases}

        has_more = len(hist_rows) > history_limit
        hist_rows = hist_rows[:history_limit]
        history = [{'id': r['task_id'], 'prompt': r['prompt'], 'reply': r['reply'],
                    'status': r['status'], 'error': r['error'],
                    'phases': _parse_phases(r['phases']),
                    'created_at': r['created_at']} for r in hist_rows]

        return {'pending': pending, 'active': active, 'history': history, 'has_more': has_more}

    def history_page(self, cursor=None, limit=10):
        """分页获取更早的历史（按 created_at 倒序）。cursor 为上一页最后一条的 created_at。"""
        with self._lock:
            if cursor is not None:
                rows = self._db.execute(
                    "SELECT task_id, prompt, reply, status, error, phases, created_at FROM ai_tasks "
                    "WHERE status IN (?, ?, ?) AND created_at < ? ORDER BY created_at DESC LIMIT ?",
                    (self.STATUS_COMPLETED, self.STATUS_FAILED, self.STATUS_CANCELLED,
                     float(cursor), limit + 1)).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT task_id, prompt, reply, status, error, phases, created_at FROM ai_tasks "
                    "WHERE status IN (?, ?, ?) ORDER BY created_at DESC LIMIT ?",
                    (self.STATUS_COMPLETED, self.STATUS_FAILED, self.STATUS_CANCELLED,
                     limit + 1)).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [{'id': r['task_id'], 'prompt': r['prompt'], 'reply': r['reply'],
                  'status': r['status'], 'error': r['error'], 'created_at': r['created_at']}
                 for r in rows]
        return {'history': items, 'has_more': has_more,
                'next_cursor': items[-1]['created_at'] if (items and has_more) else None}

    # ---------- 删除 / 取消 ----------
    def delete_task(self, task_id):
        """删除/取消一个 AI 任务。

        - pending：直接从队列移除并标记 cancelled（取消排队）；
        - running：置取消标记并 kill 子进程；
        - 终态：直接从历史中删除。

        返回 True 成功 / False 不存在 / None 已取消中。
        """
        task = self.get_task(task_id)
        if not task:
            return False
        status = task['status']
        if status == self.STATUS_PENDING:
            with self._lock:
                self._skip.add(task_id)
            self._set_status(task_id, self.STATUS_CANCELLED, error='已取消')
            self._emit(task_id, 'error', '任务已取消')
            self._finish_emit(task_id, 'cancelled')
            self._remove_from_unified(task_id)
            return True
        if status == self.STATUS_RUNNING:
            with self._lock:
                self._cancel[task_id] = True
                proc = self._procs.get(task_id)
                if proc and proc.poll() is None:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            self._emit(task_id, 'error', '任务已取消')
            # worker 会在进程退出后将状态置为 cancelled 并结束 SSE
            return True
        # 终态：直接删除记录
        with self._lock:
            self._db.execute('DELETE FROM ai_tasks WHERE task_id=?', (task_id,))
            self._db.commit()
        self._remove_from_unified(task_id)
        return True

    def clear(self):
        """清空全部对话（含排队与历史），重置上下文。"""
        with self._lock:
            # 取消进行中的任务
            rows = self._db.execute(
                'SELECT task_id, status FROM ai_tasks WHERE status IN (?, ?)',
                (self.STATUS_PENDING, self.STATUS_RUNNING)).fetchall()
            for r in rows:
                if r['status'] == self.STATUS_PENDING:
                    self._skip.add(r['task_id'])
                else:
                    self._cancel[r['task_id']] = True
                    proc = self._procs.get(r['task_id'])
                    if proc and proc.poll() is None:
                        try:
                            proc.kill()
                        except Exception:
                            pass
            self._db.execute('DELETE FROM ai_tasks')
            self._db.commit()
            self._subscribers.clear()
            self._buffers.clear()
        # 同步清理统一任务表中的 ai_chat 镜像
        if self._ut:
            try:
                from shared.unified_tasks import get_tasks as ut_get_all
                for t in ut_get_all(role='admin', limit=200):
                    if (t.get('kind') == 'ai_chat') or str(t.get('task_id', '')).startswith('ai:'):
                        self._remove_from_unified(t['task_id'].split(':', 1)[-1] if str(t['task_id']).startswith('ai:') else t['task_id'])
            except Exception:
                pass
        return True


# 单例
ai_mgr = AIChatManager()
