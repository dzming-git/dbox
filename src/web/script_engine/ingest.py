"""入库：把脚本产出文件登记成 DPlayer 资源，并按指定「模式（modes）」归属。

设计（见 docs/multi_mode_resource_management.md）：
- ResourceIndex 是通用资产；kind: video_file / gallery_folder / text。
- modes 决定资源归属哪些单资源模式（video/gallery/text）；组合模式 post 由 Post 引用表达。
- 例：modes=['video'] -> 建 Video，视频列表可见；
     modes=['post'] -> 只建 ResourceIndex（不建 Video），由后续 Post 引用，视频列表不可见；
     modes=['video','post'] -> 视频列表与帖子均可见。
"""
import os

from core.models import ResourceIndex, ResourceMode, set_resource_modes


def _is_video_ext(path):
    ext = os.path.splitext(path)[1].lower()
    return ext in ('.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.ts',
                   '.m4v', '.mpg', '.mpeg', '.wmv', '.3gp')


_KIND_TO_RI = {'video': 'video_file', 'gallery': 'gallery_folder', 'image': 'gallery_folder', 'text': 'text'}


def _get_or_create_resource_index(library_id, path, ri_kind, meta):
    """在调用方已有的 app_context 内获取/创建 ResourceIndex（不打开新 context）。"""
    ri = ResourceIndex.query.filter_by(location=path, kind=ri_kind).first()
    if not ri:
        ri = ResourceIndex(kind=ri_kind, location=path, library_id=library_id)
        if meta:
            ri.set_meta(meta)
        db.session.add(ri)
        db.session.flush()
    elif meta:
        ri.set_meta(meta)
        db.session.flush()
    return ri


def ingest_file(library_id, path, app, kind=None, modes=('video',), collection_id=None,
                meta=None, user_id=None):
    """把一个文件/目录登记进指定资源库，并按 modes 归属模式。

    返回 dict：{success, resource_index_id?, kind?, modes?, message}
    """
    if not path or not (os.path.isfile(path) or os.path.isdir(path)):
        return {'success': False, 'message': f'文件不存在: {path}'}

    if kind is None:
        if os.path.isfile(path) and _is_video_ext(path):
            kind = 'video'
        elif os.path.isdir(path):
            kind = 'gallery'
        else:
            kind = 'video'

    ri_kind = _KIND_TO_RI.get(kind, kind)
    modes = [m for m in (modes or ('video',)) if ResourceMode.is_valid(m)]

    try:
        with app.app_context():
            # 1) 获取/创建 ResourceIndex（按 location + kind 去重）
            if kind == 'video' and ResourceMode.VIDEO in modes:
                # 复用既有扫描/去重/缩略图逻辑（会建 Video + ResourceIndex）
                from library_watcher import get_watcher
                w = get_watcher()
                if not w:
                    return {'success': False, 'message': 'library_watcher 未初始化，无法入库视频'}
                entry = w.upsert_video(path, library_id)
                ri = entry.resource_index if entry else None
                if not ri:
                    return {'success': False, 'message': f'视频入库失败: {path}'}
                if meta:
                    ri.set_meta(meta)
            elif kind == 'gallery' and ResourceMode.GALLERY in modes:
                from backend.gallery.scanner import scan_library_galleries
                galleries = scan_library_galleries(library_id, app=app, specific_paths=[path])
                ri = None
                for c in galleries:
                    if c.resource_index and c.resource_index.location == path:
                        ri = c.resource_index
                        break
                if not ri:
                    ri = _get_or_create_resource_index(library_id, path, ri_kind, meta)
            else:
                # 非主模式（如只进帖子的 video、或 text）：直接建索引，不建富化实体
                ri = _get_or_create_resource_index(library_id, path, ri_kind, meta)

            # 2) 应用模式归属（membership 行 + 富化实体同步增删）
            set_resource_modes(ri, modes, collection_id=collection_id, user_id=user_id)
            db.session.commit()
            return {
                'success': True,
                'resource_index_id': ri.id,
                'kind': ri.kind,
                'modes': modes,
                'message': f'已入库({",".join(modes)}): {path}',
            }
    except Exception as e:
        return {'success': False, 'message': f'入库失败: {e}'}
