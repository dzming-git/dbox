# -*- coding: utf-8 -*-
"""
资源库文件夹自动感知

监控资源库对应的磁盘文件夹，将文件系统的变化实时同步到 web 的 Video 表：
  - 新增视频文件        -> 计算内容指纹(hash) 后入库（UPSERT，已存在则跳过/更新）
  - 视频文件被删除      -> 从 Video 表移除对应记录
  - 视频文件名变动      -> 更新 local_path / file_name（保留点赞、收藏、历史等数据）

设计要点：
  - 直接操作用户可见的 Video 表，不依赖 resourced 的扫描/索引（两者 hash 算法不同，
    但 Video.local_path 与磁盘文件同源，可用路径关联）。
  - 监控路径优先从 resourced 查询（资源库/文件夹的磁盘路径），resourced 不可用时
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

# 图集相关
_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif')
_GALLERY_COOLDOWN = 8.0  # 图集重扫去抖时间（秒，重于视频，避免大批量复制期间反复全扫）


if WATCHDOG_AVAILABLE:
    class _VideoEventHandler(FileSystemEventHandler):
        """watchdog 事件处理器：把事件转发给 watcher，并标注所属资源库"""

        def __init__(self, watcher, library_id):
            super().__init__()
            self._watcher = watcher
            self._library_id = library_id

        def on_created(self, event):
            if event.is_directory:
                # 新目录 = 可能是新图集文件夹
                self._watcher.schedule_gallery_scan(self._library_id)
                return
            if self._watcher._is_image(event.src_path):
                # 新图片 = 可能是图集新增页
                self._watcher.schedule_gallery_scan(self._library_id)
            self._watcher.schedule_upsert(event.src_path, self._library_id)

        def on_modified(self, event):
            if event.is_directory:
                # 目录内容变动（如整批复制完成）
                self._watcher.schedule_gallery_scan(self._library_id)
                return
            if self._watcher._is_image(event.src_path):
                self._watcher.schedule_gallery_scan(self._library_id)
            self._watcher.schedule_upsert(event.src_path, self._library_id)

        def on_deleted(self, event):
            if event.is_directory:
                self._watcher.schedule_gallery_scan(self._library_id)
                return
            if self._watcher._is_image(event.src_path):
                self._watcher.schedule_gallery_scan(self._library_id)
            self._watcher.remove_video(event.src_path)

        def on_moved(self, event):
            if event.is_directory:
                self._watcher.schedule_gallery_scan(self._library_id)
                return
            if self._watcher._is_image(event.src_path) or self._watcher._is_image(event.dest_path):
                self._watcher.schedule_gallery_scan(self._library_id)
            self._watcher.handle_moved(event.src_path, event.dest_path, self._library_id)
else:
    _VideoEventHandler = None


class ResourceLibraryWatcher:
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
        self._gallery_timers = {}       # library_id -> Timer（图集重扫去抖）
        self._last_scan_epoch = 0.0     # 最近一次全量/增量扫描成功的 epoch（用于增量剪枝）

    # ---------- 工具 ----------
    def _is_video(self, path):
        return isinstance(path, str) and path.lower().endswith(tuple(self._formats))

    def _is_image(self, path):
        return isinstance(path, str) and path.lower().endswith(_IMAGE_EXTS)

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
            from core.models import ResourceLibrary, Video

            with self._app.app_context():
                libraries = ResourceLibrary.query.filter_by(is_active=True).all()
            name_to_web = {lib.name: lib.id for lib in libraries}

            res_libs = None
            if self._resource_bus:
                try:
                    res = self._resource_bus.call_method(
                        'com.dbox.resourced', 'com.dbox.Resourced',
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
                            'com.dbox.resourced', 'com.dbox.Resourced',
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
                    for v in Video.query.filter(Video.resource_index_id.isnot(None)).all():
                        d = os.path.dirname(v.local_path)
                        if d:
                            dirs.add(d)
                for d in dirs:
                    if os.path.isdir(d):
                        targets.append((d, None))
        except Exception as e:
            self._debug('ERROR', f'[LibWatcher] 收集监控目标失败: {e}')
        return targets

    # ---------- 单库扫描（驱动 Video 索引）----------
    def _targets_for_library(self, library_id: int):
        """返回该 web 资源库对应的磁盘监控目标 [(path, library_id)]。

        路径来源：resourced 中同名库的 path + 其文件夹 path（与 _collect_watch_targets 同源）。
        """
        targets = []
        try:
            from core.models import ResourceLibrary
            with self._app.app_context():
                lib = ResourceLibrary.query.get(library_id)
                if not lib:
                    return targets
                name = lib.name
            res_libs = None
            if self._resource_bus:
                try:
                    res = self._resource_bus.call_method(
                        'com.dbox.resourced', 'com.dbox.Resourced',
                        'ListLibraries', {}, timeout=5000)
                    if res and res.get('success'):
                        res_libs = {rl['name']: rl for rl in res.get('libraries', [])}
                except Exception as e:
                    self._debug('WARN', f'[LibWatcher] 查询资源库失败: {e}')
                    res_libs = None
            rl = res_libs.get(name) if res_libs else None
            paths = []
            if rl:
                if rl.get('path'):
                    paths.append(rl['path'])
                try:
                    fr = self._resource_bus.call_method(
                        'com.dbox.resourced', 'com.dbox.Resourced',
                        'ListFolders', {'library_id': rl['id']}, timeout=5000)
                    if fr and fr.get('success'):
                        for f in fr.get('folders', []):
                            if f.get('path'):
                                paths.append(f['path'])
                except Exception:
                    pass
            for p in paths:
                if os.path.isdir(p):
                    targets.append((p, library_id))
                else:
                    self._debug('WARN', f'[LibWatcher] 库路径不存在，跳过: {p}')
        except Exception as e:
            self._debug('ERROR', f'[LibWatcher] 收集库 {library_id} 目标失败: {e}')
        return targets

    def scan_library(self, library_id: int):
        """对单个资源库执行全量同步：磁盘 -> Video 表（web 唯一索引源）。

        新增/更新/重命名/删除均复用已验证的 _diff_sync。只针对该库监控目标，
        不会误删其它库。返回实际扫描的目录数。
        """
        targets = self._targets_for_library(library_id)
        if not targets:
            self._debug('WARN', f'[LibWatcher] 库 {library_id} 没有可扫描的目录')
            return 0
        # 管理员主动的全量/单库扫描：强制把标题对齐为文件名，让索引与磁盘一致
        self._diff_sync(targets, refresh_title=True)
        return len(targets)

    def library_disk_targets(self, library_id: int):
        """返回该资源库在磁盘上的监控根目录列表（供图集等扫描复用）。"""
        return [p for p, _ in self._targets_for_library(library_id)]

    # ---------- 启动 / 停止 ----------
    def start(self):
        targets = self._collect_watch_targets()
        if not targets:
            self._debug('INFO', '[LibWatcher] 没有可监控的资源库目录，自动感知未启动')
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
            # 启动后立即补齐一次（处理已存在但 Video 表缺失的文件 + 图集初始入库）
            threading.Thread(target=self._initial_sync, args=(targets,),
                             daemon=True, name='lib-watcher-sync').start()
        else:
            self._debug('INFO', f'[LibWatcher] watchdog 不可用，使用定时轮询（间隔 {self._poll_interval}s）')
            self._stop_poll.clear()
            self._poll_thread = threading.Thread(
                target=self._poll_loop, args=(targets,), daemon=True, name='lib-watcher-poll')
            self._poll_thread.start()

    def _initial_sync(self, targets):
        """启动补齐：视频 diff + 各库图集首次扫描。

        完成后写入 _last_scan_epoch，作为后续增量扫描的基线时间戳。
        """
        self._diff_sync(targets, mode='full')
        self._last_scan_epoch = time.time()
        for lib_id in {lib_id for _, lib_id in targets if lib_id is not None}:
            self._delayed_gallery_scan(lib_id)

    def full_scan_once(self):
        """一次性全量扫描（不启动后台监控），供启动时自动扫描开关调用。

        收集所有监控目标后执行一次 diff 同步 + 各库图集扫描，使 Video 表与磁盘一致。
        """
        targets = self._collect_watch_targets()
        if not targets:
            self._debug('INFO', '[LibWatcher] 没有可扫描的目标，跳过全量扫描')
            return
        self._diff_sync(targets)
        for lib_id in {lib_id for _, lib_id in targets if lib_id is not None}:
            self._delayed_gallery_scan(lib_id)
        self._debug('INFO', f'[LibWatcher] 全量扫描完成，共 {len(targets)} 个目标目录')

    def _poll_loop(self, targets):
        # 首次立即同步一次，之后按间隔轮询
        self._diff_sync(targets)
        for lib_id in {lib_id for _, lib_id in targets if lib_id is not None}:
            self._delayed_gallery_scan(lib_id)
        while not self._stop_poll.is_set():
            self._stop_poll.wait(self._poll_interval)
            if self._stop_poll.is_set():
                break
            try:
                self._diff_sync(targets)
                for lib_id in {lib_id for _, lib_id in targets if lib_id is not None}:
                    self._delayed_gallery_scan(lib_id)
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
        for t in list(self._gallery_timers.values()):
            try:
                t.cancel()
            except Exception:
                pass
        self._gallery_timers.clear()

    def is_watching(self):
        return len(self._observers) > 0 or (self._poll_thread is not None and self._poll_thread.is_alive())

    def watching_paths(self):
        return list(self._observers.keys())

    # ---------- 目录 diff（新增 / 重命名 / 删除）----------
    def _collect_disk_videos(self, root, lib_id, since_epoch=0.0):
        """用 scandir 递归收集 root 下的视频文件。

        since_epoch > 0 时启用**增量剪枝**：跳过 mtime 早于该时间戳的目录
        （这些目录自上次扫描以来没有变化，无需进入枚举），大幅减少磁盘 IO。
        返回 {norm_path: (real_path, library_id)}。
        """
        found = {}
        try:
            stack = [root]
            while stack:
                cur = stack.pop()
                try:
                    with os.scandir(cur) as it:
                        for entry in it:
                            try:
                                if entry.is_dir(follow_symlinks=False):
                                    # 增量剪枝：目录 mtime 早于 since 则整目录跳过
                                    if since_epoch > 0:
                                        try:
                                            if entry.stat(follow_symlinks=False).st_mtime < since_epoch:
                                                continue
                                        except OSError:
                                            pass
                                    stack.append(entry.path)
                                elif entry.is_file(follow_symlinks=False) and self._is_video(entry.name):
                                    p = os.path.abspath(entry.path)
                                    found[os.path.normcase(p)] = (p, lib_id)
                            except (OSError, PermissionError):
                                continue
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError):
            pass
        return found

    def _diff_sync(self, targets, mode='full'):
        """对比磁盘与 Video 表，处理新增、重命名、删除。用于初始补齐与轮询。

        title 与 file_name 解耦：已存在视频仅同步 file_name / url / 内容指纹等
        物理信息，绝不修改 title（标题由管理员在编辑界面维护，可一键“同步文件名”）。
        仅在新增视频时把 title 初始化为文件名（去扩展名）。

        mode:
          'full'   —— 全量枚举磁盘并 diff（原行为，慢，仅小库/数据不一致时使用）
          'incremental' —— 仅枚举自 _last_scan_epoch 以来 mtime 变化的目录，
                           只处理新增/改名/删除，最快的日常同步策略
          'verify' —— 仅校验 DB 孤儿：清理磁盘已不存在的视频，不枚举磁盘新增文件
        """
        try:
            from core.models import Video, ResourceIndex
            incremental = (mode == 'incremental')
            verify_only = (mode == 'verify')
            since = self._last_scan_epoch if incremental else 0.0

            disk = {}
            if not verify_only:
                for root, lib_id in targets:
                    disk.update(self._collect_disk_videos(root, lib_id, since_epoch=since))

            # 新增 / 重命名 / 文件名对齐（仅更新物理信息，不动 title）
            if not verify_only:
                self._debug('INFO', f'[LibWatcher] diff({mode}) 开始，磁盘文件数 {len(disk)}')
                for np_norm, (p, lib_id) in disk.items():
                    with self._app.app_context():
                        existing = Video.query.join(ResourceIndex).filter(ResourceIndex.location == p).first()
                        if existing:
                            new_name = os.path.basename(p)
                            if existing.file_name != new_name:
                                # 磁盘文件名已变（软件未运行 / 旧逻辑漏更新）：
                                # 仅对齐 file_name / url / 内容指纹，不修改 title。
                                self._reconcile_fields(existing, p, new_name)
                            continue
                        h = Video.generate_hash(p)
                        by_hash = Video.query.filter_by(hash=h).first()
                        if by_hash and by_hash.local_path != p:
                            # 同一内容出现在新路径 -> 视为重命名
                            # 必须在 app_context 内访问 by_hash.local_path（property 触发 resource_index 懒加载）
                            self.rename_video(by_hash.local_path, p)
                        else:
                            self.upsert_video(p, lib_id)

            # 删除：DB 中 local_path 位于任一监控 root 下，但磁盘已不存在
            roots_norm = [os.path.normcase(os.path.abspath(r)) for r, _ in targets]
            with self._app.app_context():
                for v in Video.query.filter(Video.resource_index_id.isnot(None)).all():
                    np = os.path.normcase(os.path.abspath(v.local_path))
                    if not verify_only and np in disk:
                        continue
                    if any(np == rn or np.startswith(rn + os.sep) for rn in roots_norm):
                        self.remove_video(v.local_path)

            # 记录成功扫描时间，供后续增量剪枝使用
            if mode != 'verify':
                self._last_scan_epoch = time.time()
        except Exception as e:
            self._debug('ERROR', f'[LibWatcher] diff({mode}) 同步失败: {e}')

    # ---------- 单库扫描（对外 API，支持模式）----------
    def scan_library(self, library_id, mode='incremental'):
        """对单个 web 资源库执行扫描/同步。

        mode 透传给 _diff_sync：'incremental'（默认，快）/ 'full' / 'verify'。
        返回 (added, updated, removed) 计数。
        """
        try:
            targets = self._targets_for_library(library_id)
            if not targets:
                self._debug('WARN', f'[LibWatcher] 库 {library_id} 无可扫描目标')
                return (0, 0, 0)
            before = self._count_videos(targets)
            self._diff_sync(targets, mode=mode)
            after = self._count_videos(targets)
            added = max(0, after - before)
            removed = max(0, before - after)
            self._debug('INFO', f'[LibWatcher] 扫描库 {library_id}({mode}) 完成: '
                                f'新增≈{added} 移除≈{removed}')
            return (added, 0, removed)
        except Exception as e:
            self._debug('ERROR', f'[LibWatcher] 扫描库 {library_id} 失败: {e}')
            return (0, 0, 0)

    def _count_videos(self, targets):
        try:
            from core.models import Video, ResourceIndex
            with self._app.app_context():
                cnt = 0
                for _, lib_id in targets:
                    if lib_id is not None:
                        cnt += Video.query.filter_by(library_id=lib_id).count()
                return cnt
        except Exception:
            return 0

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

    # ---------- 图集重扫（去抖）----------
    def schedule_gallery_scan(self, library_id):
        """去抖：某库目录下发生图片/目录变动后，冷却一段时间再对整库图集重扫。"""
        if library_id is None:
            return
        old = self._gallery_timers.pop(library_id, None)
        if old:
            try:
                old.cancel()
            except Exception:
                pass
        t = threading.Timer(_GALLERY_COOLDOWN, self._delayed_gallery_scan, args=(library_id,))
        t.daemon = True
        t.start()
        self._gallery_timers[library_id] = t

    def _delayed_gallery_scan(self, library_id):
        self._gallery_timers.pop(library_id, None)
        try:
            # 延迟导入，避免与 gallery.scanner 形成循环依赖
            from backend.gallery.scanner import scan_library_galleries
            with self._app.app_context():
                res = scan_library_galleries(library_id, self._app, log=self._log)
            if res.get('success'):
                self._debug('INFO', f'[LibWatcher] 图集自动重扫 库{library_id}: '
                                    f'新增{res.get("added")} 更新{res.get("updated")} '
                                    f'清理{res.get("removed")} 现存{res.get("total")}')
            else:
                self._debug('WARN', f'[LibWatcher] 图集自动重扫跳过 库{library_id}: {res.get("message")}')
        except Exception as e:
            self._debug('ERROR', f'[LibWatcher] 图集自动重扫失败 库{library_id}: {e}')

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
            from core.models import db, Video, Tag, VideoTag, ResourceIndex
            with self._app.app_context():
                vhash = Video.generate_hash(path)
                existing = Video.query.join(ResourceIndex).filter(ResourceIndex.location == path).first()
                if existing is None:
                    existing = Video.query.filter_by(hash=vhash).first()
                is_new = existing is None

                if existing:
                    # 内容或路径变化：仅刷新指纹与路径等物理信息，不修改 title
                    # （标题与文件名解耦，由管理员在编辑界面维护）。
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
                    for tag_name in self._app_config.get('default_tags', []):
                        tag = Tag.query.filter_by(name=tag_name).first()
                        if not tag:
                            tag = Tag(name=tag_name, category='类型')
                            tag.path = f'/{tag_name}'
                            db.session.add(tag)
                            db.session.flush()
                        db.session.add(VideoTag(video_id=existing.id, tag_id=tag.id))

                db.session.commit()

                # 统一封面入口：确保资源索引封面与视频缩略图一致（首次启动后 resource_index 已存在）
                if existing.resource_index and not existing.resource_index.cover:
                    existing.resource_index.cover = existing.thumbnail or f'/thumbnail/{vhash}'
                    db.session.commit()

                if is_new and self._thumbnail_bus:
                    try:
                        output_format = self._app_config.get('thumbnails', {}).get('output_format', 'sprite')
                        self._thumbnail_bus.call_method(
                            'com.dbox.thumbnaild', 'com.dbox.Thumbnaild', 'Generate',
                            {'video_path': path, 'video_hash': vhash, 'output_format': output_format})
                    except Exception:
                        pass

                self._debug('INFO', f'[LibWatcher] {"新增" if is_new else "更新"}视频: {path}')
        except Exception as e:
            self._debug('ERROR', f'[LibWatcher] 同步视频失败 {path}: {e}')

    def remove_video(self, path):
        if not self._is_video(path):
            return
        try:
            from core.models import db, Video, ResourceIndex
            with self._app.app_context():
                v = Video.query.join(ResourceIndex).filter(ResourceIndex.location == path).first()
                if v:
                    db.session.delete(v)
                    db.session.commit()
                    self._debug('INFO', f'[LibWatcher] 删除视频: {path}')
        except Exception as e:
            self._debug('ERROR', f'[LibWatcher] 删除视频失败 {path}: {e}')

    def _reconcile_fields(self, v, path, new_name):
        """磁盘文件名与 DB 不一致时，仅对齐 file_name / url / 内容指纹等物理信息。

        不修改 title：标题与文件名解耦，由管理员在编辑界面维护（可一键“同步文件名”）。
        """
        try:
            from core.models import db, Video
            v.file_name = new_name
            # 同步真实磁盘路径（resource_index.location），否则播放路径仍指向旧文件名导致 404
            v.local_path = path
            try:
                v.hash = Video.generate_hash(path)
            except Exception as e:
                self._debug('WARN', f'[LibWatcher] 重新计算指纹失败 {path}: {e}')
            v.url = f'/local_video/{quote(path.replace(chr(92), "/"), safe=":/")}'
            v.updated_at = datetime.utcnow()
            db.session.commit()
            self._debug('INFO', f'[LibWatcher] 对齐文件名: {path} -> {new_name}')
        except Exception as e:
            self._debug('ERROR', f'[LibWatcher] 对齐文件名失败 {path}: {e}')

    def rename_video(self, src, dest):
        if not self._is_video(dest):
            return
        try:
            from core.models import db, Video, ResourceIndex
            with self._app.app_context():
                v = Video.query.join(ResourceIndex).filter(ResourceIndex.location == src).first()
                if v:
                    new_name = os.path.basename(dest)
                    # 仅更新路径等物理信息，不修改 title（标题与文件名解耦）。
                    v.local_path = dest
                    v.file_name = new_name
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
    _watcher_instance = ResourceLibraryWatcher(app, resource_bus, app_config, thumbnail_bus, log)
    _watcher_instance.start()
    return _watcher_instance


def get_watcher():
    return _watcher_instance
