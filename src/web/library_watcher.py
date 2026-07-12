# -*- coding: utf-8 -*-
"""
视频库文件夹自动感知

监控视频库对应的磁盘文件夹，将文件系统的变化实时同步到 web 的 Video 表：
  - 新增视频文件        -> 计算内容指纹(hash) 后入库（UPSERT，已存在则跳过/更新）
  - 视频文件被删除      -> 从 Video 表移除对应记录
  - 视频文件名变动      -> 更新 local_path / file_name（保留点赞、收藏、历史等数据）

设计要点：
  - 直接操作用户可见的 Video 表，不依赖 resourced 的扫描/索引（两者 hash 算法不同，
    但 Video.local_path 与磁盘文件同源，可用路径关联）。
  - 监控路径优先从 resourced 查询（视频库/文件夹的磁盘路径），resourced 不可用时
    回退到从现有 Video.local_path 收集目录。
  - 监控方式：优先使用 watchdog（实时事件）；若环境未安装 watchdog，则自动回退到
    定时轮询目录 diff（同样覆盖新增/删除/重命名三种情况）。
  - 事件处理带「去抖」（cooldown），避免大文件复制过程中的反复触发。
"""

import os
import time
import threading
from datetime import datetime
from urllib.parse import quote

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = None


_DEFAULT_FORMATS = ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v']
_COOLDOWN = 2.0  # 文件事件去抖时间（秒）
_DEFAULT_POLL_INTERVAL = 30  # 轮询模式下的检查间隔（秒）


if WATCHDOG_AVAILABLE:
    class _VideoEventHandler(FileSystemEventHandler):
        """watchdog 事件处理器：把事件转发给 watcher，并标注所属视频库"""

        def __init__(self, watcher, library_id):
            super().__init__()
            self._watcher = watcher
            self._library_id = library_id

        def on_created(self, event):
            if event.is_directory:
                return
            self._watcher.schedule_upsert(event.src_path, self._library_id)

        def on_modified(self, event):
            if event.is_directory:
                return
            self._watcher.schedule_upsert(event.src_path, self._library_id)

        def on_deleted(self, event):
            if event.is_directory:
                return
            self._watcher.remove_video(event.src_path)

        def on_moved(self, event):
            if event.is_directory:
                return
            self._watcher.handle_moved(event.src_path, event.dest_path, self._library_id)
else:
    _VideoEventHandler = None


class VideoLibraryWatcher:
    def __init__(self, app, resource_bus=None, app_config=None, thumbnail_bus=None, log=None):
        self._app = app
        self._resource_bus = resource_bus
        self._app_config = app_config or {}
        self._thumbnail_bus = thumbnail_bus
        self._log = log
        self._formats = [f.lower() for f in self._app_config.get('supported_formats', _DEFAULT_FORMATS)]
        self._poll_interval = self._app_config.get('watch_poll_interval', _DEFAULT_POLL_INTERVAL)
        self._observers = {}          # norm_path -> Observer
        self._timers = {}             # path -> Timer（去抖）
        self._debounce = {}           # path -> 最近调度时间
        self._lock = threading.Lock()
        self._poll_thread = None
        self._stop_poll = threading.Event()

    # ---------- 工具 ----------
    def _is_video(self, path):
        return isinstance(path, str) and path.lower().endswith(tuple(self._formats))

    def _debug(self, level, msg):
        if self._log:
            try:
                self._log.debug(level, msg)
            except Exception:
                print(msg)
        else:
            print(msg)

    # ---------- 收集监控目标 ----------
    def _collect_watch_targets(self):
        """返回 [(root_path, web_library_id), ...]"""
        targets = []
        try:
            from core.models import VideoLibrary, Video

            with self._app.app_context():
                libraries = VideoLibrary.query.filter_by(is_active=True).all()
            name_to_web = {lib.name: lib.id for lib in libraries}

            res_libs = None
            if self._resource_bus:
                try:
                    res = self._resource_bus.call_method(
                        'com.dplayer.resourced', 'com.dplayer.Resourced',
                        'ListLibraries', {}, timeout=5000)
                    if res and res.get('success'):
                        res_libs = {rl['id']: rl for rl in res.get('libraries', [])}
                except Exception as e:
                    self._debug('WARN', f'[LibWatcher] 查询资源库失败，回退到本地路径: {e}')
                    res_libs = None

            if res_libs:
                self._debug('INFO', f'[LibWatcher] resourced 返回 {len(res_libs)} 个资源库')
                for rid, rl in res_libs.items():
                    web_id = name_to_web.get(rl.get('name'))
                    if web_id is None:
                        continue
                    paths = []
                    if rl.get('path'):
                        paths.append(rl['path'])
                    # 查询该库的文件夹
                    try:
                        fr = self._resource_bus.call_method(
                            'com.dplayer.resourced', 'com.dplayer.Resourced',
                            'ListFolders', {'library_id': rid}, timeout=5000)
                        if fr and fr.get('success'):
                            for f in fr.get('folders', []):
                                if f.get('path'):
                                    paths.append(f['path'])
                    except Exception:
                        pass
                    for p in paths:
                        if os.path.isdir(p):
                            targets.append((p, web_id))
                        else:
                            self._debug('WARN', f'[LibWatcher] 库路径不存在，跳过: {p}')

            # 回退：resourced 不可用或没有任何路径时，从现有 Video 收集目录
            if not targets:
                self._debug('INFO', '[LibWatcher] 回退模式：从现有 Video.local_path 收集监控目录')
                with self._app.app_context():
                    dirs = set()
                    for v in Video.query.filter(Video.local_path.isnot(None)).all():
                        d = os.path.dirname(v.local_path)
                        if d:
                            dirs.add(d)
                for d in dirs:
                    if os.path.isdir(d):
                        targets.append((d, None))
        except Exception as e:
            self._debug('ERROR', f'[LibWatcher] 收集监控目标失败: {e}')
        return targets

    # ---------- 启动 / 停止 ----------
    def start(self):
        targets = self._collect_watch_targets()
        if not targets:
            self._debug('INFO', '[LibWatcher] 没有可监控的视频库目录，自动感知未启动')
            return

        if WATCHDOG_AVAILABLE:
            seen = set()
            for root, lib_id in targets:
                norm = os.path.normcase(os.path.abspath(root))
                if norm in seen:
                    continue
                seen.add(norm)
                try:
                    handler = _VideoEventHandler(self, lib_id)
                    obs = Observer()
                    obs.schedule(handler, root, recursive=True)
                    obs.start()
                    self._observers[norm] = obs
                    self._debug('INFO', f'[LibWatcher] 开始监控(watchdog): {root} (library_id={lib_id})')
                except Exception as e:
                    self._debug('ERROR', f'[LibWatcher] 监控启动失败 {root}: {e}')
            # 启动后立即补齐一次（处理已存在但 Video 表缺失的文件）
            threading.Thread(target=self._diff_sync, args=(targets,),
                             daemon=True, name='lib-watcher-sync').start()
        else:
            self._debug('INFO', f'[LibWatcher] watchdog 不可用，使用定时轮询（间隔 {self._poll_interval}s）')
            self._stop_poll.clear()
            self._poll_thread = threading.Thread(
                target=self._poll_loop, args=(targets,), daemon=True, name='lib-watcher-poll')
            self._poll_thread.start()

    def _poll_loop(self, targets):
        # 首次立即同步一次，之后按间隔轮询
        self._diff_sync(targets)
        while not self._stop_poll.is_set():
            self._stop_poll.wait(self._poll_interval)
            if self._stop_poll.is_set():
                break
            try:
                self._diff_sync(targets)
            except Exception as e:
                self._debug('ERROR', f'[LibWatcher] 轮询同步失败: {e}')

    def stop_all(self):
        self._stop_poll.set()
        with self._lock:
            for path, obs in list(self._observers.items()):
                try:
                    obs.stop()
                    obs.join(timeout=2)
                except Exception:
                    pass
            self._observers.clear()
        for t in list(self._timers.values()):
            try:
                t.cancel()
            except Exception:
                pass
        self._timers.clear()
        self._debounce.clear()

    def is_watching(self):
        return len(self._observers) > 0 or (self._poll_thread is not None and self._poll_thread.is_alive())

    def watching_paths(self):
        return list(self._observers.keys())

    # ---------- 目录 diff（新增 / 重命名 / 删除）----------
    def _diff_sync(self, targets):
        """对比磁盘与 Video 表，处理新增、重命名、删除。用于初始补齐与轮询。"""
        try:
            from core.models import Video
            disk = {}   # norm_path -> (real_path, library_id)
            for root, lib_id in targets:
                for dirpath, _, files in os.walk(root):
                    for f in files:
                        if self._is_video(f):
                            p = os.path.join(dirpath, f)
                            disk[os.path.normcase(os.path.abspath(p))] = (p, lib_id)

            # 新增 / 重命名
            for np_norm, (p, lib_id) in disk.items():
                with self._app.app_context():
                    existing = Video.query.filter_by(local_path=p).first()
                if existing:
                    continue
                h = Video.generate_hash(p)
                with self._app.app_context():
                    by_hash = Video.query.filter_by(hash=h).first()
                if by_hash and by_hash.local_path != p:
                    # 同一内容出现在新路径 -> 视为重命名
                    self.rename_video(by_hash.local_path, p)
                else:
                    self.upsert_video(p, lib_id)

            # 删除：DB 中 local_path 位于任一监控 root 下，但磁盘已不存在
            roots_norm = [os.path.normcase(os.path.abspath(r)) for r, _ in targets]
            with self._app.app_context():
                for v in Video.query.filter(Video.local_path.isnot(None)).all():
                    np = os.path.normcase(os.path.abspath(v.local_path))
                    if np in disk:
                        continue
                    if any(np == rn or np.startswith(rn + os.sep) for rn in roots_norm):
                        self.remove_video(v.local_path)
        except Exception as e:
            self._debug('ERROR', f'[LibWatcher] diff 同步失败: {e}')

    # ---------- 实时事件（watchdog 模式）----------
    def schedule_upsert(self, path, library_id):
        """去抖：文件稳定 cooldown 秒后再处理，避免复制/写入过程中的反复触发"""
        if not self._is_video(path):
            return
        self._debounce[path] = time.time()
        old = self._timers.pop(path, None)
        if old:
            try:
                old.cancel()
            except Exception:
                pass
        t = threading.Timer(_COOLDOWN, self._delayed_upsert, args=(path, library_id))
        t.daemon = True
        t.start()
        self._timers[path] = t

    def _delayed_upsert(self, path, library_id):
        self._timers.pop(path, None)
        self._debounce.pop(path, None)
        self.upsert_video(path, library_id)

    def handle_moved(self, src, dest, library_id):
        if self._is_video(dest):
            self.rename_video(src, dest)
        elif self._is_video(src):
            # 移出库目录
            self.remove_video(src)

    # ---------- 核心同步逻辑 ----------
    def upsert_video(self, path, library_id):
        if not path or not os.path.isfile(path):
            return
        if not self._is_video(path):
            return
        try:
            from core.models import db, Video, Tag, VideoTag
            with self._app.app_context():
                vhash = Video.generate_hash(path)
                existing = Video.query.filter_by(local_path=path).first()
                if existing is None:
                    existing = Video.query.filter_by(hash=vhash).first()
                is_new = existing is None

                if existing:
                    # 内容或路径变化：刷新指纹与路径，保留用户改过的标题与互动数据
                    existing.local_path = path
                    existing.file_name = os.path.basename(path)
                    existing.hash = vhash
                    existing.url = f'/local_video/{quote(path.replace(chr(92), "/"), safe=":/")}'
                    existing.updated_at = datetime.utcnow()
                else:
                    title = os.path.splitext(os.path.basename(path))[0]
                    existing = Video(
                        hash=vhash,
                        title=title,
                        description=f'本地视频: {os.path.basename(path)}',
                        url=f'/local_video/{quote(path.replace(chr(92), "/"), safe=":/")}',
                        thumbnail=f'/thumbnail/{vhash}',
                        is_downloaded=True,
                        local_path=path,
                        file_name=os.path.basename(path),
                        library_id=library_id,
                        priority=self._app_config.get('default_priority', 0),
                    )
                    db.session.add(existing)
                    db.session.flush()
                    # 默认标签（与扫描逻辑一致）
                    for tag_name in self._app_config.get('default_tags', ['本地视频']):
                        tag = Tag.query.filter_by(name=tag_name).first()
                        if not tag:
                            tag = Tag(name=tag_name, category='类型')
                            tag.path = f'/{tag_name}'
                            db.session.add(tag)
                            db.session.flush()
                        db.session.add(VideoTag(video_id=existing.id, tag_id=tag.id))

                db.session.commit()

                if is_new and self._thumbnail_bus:
                    try:
                        self._thumbnail_bus.call_method(
                            'com.dplayer.thumbnaild', 'com.dplayer.Thumbnaild', 'Generate',
                            {'video_path': path, 'video_hash': vhash, 'output_format': 'gif'})
                    except Exception:
                        pass

                self._debug('INFO', f'[LibWatcher] {"新增" if is_new else "更新"}视频: {path}')
        except Exception as e:
            self._debug('ERROR', f'[LibWatcher] 同步视频失败 {path}: {e}')

    def remove_video(self, path):
        if not self._is_video(path):
            return
        try:
            from core.models import db, Video
            with self._app.app_context():
                v = Video.query.filter_by(local_path=path).first()
                if v:
                    db.session.delete(v)
                    db.session.commit()
                    self._debug('INFO', f'[LibWatcher] 删除视频: {path}')
        except Exception as e:
            self._debug('ERROR', f'[LibWatcher] 删除视频失败 {path}: {e}')

    def rename_video(self, src, dest):
        if not self._is_video(dest):
            return
        try:
            from core.models import db, Video
            with self._app.app_context():
                v = Video.query.filter_by(local_path=src).first()
                if v:
                    v.local_path = dest
                    v.file_name = os.path.basename(dest)
                    v.url = f'/local_video/{quote(dest.replace(chr(92), "/"), safe=":/")}'
                    v.updated_at = datetime.utcnow()
                    db.session.commit()
                    self._debug('INFO', f'[LibWatcher] 重命名: {src} -> {dest}')
        except Exception as e:
            self._debug('ERROR', f'[LibWatcher] 重命名失败 {src} -> {dest}: {e}')


# 模块级单例
_watcher_instance = None


def start_library_watchers(app, resource_bus=None, app_config=None, thumbnail_bus=None, log=None):
    """创建（或重建）监控器并启动。重复调用会先停止旧实例。"""
    global _watcher_instance
    if _watcher_instance is not None:
        try:
            _watcher_instance.stop_all()
        except Exception:
            pass
    _watcher_instance = VideoLibraryWatcher(app, resource_bus, app_config, thumbnail_bus, log)
    _watcher_instance.start()
    return _watcher_instance


def get_watcher():
    return _watcher_instance
