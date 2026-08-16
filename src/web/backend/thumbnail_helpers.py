# -*- coding: utf-8 -*-
"""缩略图管理辅助函数。

从 main.py 下沉而来，供 thumbnail_api 蓝图直接 import。

需要运行时单例（thumbnail_bus / db / _DATA_DIR）的地方，统一从
backend.runtime 读取。
"""
import os
import json
import threading

from liblog import get_service_logger

log = get_service_logger('dbox-web')
from backend.runtime import runtime

from backend.paths import DATA_DIR, THUMB_CONFIG_FILE

# 缩略图文件扩展名集合（含 sprite 雪碧图与 vtt 预览索引）。
# gif = 动图缩略（可配置生成的备选格式），jpg = 静态 poster，png = 静态回退，
# sprite.jpg = 雪碧图，vtt = 预览坐标索引。
THUMB_EXTENSIONS = ('gif', 'jpg', 'png', 'vtt')

# 默认缩略图配置
_DEFAULT_THUMB_CONFIG = {
    'auto_generate': False,
    'max_workers': 2,
    'task_interval': 3,
    'auto_generate_interval': 3600,
    # 默认生成的缩略图格式：sprite（雪碧图 + vtt 悬停预览）为默认值，
    # 可选值：sprite / gif / jpg / png。调用方未显式指定 output_format 时统一读此配置。
    'output_format': 'sprite',
    # 悬停预览（sprite 雪碧图）采样参数：
    # head_skip / tail_skip      —— 跳过片头/片尾的比例（0~0.5），保证预览内容有代表性
    # sample_points              —— 兼容旧配置的总帧数参考（片段式采样下实际总帧数由片段参数推导）
    # sprite_cols                —— 雪碧图每行帧数（行数 = ceil(总帧数 / sprite_cols)）
    # sprite_long_edge           —— 单帧长边像素（短边按源视频宽高比自动推导）
    # segment_count / frames_per_segment —— 片段式采样：在 segment_count 个关键时间点各密集抽
    #                            frames_per_segment 帧，片段内构成几秒连续动作，片段间跳转
    # segment_frame_gap          —— 片段内相邻帧的间隔秒数（越大片段持续时间越长）
    'preview': {
        'enabled': True,
        'head_skip': 0.08,
        'tail_skip': 0.08,
        'sample_points': 12,
        'sprite_cols': 4,
        'sprite_long_edge': 180,
        'segment_count': 4,
        'frames_per_segment': 3,
        'segment_frame_gap': 0.4,
    },
}

# 自动生成后台线程控制
_thumb_auto_thread = None
_thumb_auto_stop_event = threading.Event()

# 自动生成进度快照（供前端轮询展示）
_thumb_progress = {
    'running': False,
    'total': 0,
    'processed': 0,
    'success': 0,
    'failed': 0,
    'current': '',
    'started_at': None,
    'finished_at': None,
}


def get_auto_generate_progress():
    """返回当前自动生成进度快照。

    进度以 thumbnaild 的真实执行结果（GetMetrics）为准，解决「web 端只统计
    下发成功数、与 thumbnaild 实际产出脱钩」导致面板一直显示 0/0 的问题。
    web 自身统计的 success（下发成功数）仅作辅助参考。
    """
    snap = dict(_thumb_progress)
    # 优先用 thumbnaild 的真实执行计数覆盖，确保监控位置与生成位置统一
    try:
        bus = runtime.thumbnail_bus
        if bus is not None:
            m = bus.call_method(
                'com.dbox.thumbnaild', 'com.dbox.Thumbnaild', 'GetMetrics', {}, timeout=3000
            )
            if isinstance(m, dict) and 'total' in m:
                total = m.get('total', 0)
                completed = m.get('completed', 0)
                failed = m.get('failed', 0)
                active = m.get('active', 0)
                queue = m.get('queue', 0)
                snap['total'] = total
                snap['success'] = completed          # 真实生成成功数
                snap['failed'] = failed               # 真实生成失败数
                snap['pending'] = active + queue      # 进行中 + 排队中
                snap['processed'] = completed + failed
    except Exception:
        # thumbnaild 不可达时退回 web 自身统计，不阻塞进度查询
        pass
    return snap


def _load_thumb_config():
    """加载缩略图配置"""
    try:
        if os.path.exists(THUMB_CONFIG_FILE):
            with open(THUMB_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            merged = {**_DEFAULT_THUMB_CONFIG, **config}
            return merged
    except Exception as e:
        log.debug('ERROR', f'加载缩略图配置失败: {e}')
    return {**_DEFAULT_THUMB_CONFIG}


def _save_thumb_config(config):
    """保存缩略图配置"""
    try:
        os.makedirs(os.path.dirname(THUMB_CONFIG_FILE), exist_ok=True)
        with open(THUMB_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        log.debug('ERROR', f'保存缩略图配置失败: {e}')
        return False


def _start_auto_generate(config=None, app=None):
    """启动自动生成缩略图后台线程"""
    global _thumb_auto_thread

    if config is None:
        config = _load_thumb_config()

    _thumb_auto_stop_event.clear()

    def _auto_generate_worker():
        log.maintenance('INFO', '缩略图自动生成线程已启动')

        while not _thumb_auto_stop_event.is_set():
            try:
                if app is not None:
                    with app.app_context():
                        _generate_missing_thumbnails(config)
                else:
                    _generate_missing_thumbnails(config)
            except Exception as e:
                log.debug('ERROR', f'自动生成缩略图出错: {e}')

            _thumb_progress['running'] = False
            _thumb_progress['finished_at'] = __import__('time').time()
            _thumb_auto_stop_event.wait(config.get('auto_generate_interval', 3600))

        log.maintenance('INFO', '缩略图自动生成线程已停止')

    _thumb_auto_thread = threading.Thread(target=_auto_generate_worker, daemon=True)
    _thumb_auto_thread.start()


def _get_visible_library_ids():
    """返回当前「已激活」资源库的 ID 列表，不依赖请求上下文。

    设计原则：资源库管理服务（ResourceLibrary.is_active）掌控着资源的对外出口，
    缩略图的统计与生成应只针对已激活资源库下的资源，而非扫描全部资源库。
    本函数直接读取 is_active，可在后台线程（自动生成）中安全调用，避免了
    access.get_allowed_library_ids() 依赖请求上下文、在子线程中不可用的问题。
    """
    try:
        from core.models import ResourceLibrary
        return [lib.id for lib in ResourceLibrary.query.filter_by(is_active=True).all()]
    except Exception as e:
        log.debug('ERROR', f'获取已激活资源库失败: {e}')
        return []


# 判定某字符串是否为「封面服务 URL / 路由」而非本地文件路径。
# 缩略图服务只负责把图生成进「默认文件夹」，但每张资源都有自己的索引
# （ResourceIndex），索引可通过 meta.thumbnail / cover 规定该资源缩略图的
# 实际路径——可以指向默认文件夹，也可以指向别处。因此判断「资源有没有
# 缩略图、缩略图在哪」必须以资源索引为准，而不是去扫描默认文件夹再按 hash 反推。
_URL_PREFIXES = ('http://', 'https://', '/thumbnail/', '/gallery-cover/', 'data:', 'blob:')


def _is_url_like(value):
    if not isinstance(value, str) or not value:
        return True
    return value.startswith(_URL_PREFIXES)


def resolve_thumbnail_path_for_video(video):
    """返回某视频「索引文件所规定的」缩略图磁盘路径（绝对路径，或 None）。

    解析优先级：
      1) ResourceIndex.meta['thumbnail'] 为本地文件路径（绝对，或相对 DATA_DIR）→ 采用；
      2) ResourceIndex.cover 为本地文件路径（非服务 URL / 路由）→ 采用；
      3) 回退到默认文件夹下的 {hash}.{jpg|png|gif}（缩略图服务的默认落点）；
      4) 都没有 → None。

    调用方应结合 os.path.exists() 判定「是否真的有缩略图」——索引只规定路径，
    文件可能因为生成未完成 / 生成失败而尚不存在。
    """
    if not video or not getattr(video, 'hash', None):
        return None
    ri = getattr(video, 'resource_index', None)
    if ri is not None:
        try:
            m = ri.get_meta()
            tp = m.get('thumbnail')
            if tp and not _is_url_like(tp):
                cand = tp if os.path.isabs(tp) else os.path.join(DATA_DIR, tp)
                return cand
            cov = ri.cover
            if cov and not _is_url_like(cov):
                cand = cov if os.path.isabs(cov) else os.path.join(DATA_DIR, cov)
                return cand
        except Exception as e:
            log.debug('ERROR', f'读取资源索引缩略图路径失败: {e}')

    # 默认文件夹回退（缩略图服务的默认命名）
    thumb_dir = os.path.join(DATA_DIR, 'thumbnails')
    for ext in ('jpg', 'png', 'gif'):
        path = os.path.join(thumb_dir, f'{video.hash}.{ext}')
        if os.path.exists(path):
            return path
    return None


def _record_thumbnail_path_in_index(video, force=False):
    """把缩略图「默认落点路径」写回资源索引，使索引成为缩略图位置的权威来源。

    默认仅在索引尚未记录时才写入，避免覆盖用户自定义（cover / meta.thumbnail 可能指向
    默认文件夹之外）。force=True 用于「正在（重新）生成」的场景：此时索引应改指向
    新生成到默认文件夹的缩略图，即便原先记录的是一条已失效的自定义路径。
    写的是相对 DATA_DIR 的路径（如 thumbnails/{hash}.jpg），
    resolve_thumbnail_path_for_video 会按 DATA_DIR 还原成绝对路径。
    """
    ri = getattr(video, 'resource_index', None)
    if ri is None or not getattr(video, 'hash', None):
        return
    try:
        m = ri.get_meta()
        if not force and m.get('thumbnail'):
            return
        m['thumbnail'] = f'thumbnails/{video.hash}.jpg'
        ri.meta = json.dumps(m, ensure_ascii=False)
        from core.models import db
        db.session.add(ri)
        db.session.commit()
    except Exception as e:
        log.debug('ERROR', f'记录缩略图路径到资源索引失败: {e}')


def _generate_missing_thumbnails(config=None):
    """扫描并生成缺失的缩略图，并实时更新 _thumb_progress 进度快照"""
    if config is None:
        config = _load_thumb_config()

    import time
    max_workers = config.get('max_workers', 2)
    task_interval = config.get('task_interval', 3)

    from core.models import Video
    visible_ids = _get_visible_library_ids()
    if visible_ids:
        db_videos = Video.query.filter(Video.library_id.in_(visible_ids)).all()
    else:
        db_videos = []

    missing_videos = []
    for v in db_videos:
        if not (v.hash and v.local_path and os.path.exists(v.local_path)):
            continue
        # 以资源索引规定的路径为准判断缺失（而非扫描默认文件夹按 hash 反推）；
        # 索引记录的路径若文件尚不存在，即视为缺失、需要生成。
        existing = resolve_thumbnail_path_for_video(v)
        if existing and os.path.exists(existing):
            continue
        # 把缩略图「默认落点路径」写回资源索引（force：即便是已失效的自定义路径也改指新生成文件），
        # 使索引成为缩略图位置的权威来源
        _record_thumbnail_path_in_index(v, force=True)
        missing_videos.append(v)

    # 初始化进度快照
    _thumb_progress.update({
        'running': True,
        'total': len(missing_videos),
        'processed': 0,
        'success': 0,
        'failed': 0,
        'current': '',
        'started_at': time.time(),
        'finished_at': None,
    })

    if not missing_videos:
        log.maintenance('INFO', '没有需要生成缩略图的视频')
        _thumb_progress['running'] = False
        _thumb_progress['finished_at'] = time.time()
        return

    log.maintenance('INFO', f'发现 {len(missing_videos)} 个视频缺少缩略图，开始批量生成（并发数: {max_workers}，间隔: {task_interval}秒）')

    if runtime.thumbnail_bus:
        import concurrent.futures

        def _submit_one(video):
            try:
                output_format = runtime.app_config.get('thumbnails', {}).get('output_format', 'sprite')
                r = runtime.thumbnail_bus.call_method(
                    service='com.dbox.thumbnaild',
                    interface='com.dbox.Thumbnaild',
                    method='Generate',
                    params={'video_path': video.local_path, 'video_hash': video.hash, 'output_format': output_format}
                )
                # 区分三类结果：
                # 1) 调用异常（微服务不可用/超时）→ 失败，记录错误
                # 2) 返回 success:False（队列已满/文件不存在等）→ 视为下发被拒，失败
                # 3) 返回 success:True → 已下发到 thumbnaild 队列
                if r is None:
                    return (video.hash, False, '微服务无响应（thumbnaild 未连接）')
                if isinstance(r, dict) and r.get('success') is False:
                    return (video.hash, False, r.get('error') or '任务被 thumbnaild 拒绝')
                return (video.hash, True, None)
            except Exception as e:
                return (video.hash, False, str(e))

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for i, video in enumerate(missing_videos):
                if _thumb_auto_stop_event.is_set():
                    log.maintenance('INFO', f'自动生成被停止，已提交 {i}/{len(missing_videos)} 个任务')
                    break

                _thumb_progress['current'] = f'{video.title or video.hash}'
                future = executor.submit(_submit_one, video)
                futures.append((future, video.hash))

                # 轮询式等待，兼顾停止信号，避免 task_interval 期间无法及时响应停止
                waited = 0
                while waited < task_interval and not _thumb_auto_stop_event.is_set():
                    _thumb_auto_stop_event.wait(0.5)
                    waited += 0.5

            # 逐任务回收结果并实时更新进度，避免提交阶段（可能数十分钟）内
            # 进度面板一直显示 0/0。注意：此处的 success 仅表示「已成功下发到
            # thumbnaild 队列」，并非「已生成出文件」，真实产出以后续对账为准。
            success = 0
            failed = 0
            for future, vhash in futures:
                try:
                    _, ok, err = future.result()
                except Exception as e:
                    ok, err = False, str(e)
                if ok:
                    success += 1
                else:
                    failed += 1
                    if err:
                        log.debug('WARNING', f'视频 {vhash} 缩略图生成失败: {err}')
                _thumb_progress['processed'] = _thumb_progress['processed'] + 1
                if ok:
                    _thumb_progress['success'] = _thumb_progress['success'] + 1
                else:
                    _thumb_progress['failed'] = _thumb_progress['failed'] + 1

        log.maintenance('INFO', f'批量生成缩略图完成: 已下发成功 {success}, 下发被拒/失败 {failed}')
    else:
        log.maintenance('WARN', '缩略图微服务不可用，无法批量生成')
        _thumb_progress['failed'] = _thumb_progress['total']

    _thumb_progress['running'] = False
    _thumb_progress['finished_at'] = time.time()
    return {'submitted': len(missing_videos)}
