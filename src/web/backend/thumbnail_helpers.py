# -*- coding: utf-8 -*-
"""缩略图管理辅助函数。

从 main.py 下沉而来，供 thumbnail_api 蓝图直接 import，消除
「蓝图函数体内 import main」的反模式。

需要运行时单例（thumbnail_bus / db / _DATA_DIR）的地方，统一从
backend.runtime 读取，而非延迟导入 main。
"""
import os
import json
import threading

from liblog import get_service_logger

log = get_service_logger('dplayer-web')
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


def _start_auto_generate(config=None):
    """启动自动生成缩略图后台线程"""
    global _thumb_auto_thread

    if config is None:
        config = _load_thumb_config()

    _thumb_auto_stop_event.clear()

    def _auto_generate_worker():
        log.maintenance('INFO', '缩略图自动生成线程已启动')

        while not _thumb_auto_stop_event.is_set():
            try:
                _generate_missing_thumbnails(config)
            except Exception as e:
                log.debug('ERROR', f'自动生成缩略图出错: {e}')

            _thumb_auto_stop_event.wait(config.get('auto_generate_interval', 3600))

        log.maintenance('INFO', '缩略图自动生成线程已停止')

    _thumb_auto_thread = threading.Thread(target=_auto_generate_worker, daemon=True)
    _thumb_auto_thread.start()


def _generate_missing_thumbnails(config=None):
    """扫描并生成缺失的缩略图"""
    if config is None:
        config = _load_thumb_config()

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

    if not missing_videos:
        log.maintenance('INFO', '没有需要生成缩略图的视频')
        return

    log.maintenance('INFO', f'发现 {len(missing_videos)} 个视频缺少缩略图，开始批量生成（并发数: {max_workers}，间隔: {task_interval}秒）')

    if runtime.thumbnail_bus:
        import concurrent.futures

        def _submit_one(video):
            try:
                runtime.thumbnail_bus.call_method(
                    service='com.dplayer.thumbnaild',
                    interface='com.dplayer.Thumbnaild',
                    method='Generate',
                    params={'video_path': video.local_path, 'video_hash': video.hash, 'output_format': 'gif'}
                )
                return (video.hash, True, None)
            except Exception as e:
                return (video.hash, False, str(e))

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for i, video in enumerate(missing_videos):
                if _thumb_auto_stop_event.is_set():
                    log.maintenance('INFO', f'自动生成被停止，已提交 {i}/{len(missing_videos)} 个任务')
                    break

                future = executor.submit(_submit_one, video)
                futures.append(future)

                if i < len(missing_videos) - 1 and task_interval > 0:
                    _thumb_auto_stop_event.wait(task_interval)

            success = 0
            failed = 0
            for future in concurrent.futures.as_completed(futures):
                try:
                    _, ok, err = future.result()
                    if ok:
                        success += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1

        log.maintenance('INFO', f'批量生成缩略图完成: 成功 {success}, 失败 {failed}')
    else:
        log.maintenance('WARN', '缩略图微服务不可用，无法批量生成')

    return {'submitted': len(missing_videos)}
