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

# 默认缩略图配置
_DEFAULT_THUMB_CONFIG = {
    'auto_generate': False,
    'max_workers': 2,
    'task_interval': 3,
    'auto_generate_interval': 3600,
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


def _generate_missing_thumbnails(config=None):
    """扫描并生成缺失的缩略图，并实时更新 _thumb_progress 进度快照"""
    if config is None:
        config = _load_thumb_config()

    import time
    thumb_dir = os.path.join(DATA_DIR, 'thumbnails')
    max_workers = config.get('max_workers', 2)
    task_interval = config.get('task_interval', 3)

    from core.models import Video
    db_videos = Video.query.all()

    missing_videos = []
    for v in db_videos:
        if v.hash and v.local_path and os.path.exists(v.local_path):
            has_thumb = any(
                os.path.exists(os.path.join(thumb_dir, f'{v.hash}.{ext}'))
                for ext in ['gif', 'jpg', 'png']
            )
            if not has_thumb:
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
                r = runtime.thumbnail_bus.call_method(
                    service='com.dbox.thumbnaild',
                    interface='com.dbox.Thumbnaild',
                    method='Generate',
                    params={'video_path': video.local_path, 'video_hash': video.hash, 'output_format': 'gif'}
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
