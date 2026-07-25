"""入库：把脚本产出文件登记成 DPlayer 的 video / comic 资源。

优先复用现有入库逻辑：
- 视频：library_watcher.get_watcher().upsert_video(path, library_id)
- 漫画：backend.comic.scanner.scan_library_comics(library_id, app)
"""
import os


def _is_video_ext(path):
    ext = os.path.splitext(path)[1].lower()
    return ext in ('.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.ts',
                   '.m4v', '.mpg', '.mpeg', '.wmv', '.3gp')


def ingest_file(library_id, path, app, kind=None):
    """把一个文件/目录登记进指定资源库。

    kind: 'video' | 'comic' | None（自动推断）。
    返回 dict {success, message}。
    """
    if not path or not (os.path.isfile(path) or os.path.isdir(path)):
        return {'success': False, 'message': f'文件不存在: {path}'}

    if kind is None:
        if os.path.isfile(path) and _is_video_ext(path):
            kind = 'video'
        elif os.path.isdir(path):
            kind = 'comic'
        else:
            kind = 'video'

    try:
        if kind == 'video':
            from library_watcher import get_watcher
            w = get_watcher()
            if w:
                w.upsert_video(path, library_id)
            else:
                return {'success': False, 'message': 'library_watcher 未初始化，无法入库视频'}
            return {'success': True, 'message': f'已入库视频: {path}'}

        if kind == 'comic':
            from backend.comic.scanner import scan_library_comics
            scan_library_comics(library_id, app)
            return {'success': True, 'message': f'已扫描入库漫画库: {library_id}'}
    except Exception as e:
        return {'success': False, 'message': f'入库失败: {e}'}

    return {'success': False, 'message': f'未知资源类型: {kind}'}
