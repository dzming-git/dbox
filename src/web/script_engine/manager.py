"""外部脚本任务管理器：发现脚本、执行子进程、解析进度、持久化任务、入库通知。"""
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

from .manifest import load_all, scripts_base_dir
from .ingest import ingest_file

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
        self._state_path = None
        self._initialized = False

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
        self._db = sqlite3.connect(os.path.join(data_dir, 'script_jobs.db'),
                                   check_same_thread=False)
        self._init_db()
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.reload()
        self._initialized = True

    def _data_dir(self):
        env = os.environ.get('DPLAYER_DATA_DIR')
        if env:
            return env
        pkg_dir = os.path.dirname(os.path.abspath(__file__))    # src/web/script_engine
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(pkg_dir)))
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
            if p.get('required') and (name not in params or params[name] in (None, '')):
                return f'缺少必填参数: {p.get("label", name)}'
            if name not in params and 'default' in p:
                params[name] = p['default']
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
            from library_watcher import get_watcher
            w = get_watcher()
            if w:
                targets = w.library_disk_targets(lib_id)
                if targets:
                    return {'id': lib_id, 'type': sel.get('media_type', 'any'), 'path': targets[0]}
        except Exception:
            pass
        return {'id': lib_id, 'type': sel.get('media_type', 'any'), 'path': ''}

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
        }
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
        elif t == 'log':
            self._append_log(job_id, obj.get('level', 'info'), obj.get('message', ''))
        elif t == 'error':
            self._append_log(job_id, 'error', obj.get('message', ''))
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
            from library_watcher import get_watcher
            w = get_watcher()
            if w:
                targets = w.library_disk_targets(library_id)
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
            self._reported[job_id] = files or []
            self._db.execute('UPDATE jobs SET notified=1, updated_at=? WHERE id=?',
                             (_now(), job_id))
            self._db.commit()
        return True, '已记录待入库文件'

    def _reconcile(self, job_id, library_id, files):
        """把脚本产出文件从临时目录移动到资源库路径（跨盘安全），再入库。

        返回移动后的最终路径列表。
        """
        final_paths = []
        if not library_id:
            return final_paths
        lib = self._lib_ctx(library_id)
        lib_path = lib[0]['path'] if lib else ''
        working_dir = self._get_job_row(job_id)['working_dir']
        for f in files:
            path = f.get('path') if isinstance(f, dict) else f
            kind = f.get('type') if isinstance(f, dict) else None
            if not path or not os.path.exists(path):
                continue
            # 若仍在临时目录，移动到资源库默认路径（shutil.move 支持跨盘）
            if lib_path and os.path.abspath(path).startswith(os.path.abspath(working_dir)):
                dest = os.path.join(lib_path, os.path.basename(path))
                try:
                    if os.path.abspath(path) != os.path.abspath(dest):
                        os.makedirs(lib_path, exist_ok=True)
                        shutil.move(path, dest)
                        path = dest
                except Exception as e:
                    self._append_log(job_id, 'error', f'移动文件失败: {e}')
                    continue
            res = ingest_file(library_id, path, self.app, kind)
            self._append_log(job_id, 'info' if res.get('success') else 'error',
                             '入库: ' + res.get('message', ''))
            final_paths.append(path)
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
        cols = ['id', 'script_id', 'script_name', 'status', 'progress', 'params', 'result',
                'owner_id', 'token', 'working_dir', 'library_id', 'notified', 'error',
                'created_at', 'updated_at']
        return dict(zip(cols, r))

    def _set_status(self, job_id, status):
        with self._lock:
            self._db.execute('UPDATE jobs SET status=?, updated_at=? WHERE id=?',
                             (status, _now(), job_id))
            self._db.commit()

    def _finish(self, job_id, status, result=None, error=None):
        with self._lock:
            if result is not None:
                self._db.execute('UPDATE jobs SET status=?, progress=100, result=?, updated_at=? WHERE id=?',
                                 (status, result, _now(), job_id))
            else:
                self._db.execute('UPDATE jobs SET status=?, error=?, updated_at=? WHERE id=?',
                                 (status, error or '', _now(), job_id))
            self._db.commit()

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
