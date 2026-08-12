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


# TODO(凭证集中管理): 把 codebuddy 凭证纳入「凭证保险箱」统一管理的需求暂未实现，延后处理。
#   背景：反馈中心要求 codebuddy 的凭证能在拓展管理→凭证保险箱里看到并集中管理。
#   现状：当前 codebuddy 实际走 ~/.codebuddy 的 OAuth 登录会话鉴权（见 _codebuddy_user_home），
#        并非 ANTHROPIC_API_KEY 环境变量；且本函数里保险库目录路径拼成了 src/common（应为
#        src/web/common），导致 from credential_vault import 始终异常、被静默吞掉，保险库分支从未生效。
#   待办：重新设计凭证来源——
#        1) 若 codebuddy 提供可用的 API token，让保险箱作为唯一权威来源（注入环境变量）；
#        2) 否则在保险箱 UI 呈现 ~/.codebuddy 登录会话的管理入口（已登录账号/重新登录）；
#        3) 修正保险库目录路径，使保险库读取真正生效。
#   注：此前一次「凭证保险库集中管理 codebuddy token」提交已回退（基于错误前提，视为死代码）。

def _load_codebuddy_token() -> str:
    """从通用凭证保险库读取 codebuddy token（与 feedback_ai 一致）。"""
    env_token = os.environ.get(_ANTHROPIC_API_KEY_ENV)
    if env_token:
        return env_token.strip()
    try:
        sys_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..', 'common')
        if sys_path not in sys.path:
            sys.path.insert(0, sys_path)
        from credential_vault import CredentialVault, data_dir_for  # type: ignore
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
    pkg_dir = os.path.dirname(os.path.abspath(__file__))         # src/web/script_engine
    return os.path.dirname(os.path.dirname(os.path.dirname(pkg_dir)))


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


def _sse_block(event: str, data) -> str:
    """构造一段合规的 SSE 文本块。

    data 中的换行会被拆成多行 `data:` 字段，避免破坏 SSE 协议
    （否则含换行的回复会导致事件解析错位、前端拿不到完整回复）。
    """
    data = '' if data is None else str(data)
    lines = data.split('\n')
    return 'event: %s\n' % event + ''.join('data: ' + ln + '\n' for ln in lines) + '\n'


def _file_feedback(ftype: str, title: str, content: str):
    """在反馈中心建一条反馈单，返回新单号；失败返回 None。

    仅由 _maybe_file_feedback 在 AI 判定为「新反馈」时调用。
    身份遵循项目准则：反馈中心交互使用「自动助手」身份
    （submitter='自动助手'、source='ai_assistant'、auto_classified=True）。
    """
    try:
        from backend.feedback_db import db_create_issue, init_feedback_db
        init_feedback_db()
        if ftype not in ('bug', 'suggestion'):
            ftype = 'suggestion'
        title = (title or '').strip()
        content = (content or '').strip()
        if not title and not content:
            return None
        return db_create_issue(
            title=title, content=content, category=ftype,
            submitter='自动助手', source='ai_assistant', auto_classified=True,
        )
    except Exception as e:
        try:
            from liblog import get_service_logger
            get_service_logger('dbox-web').warning('AI 助手建单失败: %s' % e)
        except Exception:
            pass
        return None


def _maybe_file_feedback(reply: str):
    """若 AI 回复内含 feedback-request 块，则建单并回填单号、剥离该块。

    返回处理后的回复文本（始终为字符串）。解析/建单失败时保留原回复、仅剥离块。
    """
    if not reply:
        return reply
    m = _FB_RE.search(reply)
    if not m:
        return reply
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
    return reply


# 对话系统约束：本助手具备真实执行能力，要求直接动手而非只描述。
_SYSTEM_PROMPT = (
    '你是一个嵌入在媒体库管理后台里的 AI 助手，拥有读写文件、运行命令的真实能力。\n'
    '当用户布置具体任务（如修改代码、创建/删除文件、执行命令等）时，请直接动手完成，'
    '不要只罗列步骤或描述做法；完成后用简体中文简要说明你做了什么。\n'
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
    '要在库里查找资源的真实标识，可用 Bash 工具直接查询媒体库数据库（Python 内置 sqlite3，无需额外依赖）：\n'
    '  python -c "import sqlite3,os; p=os.path.join(os.environ.get(\'DBOX_DATA_DIR\',\'data\'),\'databases\',\'dbox.db\'); c=sqlite3.connect(p); [print(r) for r in c.execute(\"SELECT hash,title FROM videos WHERE title LIKE \'%关键字%\' LIMIT 5\")]"\n'
    '（图集表为 galleries、帖子表 posts、文本表 texts；posts/texts 取 id 列即可。）\n'
    '仅在确实引用到某个具体资源时才使用此链接；闲聊或泛泛而谈时不要编造引用。'
)


# 解析 AI 回复中的 feedback-request 围栏块（AI 用其对反馈中心提单，后端执行建单并回填单号）
_FB_RE = re.compile(r'```feedback-request\s*\n(.*?)```', re.DOTALL)


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
        # 尝试挂接统一任务管理器（失败不影响对话功能）
        try:
            from unified_tasks import init_task_manager as _init_tm
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
            self._db.execute('CREATE INDEX IF NOT EXISTS idx_ai_tasks_status ON ai_tasks(status)')
            self._db.execute('CREATE INDEX IF NOT EXISTS idx_ai_tasks_created ON ai_tasks(created_at)')
            self._db.commit()

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

    def _set_status(self, task_id, status, reply=None, error=None):
        now = self._now()
        with self._lock:
            if reply is not None:
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
            from unified_tasks import create_task
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
            from unified_tasks import update_task, get_task as ut_get
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
            from unified_tasks import delete_task
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

    def _build_prompt(self, message):
        parts = [_SYSTEM_PROMPT]
        turns = self._context_turns()
        if turns:
            parts.append('以下是之前的对话记录，供你理解上下文：')
            for up, ar in turns:
                parts.append('用户：' + up)
                parts.append('助手：' + ar)
            parts.append('')
        parts.append('用户问题：' + message)
        return '\n'.join(parts)

    def _process(self, task_id):
        task = self.get_task(task_id)
        if not task:
            return
        with self._lock:
            self._buffers[task_id] = []
            self._set_status(task_id, self.STATUS_RUNNING)
            self._emit(task_id, 'status', 'running')

        buddy = _resolve_buddy_cli()
        if not buddy:
            self._set_status(task_id, self.STATUS_FAILED,
                             error='未找到 CodeBuddy CLI，请在凭证保险库配置 codebuddy，'
                                   '或设置环境变量 DBOX_BUDDYCN 指向 codebuddy.cmd 绝对路径')
            self._emit(task_id, 'error', '未找到 CodeBuddy CLI，请在凭证保险库配置 codebuddy')
            self._finish_emit(task_id, 'failed')
            return

        prompt = self._build_prompt(task['prompt'])

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
            '--max-turns', '60',
            '--add-dir', _project_root(),
            '--input-format', 'text',
        ]

        full = []
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, cwd=_project_root(), env=env,
                creationflags=(CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0),
            )
            with self._lock:
                self._procs[task_id] = proc

            # 看门狗：整体执行超过上限则强制结束进程树（含子进程），避免 worker 卡死
            def _watchdog():
                self._cancel[task_id] = True
                self._terminate(proc)
            watchdog = threading.Timer(_MAX_TASK_SECONDS, _watchdog)
            watchdog.daemon = True
            watchdog.start()

            # 经 stdin 传入 prompt（仅 stdin，不传位置参数）
            try:
                proc.stdin.write(prompt.encode('utf-8'))
                proc.stdin.close()
            except Exception:
                pass

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
                self._terminate(proc)  # 兜底清理可能残留的子进程，释放 stdout 管道

            if self._cancel.get(task_id):
                self._set_status(task_id, self.STATUS_CANCELLED, error='已取消')
                self._emit(task_id, 'error', '任务已取消')
                self._finish_emit(task_id, 'cancelled')
                return

            if _is_auth_error(err_text):
                self._set_status(task_id, self.STATUS_FAILED, error='CodeBuddy 认证失败')
                self._emit(task_id, 'error', 'CodeBuddy 认证失败，请在凭证保险库配置 codebuddy token 或执行 codebuddy /login')
                self._finish_emit(task_id, 'failed')
                return
            if proc.returncode not in (0, None):
                err_excerpt = err_text.strip()[:500]
                self._set_status(task_id, self.STATUS_FAILED, error='AI 执行出错（退出码 %s）: %s' % (proc.returncode, err_excerpt))
                self._emit(task_id, 'error', 'AI 执行出错（退出码 %s）: %s' % (proc.returncode, err_excerpt))
                self._finish_emit(task_id, 'failed')
                return

            reply = '\n'.join(full).strip()
            if not reply and proc.returncode in (0, None):
                # 模型仅执行了工具操作而未产出文本（常见于“直接动手完成”场景），
                # 此时 stdout 为空。为避免聊天框出现空白气泡，给出友好占位说明。
                reply = '（任务已执行完成，无文本输出）'
            # 若 AI 在回复中携带 feedback-request 块（判定为提交新反馈），则建单、
            # 回填真实单号并剥离该块，再存库与下发。
            reply = _maybe_file_feedback(reply)
            self._set_status(task_id, self.STATUS_COMPLETED, reply=reply)
            self._emit(task_id, 'done', reply)
            self._finish_emit(task_id, 'completed')
        except Exception as e:
            self._set_status(task_id, self.STATUS_FAILED, error='调用失败: ' + str(e))
            self._emit(task_id, 'error', '调用失败: ' + str(e))
            self._finish_emit(task_id, 'failed')

    # ---------- SSE 发布订阅 ----------
    def _append_token(self, task_id, piece):
        """追加一个 token：写入缓冲区并推送给所有订阅者。"""
        with self._lock:
            self._buffers.setdefault(task_id, []).append(piece)
            subs = list(self._subscribers.get(task_id, []))
        for q in subs:
            try:
                q.put(('token', piece))
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

    def _finish_emit(self, task_id, _status):
        """通知所有订阅者任务结束（推送终止哨兵）并清理缓冲区。"""
        with self._lock:
            subs = list(self._subscribers.get(task_id, []))
            self._subscribers.pop(task_id, None)
            self._buffers.pop(task_id, None)
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
        - 正在处理（running）：先回放已产出的 token 缓冲，再续接后续实时 token。
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
            buf = list(self._buffers.get(task_id, []))
            cur = self._db.execute(
                'SELECT status FROM ai_tasks WHERE task_id=?', (task_id,)).fetchone()
            cur_status = cur['status'] if cur else status

        if cur_status == self.STATUS_PENDING:
            yield _sse_block('queued', '')

        # running 时先把缓冲（已在执行的产出）回放，避免刷新后丢失前半段
        for piece in buf:
            yield _sse_block('token', piece)

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
            if etype == 'token':
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
                "SELECT task_id, prompt, reply, status, error, created_at FROM ai_tasks "
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
            active = {'id': r['task_id'], 'prompt': r['prompt'], 'status': r['status'],
                      'created_at': r['created_at'], 'stream': buf}

        has_more = len(hist_rows) > history_limit
        hist_rows = hist_rows[:history_limit]
        history = [{'id': r['task_id'], 'prompt': r['prompt'], 'reply': r['reply'],
                    'status': r['status'], 'error': r['error'],
                    'created_at': r['created_at']} for r in hist_rows]

        return {'pending': pending, 'active': active, 'history': history, 'has_more': has_more}

    def history_page(self, cursor=None, limit=10):
        """分页获取更早的历史（按 created_at 倒序）。cursor 为上一页最后一条的 created_at。"""
        with self._lock:
            if cursor is not None:
                rows = self._db.execute(
                    "SELECT task_id, prompt, reply, status, error, created_at FROM ai_tasks "
                    "WHERE status IN (?, ?, ?) AND created_at < ? ORDER BY created_at DESC LIMIT ?",
                    (self.STATUS_COMPLETED, self.STATUS_FAILED, self.STATUS_CANCELLED,
                     float(cursor), limit + 1)).fetchall()
            else:
                rows = self._db.execute(
                    "SELECT task_id, prompt, reply, status, error, created_at FROM ai_tasks "
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
                from unified_tasks import get_tasks as ut_get_all
                for t in ut_get_all(role='admin', limit=200):
                    if (t.get('kind') == 'ai_chat') or str(t.get('task_id', '')).startswith('ai:'):
                        self._remove_from_unified(t['task_id'].split(':', 1)[-1] if str(t['task_id']).startswith('ai:') else t['task_id'])
            except Exception:
                pass
        return True


# 单例
ai_mgr = AIChatManager()
