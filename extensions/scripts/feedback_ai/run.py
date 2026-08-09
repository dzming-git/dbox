#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反馈中心 AI 自动处理脚本（作为通用轮询调度器的一个 poll 脚本运行）

运行模型：
  - 由 scripts/poll_scheduler.py 按 manifest 的 interval 周期调用（每次一个独立进程）。
  - 每次被调用 = 跑一轮：重置超时 processing 任务 -> 扫描 pending -> 处理一条 -> 退出。
  - 所有任务状态持久化在 feedback_issues.feedback_extra.ai_task（JSON），天然自愈：
    调度器崩溃/脚本异常都不丢任务，下一轮继续。

stdin 约定（调度器传入）：{"trigger":"poll","context":{}}
也支持命令行子命令手动调试：enqueue / status / retry / cancel / process / run

AI 调用：
  - 通过 CodeBuddy CLI（buddycn）消费标准化 JSON 契约，超时 AI_TIMEOUT。
  - 方向 B：CLI 以 -y --add-dir 运行，AI 拥有本项目源码（src/extensions/scripts/configs）
    的读写权限，会直接修改文件真正修复反馈，而非仅给建议。
  - 契约：{"verdict":"resolved|needs_decision|blocked","reply":str,"analysis":str,
    "changes":[文件路径],"decision_needed":str|null}
  - 防假结案：verdict=resolved 时脚本会校验工作区是否真有源码改动（排除 data/.git/venv），
    若无实际改动则降级为 needs_decision，避免「声称已修复实际没改」。
  - 解析失败重试 max_retries 次，仍失败则退回 pending_verification 并附错误说明。

自动回复一律以「自动助手」身份（role=4 FEEDBACK_BOT）写入，符合反馈中心规则。
"""
import os
import sys
import json
import time
import argparse
import subprocess
import tempfile
from datetime import datetime

# 路径：把 scripts/ 与 src/web/backend/ 加入 sys.path，复用 feedback_list 与 feedback_db
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))  # 项目根
sys.path.insert(0, os.path.join(_PROJECT_ROOT, 'scripts'))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, 'src', 'web', 'backend'))

# 注意：必须用 feedback_db 的运行时目录解析（get_runtime_dir 指向 .../data），
# 不能用 feedback_list.find_runtime_dir()——后者返回项目根，会令 load_issues
# 回退读取旧的 data/issues.json 而非真实的 data/databases/feedback.db，
# 导致 AI 脚本永远看不到新建的真实反馈（表现为新反馈迟迟不进入处理中）。
from feedback_db import get_runtime_dir as find_runtime_dir  # noqa: E402
from feedback_list import load_issues as _load_issues_raw  # noqa: E402


def load_issues(runtime_dir: str):
    return _load_issues_raw(runtime_dir)


from feedback_db import (  # noqa: E402
    init_feedback_db,
    db_get_extra,
    db_update_extra,
    db_set_status,
    db_append_comment,
)

AUTO_AUTHOR = '自动助手'
AUTO_ROLE = 4  # UserRole.FEEDBACK_BOT

# 执行参数
AI_TIMEOUT = 600           # 单次 AI 调用超时（秒），方向 B 需改代码，较纯分析更耗时
MAX_RETRIES = 3            # 单条任务最大重试次数
PROCESSING_TIMEOUT = 600   # processing 心跳超时（秒），超时视为崩溃，重置 pending

# ai_task 状态机
TASK_PENDING = 'pending'
TASK_PROCESSING = 'processing'
TASK_DONE = 'done'
TASK_FAILED = 'failed'
TASK_SKIPPED = 'skipped'

ISSUE_OPEN = 'open'

VERDICT_RESOLVED = 'resolved'
VERDICT_NEEDS_DECISION = 'needs_decision'
VERDICT_BLOCKED = 'blocked'


# ============================ 工具 ============================
def _now_iso():
    return datetime.now().isoformat(timespec='seconds')


def _safe_json(raw):
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        return {}


def get_ai_task(issue_id: str) -> dict:
    return db_get_extra(issue_id).get('ai_task') or {}


def _save_ai_task(issue_id: str, task: dict):
    db_update_extra(issue_id, {'ai_task': task})


def enqueue(issue_id: str, force: bool = False) -> dict:
    init_feedback_db()
    existing = get_ai_task(issue_id)
    if existing.get('state') in (TASK_PENDING, TASK_PROCESSING, TASK_DONE) and not force:
        return existing
    task = {
        'state': TASK_PENDING,
        'retries': 0,
        'enqueued_at': _now_iso(),
        'started_at': None,
        'heartbeat_at': None,
        'finished_at': None,
        'last_error': None,
        'verdict': None,
    }
    _save_ai_task(issue_id, task)
    return task


# ============================ AI 调用 ============================
def _build_prompt(issue: dict) -> str:
    content = issue.get('content', '')
    title = issue.get('title', '')
    comments = issue.get('comments', [])
    history = ''
    if comments:
        lines = []
        for c in comments:
            author = c.get('author', '')
            ctime = c.get('created_at', '')
            ctext = c.get('content', '')
            lines.append(f'  [{ctime}] {author}: {ctext}')
        history = '\n'.join(lines)

    return f"""你是 Dplayer 反馈中心的「自动助手」，且具备修改代码的权限。请直接定位并修复以下用户反馈对应的源码问题（不要只给建议）。

【反馈标题】{title}
【反馈内容】
{content}

【历史留言】
{history or '（无）'}

工作目录为项目根（{_PROJECT_ROOT}）。你可以且应当直接编辑相关源码文件来修复该反馈。

★ 修改边界（务必遵守）：
- 允许修改：src/、scripts/、configs/ 下的源码与配置。
- 禁止修改：data/（运行时数据、数据库）、.git/、任何密钥/凭证文件、venv/、
  extensions/scripts/feedback_ai/（本自动处理脚本自身，不得自我修改）。
- 禁止执行 git commit / git push（代码改动留在工作区即可，由后续流程统一提交，避免错误身份提交）。
- 修改要聚焦、最小必要，改动后确保不破坏现有功能。

修改完成后，严格按以下 JSON 格式输出（只输出 JSON，不要使用 markdown 代码块包裹）：
{{
  "verdict": "resolved | needs_decision | blocked",
  "reply": "给用户的回复内容（中文，简洁专业，说明根因或处理方案；若为 bug 请描述根因，若建议请说明如何使用）",
  "analysis": "内部分析记录（根因定位、影响范围、修改了哪些文件、复现路径，供管理员参考，不展示给用户）",
  "changes": ["实际修改的文件相对路径列表，例如 src/web/main.py"],
  "decision_needed": "需要管理员决策的事项（仅当 verdict=needs_decision/blocked 时填写，否则为 null）"
}}

verdict 取值说明：
- resolved：已实际修改代码修复（changes 非空），将标记为待验证。
- needs_decision：需要人工决策（如涉及产品设计取舍，或你判断不应自动改代码），将标记待验证并附决策事项。
- blocked：被阻塞（如信息不足、需用户补充），将标记待验证并附阻塞原因。

注意：只有你确实修改了源码文件时，verdict 才能填 resolved；若仅给建议未改代码，请填 needs_decision。
"""


class AuthError(RuntimeError):
    """AI 工具（CodeBuddy CLI）未登录 / 认证失败，属工具故障而非反馈本身问题。"""


# 认证失败类返回的关键词（中英文都要覆盖，CLI 在不同环境下可能输出不同语言）
_AUTH_ERROR_HINTS = (
    'authentication required',
    'please use /login',
    'please login',
    'sign in to your account',
    'not logged in',
    '未登录',
    '请登录',
    '请先登录',
    '需要登录',
    '登录失败',
    'unauthorized',
    'token invalid',
    'login required',
)


def _is_auth_error(raw: str) -> bool:
    """判断 CLI 返回是否为「未登录 / 认证失败」类提示（而非真实模型分析）。"""
    if not raw:
        return False
    low = raw.lower()
    return any(hint in low for hint in _AUTH_ERROR_HINTS)


def _has_uncommitted_changes() -> bool:
    """检测工作区是否有未提交改动（AI 改代码后应非空）。

    用 git status --porcelain 判断；非 git 仓库或命令不可用时返回 False（不阻断流程）。
    """
    try:
        proc = subprocess.run(
            ['git', 'status', '--porcelain'],
            cwd=_PROJECT_ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30,
        )
        out = (proc.stdout or b'').decode('utf-8', errors='replace').strip()
        return bool(out)
    except Exception:
        return False


def _should_ignore_change(path: str) -> bool:
    """AI 改动白名单之外的路径（data/、.git/、venv/、密钥等）应被忽略，不计入有效改动。"""
    norm = path.replace('\\', '/').lower()
    if '/.git/' in norm or norm.startswith('.git/'):
        return True
    if '/venv/' in norm or norm.startswith('venv/'):
        return True
    if '/data/' in norm or norm.startswith('data/'):
        return True
    if '/extensions/scripts/feedback_ai/' in norm or norm.startswith('extensions/scripts/feedback_ai/'):
        return True
    return False


def _effective_changes() -> list:
    """返回 AI 实际改动的、且落在源码白名单内的文件列表（排除 data/、.git/、venv/）。"""
    try:
        proc = subprocess.run(
            ['git', 'status', '--porcelain', '-uall'],
            cwd=_PROJECT_ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30,
        )
        out = (proc.stdout or b'').decode('utf-8', errors='replace')
    except Exception:
        return []
    changed = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        # porcelain 格式：XY path（XY 为状态码）
        body = line[3:].strip() if len(line) > 3 else line
        if _should_ignore_change(body):
            continue
        changed.append(body)
    return changed


def _call_ai(prompt: str) -> str:
    """调用 CodeBuddy CLI 消费契约，返回 AI 的纯文本回复。

    使用 -p（print 非交互，prompt 作为位置参数直传，避开 stdin 在 pipe 下的交互歧义）。
    不指定 --output-format（该选项返回的是对话历史 JSON 而非最终回答），
    改为默认文本输出，由 prompt 约束 AI 只输出契约 JSON，解析时再宽松提取。
    以 bytes 读取后用 utf-8/gbk 双重兜底解码（Windows 下 CLI 输出编码不确定）。

    若 CLI 返回的是「未登录 / 认证失败」提示（工具故障），抛出 AuthError，
    避免把这类无意义的报错当成 AI 分析回复发给用户。
    """
    buddy = os.environ.get('DBOX_BUDDYCN') or r'C:\Users\<用户>\AppData\Roaming\npm\codebuddy.cmd'
    # 关键：
    # 1) -p/--print 是非交互纯文本输出模式；
    # 2) 必须加 --input-format text，并通过【stdin】传 prompt（input=prompt），
    #    不能把 prompt 放在命令行参数里——Windows 下多行/长中文命令行参数会被
    #    CLI 解析丢失，导致 AI 拿不到反馈上下文（表现为「你尚未附上具体的用户
    #    反馈内容」这类默认回复）；
    # 3) -y / --dangerously-skip-permissions + --add-dir <项目根>：允许 AI 在本项目内
    #    直接读写源码文件（方向 B：AI 真正修复代码，而非仅给建议）；
    # 4) cwd 设为项目根，使 AI 的相对路径编辑基于项目根；
    # 5) 以 bytes 读取再 utf-8/gbk 兜底解码，避免 Windows 下控制台 GBK 引起乱码/崩溃。
    proc = subprocess.run(
        [buddy, '-p', '-y', '--add-dir', _PROJECT_ROOT,
         '--input-format', 'text', prompt],
        input=prompt.encode('utf-8'),
        cwd=_PROJECT_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=AI_TIMEOUT,
    )
    raw = (proc.stdout or b'') + (proc.stderr or b'')
    for enc in ('utf-8', 'gbk', 'utf-8-sig'):
        try:
            text = raw.decode(enc)
            break
        except Exception:
            text = raw.decode('utf-8', errors='replace')
    if _is_auth_error(text):
        raise AuthError(
            'AI 工具（CodeBuddy CLI）未登录或认证失败，无法调用模型。'
            '请先执行 `codebuddy /login` 登录后重启调度器。'
        )
    return text


def _parse_contract(raw: str) -> dict:
    """解析 AI 返回的契约（容错）。

    优先尝试结构化 JSON（整体或首个 {...} 块、含 ```json 代码块）；
    若 AI 未返回合法结构化 JSON（该 CLI 模型常返回自然语言分析），则降级：
    将整段文本作为 reply，verdict 默认 needs_decision，并标注决策事项，
    保证任务永远能被处理、不卡死、不丢任务（管理员在待验证环节查看原文）。
    """
    if not raw or not raw.strip():
        raise ValueError('AI 返回为空')

    # 1) 优先：整体 JSON
    text = raw.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return _validate_contract(data)
    except Exception:
        pass

    # 2) 剥离 markdown 代码块后提取首个 {...}
    cleaned = text
    if cleaned.startswith('```'):
        cleaned = cleaned.strip('`')
        cleaned = cleaned.split('\n', 1)[-1] if '\n' in cleaned else cleaned
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start:end + 1])
            if isinstance(data, dict):
                return _validate_contract(data)
        except Exception:
            pass

    # 3) 降级：AI 未返回结构化 JSON，以原文作为回复，转人工决策
    reply = text.strip()
    if not reply:
        raise ValueError('AI 返回内容为空')
    return {
        'verdict': VERDICT_NEEDS_DECISION,
        'reply': reply,
        'analysis': reply,
        'decision_needed': 'AI 未返回结构化结论（可能以自然语言给出分析），请管理员查看原文并判定。',
    }


def _validate_contract(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError('契约根节点必须是对象')
    verdict = data.get('verdict')
    if verdict not in (VERDICT_RESOLVED, VERDICT_NEEDS_DECISION, VERDICT_BLOCKED):
        raise ValueError(f'verdict 非法: {verdict!r}')
    reply = (data.get('reply') or '').strip()
    if not reply:
        raise ValueError('reply 不能为空')
    return {
        'verdict': verdict,
        'reply': reply,
        'analysis': (data.get('analysis') or '').strip(),
        'changes': data.get('changes') or [],
        'decision_needed': data.get('decision_needed'),
    }


# ============================ 单条执行 ============================
def execute_one(issue_id: str) -> dict:
    task = get_ai_task(issue_id)
    if not task:
        enqueue(issue_id)

    task = {
        'state': TASK_PROCESSING,
        'retries': task.get('retries', 0),
        'enqueued_at': task.get('enqueued_at'),
        'started_at': _now_iso(),
        'heartbeat_at': _now_iso(),
        'finished_at': None,
        'last_error': None,
        'verdict': task.get('verdict'),
    }
    _save_ai_task(issue_id, task)

    issue = _load_issue(issue_id)
    if not issue:
        task['state'] = TASK_FAILED
        task['last_error'] = '反馈不存在'
        task['finished_at'] = _now_iso()
        _save_ai_task(issue_id, task)
        return task

    try:
        prompt = _build_prompt(issue)
        raw = _call_ai(prompt)
        contract = _parse_contract(raw)
    except AuthError as e:
        # 工具故障（CLI 未登录）：不应把报错回复发给用户，也不进入「待验证」骚扰
        # 管理员判定反馈本身——它属于自动处理链路自身的问题，需要的是修复工具
        # 登录态，而非人工决策反馈内容。
        task['state'] = TASK_FAILED
        task['last_error'] = str(e)
        task['finished_at'] = _now_iso()
        _save_ai_task(issue_id, task)
        db_append_comment(
            issue_id, AUTO_AUTHOR, AUTO_ROLE,
            f'【自动处理】AI 工具调用失败：{e}\n'
            f'该反馈未自动处理，请先登录 AI 工具后重启调度器重试，或人工处理本反馈。',
        )
        return task
    except Exception as e:
        retries = task.get('retries', 0)
        if retries < MAX_RETRIES:
            task['retries'] = retries + 1
            task['state'] = TASK_PENDING
            task['last_error'] = f'第{retries + 1}次执行失败: {e}'
            task['heartbeat_at'] = None
            task['finished_at'] = None
            _save_ai_task(issue_id, task)
            return task
        task['state'] = TASK_FAILED
        task['last_error'] = f'重试{max(retries, MAX_RETRIES)}次后仍失败: {e}'
        task['finished_at'] = _now_iso()
        _save_ai_task(issue_id, task)
        db_set_status(issue_id, 'pending_verification')
        db_append_comment(
            issue_id, AUTO_AUTHOR, AUTO_ROLE,
            f'【自动处理】AI 分析失败（已重试{max(retries, MAX_RETRIES)}次）：{e}。\n'
            f'已转人工待验证，请管理员查看并手动处理。',
        )
        return task

    verdict = contract['verdict']
    reply = contract['reply']
    analysis = contract['analysis']
    decision = contract.get('decision_needed')

    # 关键验证：AI 声称 resolved（已修复）但工作区实际无代码改动时，不能轻信，
    # 降级为 needs_decision 并明确告知管理员「未实际改动」，避免再次出现
    # 「AI 说修好了但实际没改」的假结案（此前 202608090009 即此问题）。
    if verdict == VERDICT_RESOLVED:
        effective = _effective_changes()
        if not effective:
            verdict = VERDICT_NEEDS_DECISION
            decision = ('AI 声称已修复，但工作区未检测到任何源码改动（changes 为空或仅落在 '
                        'data/.git/venv 等禁改区域）。请人工核实是否真需改代码，或确认 AI 误判。')
            reply = (reply or '') + '\n\n[自动处理提示] 未检测到实际代码改动，已转人工核实。'

    task['state'] = TASK_DONE
    task['verdict'] = verdict
    task['finished_at'] = _now_iso()
    task['last_error'] = None
    _save_ai_task(issue_id, task)

    db_update_extra(issue_id, {
        'ai_reply': reply,
        'ai_analysis': analysis,
        'ai_verdict': verdict,
        'ai_decision': decision,
        'ai_changes': contract.get('changes') or [],
        'ai_processed_at': _now_iso(),
    })
    db_set_status(issue_id, 'pending_verification')
    db_append_comment(issue_id, AUTO_AUTHOR, AUTO_ROLE, reply)

    if verdict in (VERDICT_NEEDS_DECISION, VERDICT_BLOCKED):
        db_append_comment(
            issue_id, AUTO_AUTHOR, AUTO_ROLE,
            f'【自动处理】需人工决策：{decision}',
        )
    return task


def _load_issue(issue_id: str) -> dict:
    runtime_dir = find_runtime_dir()
    issues = load_issues(runtime_dir)
    for it in issues:
        if it.get('id') == issue_id:
            return it
    return {}


# ============================ 轮询一轮 ============================
def recover_and_pick() -> str:
    """重置超时 processing 任务，返回一条 pending 的 issue_id（无则 None）。"""
    runtime_dir = find_runtime_dir()
    issues = load_issues(runtime_dir)
    now_ts = time.time()
    pending_id = None
    for it in issues:
        iid = it.get('id')
        extra = it.get('feedback_extra')
        if not extra:
            continue
        data = _safe_json(extra)
        task = data.get('ai_task') or {}
        state = task.get('state')
        if state == TASK_PROCESSING:
            hb = task.get('heartbeat_at')
            hb_ts = 0
            if hb:
                try:
                    hb_ts = datetime.fromisoformat(hb).timestamp()
                except Exception:
                    hb_ts = 0
            if now_ts - hb_ts > PROCESSING_TIMEOUT:
                task['state'] = TASK_PENDING
                task['last_error'] = '心跳超时，自动重置为 pending（崩溃恢复）'
                task['heartbeat_at'] = None
                _save_ai_task(iid, task)
        if state == TASK_PENDING and pending_id is None:
            pending_id = iid
    return pending_id


def _auto_enqueue_new():
    """自动发现「未入队且状态为 open」的反馈并入队，使其进入 AI 处理流程。

    反馈创建时没有任何地方主动调用 enqueue，因此必须在轮询入口兜底扫描，
    否则新反馈的 feedback_extra 永远为 None，AI 永远不会处理（表现为新增反馈
    长时间不进入「处理中」）。
    """
    runtime_dir = find_runtime_dir()
    issues = load_issues(runtime_dir)
    count = 0
    for it in issues:
        iid = it.get('id')
        extra = it.get('feedback_extra')
        if extra:  # 已入队（含已完成/跳过），跳过
            continue
        if it.get('status') != ISSUE_OPEN:
            continue
        enqueue(iid)
        count += 1
    if count:
        print(f'自动入队 {count} 条新反馈')


def run_once():
    """被调度器调用时执行的一轮：自动入队新反馈 + 崩溃恢复 + 处理一条 pending。"""
    init_feedback_db()
    _auto_enqueue_new()
    iid = recover_and_pick()
    if iid:
        print(f'处理 {iid}')
        result = execute_one(iid)
        print(f'结果: {result.get("state")} verdict={result.get("verdict")} '
              f'retries={result.get("retries")} err={result.get("last_error")}')
    else:
        print('队列为空，无待处理任务')


# ============================ CLI ============================
def main():
    parser = argparse.ArgumentParser(description='反馈中心 AI 自动处理（poll 脚本）')
    sub = parser.add_subparsers(dest='cmd')

    p_enq = sub.add_parser('enqueue', help='入队一条反馈')
    p_enq.add_argument('issue_id')
    p_enq.add_argument('--force', action='store_true')
    p_enq.set_defaults(func=lambda a: print(json.dumps(enqueue(a.issue_id, a.force), ensure_ascii=False, indent=2)))

    p_st = sub.add_parser('status', help='查看 ai_task 状态')
    p_st.add_argument('issue_id')
    p_st.set_defaults(func=_cli_status)

    p_rt = sub.add_parser('retry', help='重置失败/卡死任务并重试')
    p_rt.add_argument('issue_id')
    p_rt.set_defaults(func=_cli_retry)

    p_ca = sub.add_parser('cancel', help='取消一条任务（置 skipped）')
    p_ca.add_argument('issue_id')
    p_ca.set_defaults(func=_cli_cancel)

    p_pr = sub.add_parser('process', help='同步处理单条（调试）')
    p_pr.add_argument('issue_id')
    p_pr.set_defaults(func=lambda a: print(json.dumps(execute_one(a.issue_id), ensure_ascii=False, indent=2)))

    p_run = sub.add_parser('run', help='跑一轮（等价于被调度器调用）')
    p_run.set_defaults(func=lambda a: run_once())

    args = parser.parse_args()
    if not getattr(args, 'cmd', None):
        # 无子命令：作为被调度器调用的脚本，读 stdin 后跑一轮
        try:
            raw = sys.stdin.read().strip()
            _ = json.loads(raw) if raw else {}
        except Exception:
            pass
        run_once()
        return
    args.func(args)


def _cli_status(args):
    task = get_ai_task(args.issue_id)
    if not task:
        print(f'#{args.issue_id} 无 ai_task（未入队）')
        return
    print(json.dumps(task, ensure_ascii=False, indent=2))
    extra = db_get_extra(args.issue_id)
    if extra.get('ai_reply'):
        print('-' * 60)
        print(f'verdict: {extra.get("ai_verdict")}')
        print(f'reply: {extra.get("ai_reply")}')


def _cli_retry(args):
    task = get_ai_task(args.issue_id)
    if not task:
        print(f'#{args.issue_id} 无任务可重试')
        return
    task['state'] = TASK_PENDING
    task['retries'] = 0
    task['last_error'] = None
    task['heartbeat_at'] = None
    task['finished_at'] = None
    _save_ai_task(args.issue_id, task)
    print(f'#{args.issue_id} 已重置为 pending，将重新消费')


def _cli_cancel(args):
    task = get_ai_task(args.issue_id)
    if not task:
        print(f'#{args.issue_id} 无任务可取消')
        return
    task['state'] = TASK_SKIPPED
    task['last_error'] = '已手动取消'
    task['finished_at'] = _now_iso()
    _save_ai_task(args.issue_id, task)
    print(f'#{args.issue_id} 已取消（skipped），调度器不再处理')


if __name__ == '__main__':
    main()
