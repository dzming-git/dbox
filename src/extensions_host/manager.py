"""外部脚本任务管理器：发现脚本、执行子进程、解析进度、持久化任务、入库通知。

本模块运行于独立的拓展宿主进程（extensions_host），不直接 import 主服务的
core.models / library_watcher / backend.access 等业务模块：涉及资源库磁盘目标、
帖子生成等副作用，一律通过 platform_client 以 HTTP 调用主服务的内部契约接口完成，
从而实现拓展管理与主模块的彻底解耦。
"""
import os
import sys
import json
import time
import uuid
import shlex
import shutil
import secrets
import sqlite3
import threading
import subprocess
import concurrent.futures
from datetime import datetime

from manifest import load_all, scripts_base_dir
from ingest import ingest_file
from shared.credential_vault import CredentialVault
from shared.unified_tasks import init_task_manager as _init_task_manager, sync_job as _tm_sync_job

STATE_FILE = 'script_state.json'  # 持久化 enabled 覆盖，避免 reload 重置


def _now():
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')


class ScriptJobManager:
    def __init__(self):
        self.app = None
        self.base_dir = None
        self.max_workers = 2
        self._lock = threading.RLock()
        self._db = None
        self.scripts = {}
        self._executor = None
        self._procs = {}
        self._cancel = {}
        self._reported = {}
        self._input_events = {}
        self._input_responses = {}
        self._state_path = None
        self._initialized = False
        self.vault = None

    # ---------- 初始化 ----------
    def init(self, app, base_dir=None, max_workers=2):
        if self._initialized:
            return
        self.app = app
        self.base_dir = base_dir or scripts_base_dir()
        self.max_workers = max_workers
        os.makedirs(self.base_dir, exist_ok=True)
        data_dir = self._data_dir()
        os.makedirs(os.path.join(data_dir, 'script_jobs'), exist_ok=True)
        self._state_path = os.path.join(data_dir, STATE_FILE)
        self.vault = CredentialVault(data_dir)
        self._db = sqlite3.connect(os.path.join(data_dir, 'script_jobs.db'),
                                   check_same_thread=False)
        # 用 Row 工厂：列按【列名】访问，避免 SELECT * 与 cols 列表顺序不一致导致错位
        self._db.row_factory = sqlite3.Row
        self._init_db()
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.reload()
        # 初始化统一任务管理器（幂等），脚本任务会镜像到任务表供前端展示
        try:
            _init_task_manager(data_dir)
        except Exception as e:
            print(f'[script_engine] 初始化任务管理器失败: {e}')
        self._initialized = True

    def _sync_task(self, job_id):
        """将脚本任务镜像到统一任务管理器（供前端任务页/红点读取）。"""
        try:
            job = self.get_job(job_id)
            if job:
                _tm_sync_job(job)
        except Exception as e:
            print(f'[script_engine] 镜像任务失败 job={job_id}: {e}')

    def _data_dir(self):
        env = os.environ.get('DBOX_DATA_DIR')
        if env:
            return env
        pkg_dir = os.path.dirname(os.path.abspath(__file__))    # src/extensions_host
        project_root = os.path.dirname(os.path.dirname(pkg_dir))  # 向上两级 -> 项目根 (dbox)
        return os.path.join(project_root, 'data')

    def _init_db(self):
        with self._lock:
            self._db.execute('''CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                script_id TEXT,
                script_name TEXT,
                status TEXT,
                progress INTEGER DEFAULT 0,
                params TEXT,
                result TEXT,
                owner_id INTEGER,
                token TEXT,
                working_dir TEXT,
                library_id INTEGER,
                notified INTEGER DEFAULT 0,
                error TEXT,
                created_at TEXT,
                updated_at TEXT
            )''')
            self._db.execute('''CREATE TABLE IF NOT EXISTS job_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT,
                ts TEXT,
                level TEXT,
                message TEXT
            )''')
            # 用户对脚本参数的个人默认值（按脚本+参数名+用户隔离）
            self._db.execute('''CREATE TABLE IF NOT EXISTS script_param_defaults (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                script_id TEXT,
                param_name TEXT,
                owner_id INTEGER,
                value TEXT,
                updated_at TEXT,
                UNIQUE(script_id, param_name, owner_id)
            )''')
            self._db.commit()
            # 迁移：交互式输入相关字段（老库可能没有）
            for col, ctype in (('awaiting', 'INTEGER DEFAULT 0'),
                               ('pending_input', 'TEXT'),
                               ('input_response', 'TEXT')):
                try:
                    self._db.execute(f'ALTER TABLE jobs ADD COLUMN {col} {ctype}')
                except Exception:
                    pass
            self._db.commit()

    # ---------- 脚本发现 / 状态 ----------
    def reload(self):
        with self._lock:
            self.scripts = load_all(self.base_dir)
            saved = self._load_state()
            for sid, sc in self.scripts.items():
                if sid in saved:
                    sc['enabled'] = bool(saved[sid])
        return len(self.scripts)

    # ---------- 脚本参数用户默认值 ----------
    def get_param_defaults(self, script_id: str, owner_id: int) -> dict:
        """读取某用户对某脚本所有参数的个人默认值 {param_name: value}。"""
        try:
            with self._lock:
                rows = self._db.execute(
                    'SELECT param_name, value FROM script_param_defaults '
                    'WHERE script_id=? AND owner_id=?',
                    (script_id, owner_id),
                ).fetchall()
        except Exception:
            return {}
        out = {}
        for name, value in rows:
            try:
                out[name] = json.loads(value)
            except Exception:
                out[name] = value
        return out

    def save_param_defaults(self, script_id: str, owner_id: int,
                            defaults: dict) -> bool:
        """保存某用户对某脚本参数的个人默认值。

        defaults: {param_name: value}，仅持久化声明了 user_defaultable 的参数。
        值为 None 或空串的键表示从默认集中移除。
        """
        now = time.strftime('%Y-%m-%d %H:%M:%S')
        sc = self.scripts.get(script_id)
        if not sc:
            return False
        allowed = {p.get('name') for p in sc.get('params', [])
                   if p.get('user_defaultable')}
        try:
            with self._lock:
                for name, value in defaults.items():
                    if name not in allowed:
                        continue
                    if value is None or value == '':
                        self._db.execute(
                            'DELETE FROM script_param_defaults '
                            'WHERE script_id=? AND param_name=? AND owner_id=?',
                            (script_id, name, owner_id),
                        )
                    else:
                        self._db.execute(
                            'INSERT INTO script_param_defaults '
                            '(script_id, param_name, owner_id, value, updated_at) '
                            'VALUES (?,?,?,?,?) '
                            'ON CONFLICT(script_id, param_name, owner_id) '
                            'DO UPDATE SET value=excluded.value, '
                            'updated_at=excluded.updated_at',
                            (script_id, name, owner_id,
                             json.dumps(value, ensure_ascii=False), now),
                        )
                self._db.commit()
            return True
        except Exception as e:
            print(f'[script_engine] 保存参数默认值失败: {e}')
            return False

    def _load_state(self):
        if not self._state_path or not os.path.isfile(self._state_path):
            return {}
        try:
            with open(self._state_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_state(self):
        if not self._state_path:
            return
        with self._lock:
            try:
                with open(self._state_path, 'w', encoding='utf-8') as f:
                    json.dump({sid: bool(sc.get('enabled')) for sid, sc in self.scripts.items()}, f)
            except Exception:
                pass

    def set_enabled(self, script_id, enabled):
        with self._lock:
            if script_id not in self.scripts:
                return False
            self.scripts[script_id]['enabled'] = bool(enabled)
            self._save_state()
        return True

    # ---------- 参数校验 ----------
    def _validate_params(self, manifest, params):
        params = dict(params or {})
        for p in manifest.get('params', []):
            name = p.get('name')
            # 多选参数：先确保是列表（标量归一成单元素列表），再走默认/必填校验
            if p.get('type') == 'multi_enum' and name in params and not isinstance(params[name], list):
                params[name] = [params[name]] if params[name] not in (None, '') else []
            if name not in params and 'default' in p:
                params[name] = p['default']
            if p.get('required'):
                val = params.get(name)
                if p.get('type') == 'multi_enum':
                    # 多选：要求是「非空数组」
                    if not isinstance(val, list) or len(val) == 0:
                        return f'缺少必填参数: {p.get("label", name)}'
                elif val in (None, ''):
                    return f'缺少必填参数: {p.get("label", name)}'
        return params

    def _resolve_library(self, manifest, params):
        sel = next((p for p in manifest.get('params', []) if p.get('type') == 'library_select'), None)
        if not sel:
            return None
        lib_id = params.get(sel['name'])
        if not lib_id:
            return None
        try:
            lib_id = int(lib_id)
        except Exception:
            return None
        try:
            from platform_client import library_disk_targets
            targets = library_disk_targets(lib_id)
            if targets:
                return {'id': lib_id, 'type': sel.get('media_type', 'any'), 'path': targets[0]}
        except Exception:
            pass
        return {'id': lib_id, 'type': sel.get('media_type', 'any'), 'path': ''}

    # ---------- Cookie 校验 / 物化 ----------
    def _check_cookies(self, manifest, params):
        """运行前校验 cookie 配置是否齐全（仅管理员能配置，故此处只检查存在性）。"""
        if not self.vault:
            return None
        for domain in (manifest.get('required_cookies') or []):
            if not self.vault.get_by_domain(domain):
                return f'缺少 {domain} 的凭证配置（请在「凭证保险库」中添加）'
        for p in manifest.get('params', []):
            if p.get('type') == 'cookie_select':
                pid = params.get(p.get('name'))
                if p.get('required') and not pid:
                    return f'请选择 cookie: {p.get("label", p.get("name"))}'
                if pid and not self.vault.get(pid):
                    return f'cookie 配置不存在: {pid}'
        return None

    def _resolve_cookies(self, manifest, params, working_dir):
        """物化 cookie 到 working_dir，返回 (params, cookie_ctx)。

        - required_cookies（按域名）：自动匹配 vault 中对应域名 profile 并物化，写入 context.cookies[domain]。
        - cookie_select 参数：把用户选中的 profile id 物化，并将该参数值替换为文件路径（脚本直接拿到路径）。
        """
        cookie_ctx = {}
        if self.vault:
            for domain in (manifest.get('required_cookies') or []):
                rec = self.vault.get_by_domain(domain)
                if not rec:
                    raise KeyError(f'缺少 {domain} 的 cookie 配置')
                path, fmt = self.vault.materialize(rec['id'], working_dir)
                cookie_ctx[domain] = {'path': path, 'format': fmt}
            for p in manifest.get('params', []):
                if p.get('type') == 'cookie_select':
                    pid = params.get(p.get('name'))
                    if pid:
                        path, fmt = self.vault.materialize(pid, working_dir)
                        params[p['name']] = path
                        dom = p.get('domain_filter') or self.vault.get(pid).get('domain')
                        cookie_ctx[dom] = {'path': path, 'format': fmt}
        return params, cookie_ctx

    def _cleanup(self, job_id):
        """删除任务临时目录（含临时 cookie 文件与未移动的产物）。"""
        job = self._get_job_row(job_id)
        if job and job['working_dir'] and os.path.isdir(job['working_dir']):
            shutil.rmtree(job['working_dir'], ignore_errors=True)

    # ---------- 命令构建（安全：仅允许白名单目录内的文件，绝不使用 shell） ----------
    def _build_cmd(self, manifest, script_dir):
        cmd_name = manifest.get('command')
        if not cmd_name:
            raise ValueError('manifest 缺少 command')
        script_file = os.path.abspath(os.path.join(script_dir, cmd_name))
        base = os.path.abspath(self.base_dir)
        if not (script_file == base or script_file.startswith(base + os.sep)):
            raise PermissionError('脚本不在允许的目录内')
        if not os.path.isfile(script_file):
            raise FileNotFoundError(f'脚本文件不存在: {cmd_name}')
        rt = (manifest.get('runtime') or 'executable').lower()
        if rt == 'python':
            return [sys.executable, script_file]
        if rt == 'node':
            return ['node', script_file]
        if rt in ('exe', 'binary'):
            return [script_file]
        if rt == 'shell':
            return (['cmd', '/c', script_file] if os.name == 'nt' else ['sh', script_file])
        return [script_file]

    # ---------- 运行 ----------
    def run(self, script_id, params, owner_id, notify_base):
        with self._lock:
            sc = self.scripts.get(script_id)
            if not sc:
                return None, '脚本不存在'
            if sc.get('_error'):
                return None, f'脚本清单错误: {sc["_error"]}'
            if not sc.get('enabled'):
                return None, '脚本未启用（需管理员启用）'
            validated = self._validate_params(sc, params)
            if isinstance(validated, str):
                return None, validated
            ck_err = self._check_cookies(sc, validated)
            if ck_err:
                return None, ck_err
            job_id = 'job_' + uuid.uuid4().hex[:16]
            token = secrets.token_hex(16)
            self._notify_base = notify_base
            working_dir = os.path.join(self._data_dir(), 'script_jobs', job_id)
            os.makedirs(working_dir, exist_ok=True)
            lib = self._resolve_library(sc, validated)
            ctx = {
                'working_dir': working_dir,
                'libraries': [lib] if lib else [],
                'notify': {
                    'url': f'{notify_base.rstrip("/")}/api/scripts/{job_id}/notify',
                    'token': token,
                },
            }
            self._insert_job({
                'id': job_id, 'script_id': script_id, 'script_name': sc.get('name', script_id),
                'status': 'queued', 'progress': 0, 'params': json.dumps(validated, ensure_ascii=False),
                'owner_id': owner_id, 'token': token, 'working_dir': working_dir,
                'library_id': lib['id'] if lib else None,
                'notified': 0, 'error': '', 'created_at': _now(), 'updated_at': _now(),
            })
        self._executor.submit(self._execute, job_id)
        return job_id, None

    # ---------- 执行子进程 ----------
    def _execute(self, job_id):
        job = self._get_job_row(job_id)
        if not job:
            return
        manifest = self.scripts.get(job['script_id'])
        if not manifest:
            self._finish(job_id, 'failed', error='脚本未找到')
            return
        try:
            cmd = self._build_cmd(manifest, manifest['_dir'])
        except Exception as e:
            self._finish(job_id, 'failed', error=f'命令构建失败: {e}')
            return

        params = json.loads(job['params']) if job['params'] else {}
        ctx = {
            'working_dir': job['working_dir'],
            'libraries': self._lib_ctx(job['library_id']),
            'notify': {
                'url': f'{getattr(self, "_notify_base", "")}/api/scripts/{job_id}/notify',
                'token': job['token'],
            },
            'input': {
                'url': f'{getattr(self, "_notify_base", "")}/api/scripts/{job_id}/input',
                'token': job['token'],
            },
        }
        # 解析 cookie：把 vault 中的 profile 物化到 working_dir，并把路径注入 context / 替换参数
        try:
            params, cookie_ctx = self._resolve_cookies(manifest, params, job['working_dir'])
        except Exception as e:
            self._finish(job_id, 'failed', error=f'Cookie 解析失败: {e}')
            return
        ctx['cookies'] = cookie_ctx
        payload = {'job_id': job_id, 'params': params, 'context': ctx}
        stdin_text = json.dumps(payload, ensure_ascii=False)

        self._set_status(job_id, 'running')
        timeout = int(manifest.get('timeout') or 0)
        proc = None
        try:
            proc = subprocess.Popen(
                cmd, cwd=manifest['_dir'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace', bufsize=1,
            )
            with self._lock:
                self._procs[job_id] = proc
            if proc.stdin:
                try:
                    proc.stdin.write(stdin_text + '\n')
                    proc.stdin.close()
                except Exception:
                    pass

            # 超时看门狗
            watchdog = None
            if timeout > 0:
                def _watch():
                    time.sleep(timeout)
                    p = self._procs.get(job_id)
                    if p and p.poll() is None:
                        try:
                            p.kill()
                        except Exception:
                            pass
                watchdog = threading.Thread(target=_watch, daemon=True)
                watchdog.start()

            result_files = []
            notified_in_script = False
            for line in iter(proc.stdout.readline, ''):
                line = line.strip()
                if not line:
                    continue
                self._handle_line(job_id, line, result_files)
                if self._cancel.get(job_id):
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    break
            proc.wait()
            rc = proc.returncode

            with self._lock:
                self._cancel.pop(job_id, None)
                self._procs.pop(job_id, None)

            if self._cancel.get(job_id):
                self._finish(job_id, 'cancelled')
                return

            if rc == 0:
                # 脚本产出文件可能由 notify 上报，或在 result.files 中；统一由管理器移动到资源库并入库
                files = self._reported.get(job_id)
                if not files:
                    files = result_files
                final_paths = []
                if files:
                    final_paths = self._reconcile(job_id, job['library_id'], files)
                self._finish(job_id, 'success', result=json.dumps({'files': final_paths}, ensure_ascii=False))
            else:
                self._finish(job_id, 'failed', error=f'脚本退出码 {rc}')
        except Exception as e:
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
            self._finish(job_id, 'failed', error=str(e))
        finally:
            with self._lock:
                self._procs.pop(job_id, None)
                self._cancel.pop(job_id, None)
            # 任务结束：清理 working_dir（含临时 cookie 文件），避免凭证残留
            self._cleanup(job_id)

    def _handle_line(self, job_id, line, result_files):
        try:
            obj = json.loads(line)
        except Exception:
            self._append_log(job_id, 'info', line)
            return
        t = obj.get('type')
        if t == 'progress':
            pct = int(obj.get('percent', 0) or 0)
            with self._lock:
                self._db.execute('UPDATE jobs SET progress=?, updated_at=? WHERE id=?',
                                 (pct, _now(), job_id))
                self._db.commit()
            self._append_log(job_id, 'info', obj.get('message', f'进度 {pct}%'))
            self._sync_task(job_id)
        elif t == 'log':
            self._append_log(job_id, obj.get('level', 'info'), obj.get('message', ''))
        elif t == 'error':
            self._append_log(job_id, 'error', obj.get('message', ''))
        elif t == 'await_input':
            self._set_awaiting(job_id, obj.get('input', {}))
            self._sync_task(job_id)
        elif t == 'result':
            files = obj.get('files', [])
            if isinstance(files, list):
                result_files.extend(files)
            self._append_log(job_id, 'info', '脚本返回结果')
        else:
            self._append_log(job_id, 'info', line)

    def _lib_ctx(self, library_id):
        if not library_id:
            return []
        try:
            from platform_client import library_disk_targets
            targets = library_disk_targets(library_id)
            if targets:
                return [{'id': library_id, 'type': 'any', 'path': targets[0]}]
        except Exception:
            pass
        return [{'id': library_id, 'type': 'any', 'path': ''}]

    def _notify_base_from_job(self, job_id):
        # 已弃用；notify base 在 run 时存入 self._notify_base。
        return getattr(self, '_notify_base', '')

    # ---------- 入库通知（脚本回调） ----------
    def notify(self, job_id, token, files):
        """脚本回调：记录待入库文件（最终移动与入库在任务成功时由管理器统一完成）。"""
        job = self._get_job_row(job_id)
        if not job:
            return False, '任务不存在'
        if not token or token != job['token']:
            return False, '令牌无效'
        with self._lock:
            try:
                import json as _json, tempfile
                _p = os.path.join(tempfile.gettempdir(), '_notify_files.json')
                with open(_p, 'w', encoding='utf-8') as _df:
                    _df.write(_json.dumps(files, ensure_ascii=False, default=str))
            except Exception:
                pass
            self._reported[job_id] = files or []
            self._db.execute('UPDATE jobs SET notified=1, updated_at=? WHERE id=?',
                             (_now(), job_id))
            self._db.commit()
        return True, '已记录待入库文件'

    def _reconcile(self, job_id, library_id, files):
        """把脚本产出文件从临时目录移动到资源库路径（跨盘安全），再按 modes 入库。

        返回移动后的最终路径列表。同组（group）的资源会被聚合成一条帖子（组合模式）。
        涉及资源库磁盘目标与帖子生成等副作用，通过 platform_client 调用主服务完成。
        """
        final_paths = []
        post_groups = {}  # group_key -> {'title':..., 'ids':[...]}
        if not library_id:
            return final_paths
        job = self._get_job_row(job_id)
        owner_id = job['owner_id'] if job else None
        lib = self._lib_ctx(library_id)
        lib_path = lib[0]['path'] if lib else ''
        working_dir = job['working_dir']
        for f in files:
            path = f.get('path') if isinstance(f, dict) else f
            kind = f.get('type') if isinstance(f, dict) else None
            # 模式归属：脚本可逐文件指定 target_modes，否则默认只进视频模式（向后兼容）
            modes = f.get('target_modes') or f.get('modes') or ['video']
            group = f.get('group')
            collection_id = f.get('collection_id')
            meta = {
                'title': f.get('title'),
                'thumbnail': f.get('thumbnail') or (path if (isinstance(f, dict) and f.get('type') == 'image') else None),
                'duration': f.get('duration'),
                'caption': f.get('caption'),
                'source_url': f.get('source_url'),
            }
            if not path or not os.path.exists(path):
                continue
            # 若仍在临时目录，移动到资源库默认路径（shutil.move 支持跨盘）
            if os.path.abspath(path).startswith(os.path.abspath(working_dir)):
                if lib_path:
                    dest = os.path.join(lib_path, os.path.basename(path))
                else:
                    # 资源库未配置磁盘根目录时，落到稳定的持久目录，
                    # 否则文件留在临时目录、任务结束后被 _cleanup 删除导致网页打不开
                    base = os.path.join(self._data_dir(), 'ingested', str(library_id))
                    os.makedirs(base, exist_ok=True)
                    if os.path.isdir(path):
                        stem = group or os.path.splitext(os.path.basename(path))[0] or uuid.uuid4().hex[:8]
                        dest = os.path.join(base, str(stem))
                    else:
                        dest = os.path.join(base, os.path.basename(path))
                    # 避免同名冲突：追加数字后缀
                    if os.path.exists(dest):
                        i = 1
                        cand = f'{dest}_{i}'
                        while os.path.exists(cand):
                            i += 1
                            cand = f'{dest}_{i}'
                        dest = cand
                try:
                    if os.path.abspath(path) != os.path.abspath(dest):
                        os.makedirs(os.path.dirname(dest) or base, exist_ok=True)
                        shutil.move(path, dest)
                        path = dest
                except Exception as e:
                    self._append_log(job_id, 'error', f'移动文件失败: {e}')
                    continue
            res = ingest_file(library_id, path, self.app, kind, modes=modes,
                              collection_id=collection_id, meta=meta, user_id=owner_id,
                              hidden=bool(f.get('hidden')))
            self._append_log(job_id, 'info' if res.get('success') else 'error',
                             '入库: ' + res.get('message', ''))
            final_paths.append(path)
            # 收集帖子模式资源，用于聚合为帖子（组合模式）
            if res.get('success') and 'post' in (res.get('modes') or []):
                rid = res.get('resource_index_id')
                if rid:
                    gk = group or '_default_'
                    g = post_groups.setdefault(gk, {'title': f.get('post_title'),
                                                   'content': f.get('content'), 'ids': [],
                                                   'author_name': f.get('author_name'),
                                                   'author_url': f.get('author_url'),
                                                   'source_url': f.get('source_url')})
                    # 若组内尚未记录正文，用首个带 content 的文件填充
                    if not g.get('content') and f.get('content'):
                        g['content'] = f.get('content')
                    # 作者/源地址同组共享：取首个非空值
                    if not g.get('author_name') and f.get('author_name'):
                        g['author_name'] = f.get('author_name')
                    if not g.get('author_url') and f.get('author_url'):
                        g['author_url'] = f.get('author_url')
                    if not g.get('source_url') and f.get('source_url'):
                        g['source_url'] = f.get('source_url')
                    post_groups[gk]['ids'].append(rid)
        # 聚合帖子：同组资源合成一条帖子（例：图文+视频一体的下载）
        if post_groups:
            try:
                from platform_client import upsert_post_by_group
                for gk, g in post_groups.items():
                    if g['ids']:
                        gk_clean = gk if gk and gk != '_default_' else None
                        d = upsert_post_by_group(gk_clean,
                                                 g.get('title') or '',
                                                 g.get('content'), g['ids'], user_id=owner_id,
                                                 author_name=g.get('author_name'),
                                                 author_url=g.get('author_url'),
                                                 source_url=g.get('source_url'))
                        # 兼容不同返回形态：dict 或 ORM 对象
                        _pid = d.get('post_id') if isinstance(d, dict) else getattr(d, 'id', None)
                        self._append_log(job_id, 'info',
                                         f'已生成帖子 #{_pid}（{len(g["ids"])} 个资源）')
            except Exception as e:
                self._append_log(job_id, 'error', f'生成帖子失败: {e}')
        return final_paths

    # ---------- 取消 ----------
    def cancel(self, job_id):
        with self._lock:
            job = self._get_job_row(job_id)
            if not job:
                return False
            if job['status'] in ('success', 'failed', 'cancelled'):
                return False
            self._cancel[job_id] = True
            proc = self._procs.get(job_id)
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
        return True

    # ---------- 交互式输入 ----------
    def _set_awaiting(self, job_id, input_spec):
        spec = input_spec or {}
        with self._lock:
            self._input_events.pop(job_id, None)
            self._input_events[job_id] = threading.Event()
            self._input_responses.pop(job_id, None)
            self._db.execute(
                'UPDATE jobs SET status=?, awaiting=1, pending_input=?, updated_at=? WHERE id=?',
                ('awaiting_input', json.dumps(spec, ensure_ascii=False), _now(), job_id))
            self._db.commit()
        self._append_log(job_id, 'info', '脚本请求用户输入: ' + str(spec.get('prompt', '')))
        self._sync_task(job_id)

    def respond(self, job_id, value):
        """前端提交用户对脚本提问的答复。"""
        job = self._get_job_row(job_id)
        if not job:
            return False, '任务不存在'
        if job['status'] != 'awaiting_input':
            return False, '当前不在等待输入状态'
        with self._lock:
            self._input_responses[job_id] = value
            ev = self._input_events.get(job_id)
            if ev:
                ev.set()
            self._db.execute(
                'UPDATE jobs SET status=?, awaiting=0, input_response=?, updated_at=? WHERE id=?',
                ('running', json.dumps(value, ensure_ascii=False), _now(), job_id))
            self._db.commit()
        self._append_log(job_id, 'info', '用户已作出选择，继续运行')
        self._sync_task(job_id)
        return True, 'ok'

    def get_input(self, job_id, token, timeout=30):
        """脚本侧长轮询：阻塞至用户答复或超时（超时返回 (None, None) 让脚本重试）。"""
        job = self._get_job_row(job_id)
        if not job:
            return None, '任务不存在'
        if not token or token != job['token']:
            return None, '令牌无效'
        with self._lock:
            resp = self._input_responses.get(job_id)
            if resp is not None:
                del self._input_responses[job_id]
                return resp, None
            ev = self._input_events.setdefault(job_id, threading.Event())
        if self._cancel.get(job_id):
            return None, 'cancelled'
        ev.wait(timeout)
        with self._lock:
            resp = self._input_responses.get(job_id)
            if resp is not None:
                del self._input_responses[job_id]
                self._input_events.pop(job_id, None)
                return resp, None
        return None, None

    # ---------- 查询 ----------
    def get_job(self, job_id):
        job = self._get_job_row(job_id)
        if not job:
            return None
        logs = self._get_logs(job_id)
        return {
            'id': job['id'], 'script_id': job['script_id'], 'script_name': job['script_name'],
            'status': job['status'], 'progress': job['progress'],
            'params': json.loads(job['params']) if job['params'] else {},
            'result': json.loads(job['result']) if job['result'] else None,
            'library_id': job['library_id'], 'notified': bool(job['notified']),
            'error': job['error'], 'created_at': job['created_at'], 'updated_at': job['updated_at'],
            'awaiting': bool(job.get('awaiting')),
            'pending_input': json.loads(job['pending_input']) if job.get('pending_input') else None,
            'logs': logs,
        }

    def list_jobs(self, limit=50):
        with self._lock:
            rows = self._db.execute(
                'SELECT id, script_id, script_name, status, progress, created_at, updated_at '
                'FROM jobs ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
        return [
            {'id': r[0], 'script_id': r[1], 'script_name': r[2], 'status': r[3],
             'progress': r[4], 'created_at': r[5], 'updated_at': r[6]}
            for r in rows
        ]

    # ---------- DB 辅助 ----------
    def _insert_job(self, row):
        with self._lock:
            self._db.execute(
                'INSERT INTO jobs (id, script_id, script_name, status, progress, params, '
                'owner_id, token, working_dir, library_id, notified, error, created_at, updated_at) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (row['id'], row['script_id'], row['script_name'], row['status'], row['progress'],
                 row['params'], row['owner_id'], row['token'], row['working_dir'], row['library_id'],
                 row['notified'], row['error'], row['created_at'], row['updated_at']))
            self._db.commit()

    def _get_job_row(self, job_id):
        with self._lock:
            r = self._db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not r:
            return None
        # 使用 Row 工厂 -> 按列名访问，杜绝因 ALTER 追加列导致的顺序错位
        return dict(r)

    def _set_status(self, job_id, status):
        with self._lock:
            self._db.execute('UPDATE jobs SET status=?, updated_at=? WHERE id=?',
                             (status, _now(), job_id))
            self._db.commit()
        self._sync_task(job_id)

    def _finish(self, job_id, status, result=None, error=None):
        with self._lock:
            if result is not None:
                self._db.execute('UPDATE jobs SET status=?, progress=100, result=?, updated_at=? WHERE id=?',
                                 (status, result, _now(), job_id))
            else:
                self._db.execute('UPDATE jobs SET status=?, error=?, updated_at=? WHERE id=?',
                                 (status, error or '', _now(), job_id))
            self._db.commit()
        self._sync_task(job_id)

    def _is_notified(self, job_id):
        with self._lock:
            r = self._db.execute('SELECT notified FROM jobs WHERE id=?', (job_id,)).fetchone()
        return bool(r and r[0])

    def _append_log(self, job_id, level, message):
        with self._lock:
            self._db.execute('INSERT INTO job_logs (job_id, ts, level, message) VALUES (?,?,?,?)',
                             (job_id, _now(), level, message or ''))
            self._db.commit()

    def _get_logs(self, job_id):
        with self._lock:
            rows = self._db.execute(
                'SELECT level, message, ts FROM job_logs WHERE job_id=? ORDER BY id', (job_id,)).fetchall()
        return [{'level': r[0], 'message': r[1], 'ts': r[2]} for r in rows]


# 单例
mgr = ScriptJobManager()
