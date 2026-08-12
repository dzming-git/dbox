"""入库：把脚本产出文件登记成 Dbox 资源，并按指定「模式（modes）」归属。

设计（见 docs/multi_mode_resource_management.md）：
- ResourceIndex 是通用资产；kind: video_file / gallery_folder / text。
- modes 决定资源归属哪些单资源模式（video/gallery/text）；组合模式 post 由 Post 引用表达。
- 例：modes=['video'] -> 建 Video，视频列表可见；
     modes=['post'] -> 只建 ResourceIndex（不建 Video），由后续 Post 引用，视频列表不可见；
     modes=['video','post'] -> 视频列表与帖子均可见。

本模块驻留在主 Web 服务进程内（backend/internal_ingest），可直接使用 core.models /
library_watcher / backend.gallery.scanner 等业务模块。独立运行的拓展宿主
（extensions_host）不直接 import 本模块，而是通过平台内部接口 /internal/ingest
以 HTTP 调用本能力，从而实现拓展管理与主模块的彻底解耦。
"""
import os
from urllib.parse import quote

from core.models import ResourceIndex, ResourceMode, set_resource_modes, db, Video


def _is_video_ext(path):
    ext = os.path.splitext(path)[1].lower()
    return ext in ('.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.ts',
                   '.m4v', '.mpg', '.mpeg', '.wmv', '.3gp')


_KIND_TO_RI = {'video': 'video_file', 'gallery': 'gallery_folder', 'image': 'gallery_folder', 'text': 'text', 'document': 'document_file'}


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
                meta=None, user_id=None, hidden=False):
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
    # 是否隐藏：隐藏的资源不进视频/图集库列表，仅在帖子流可见（X 下载默认隐藏）
    _hidden = bool(hidden)

    try:
        with app.app_context():
            # 1) 获取/创建 ResourceIndex（按 location + kind 去重）
            if kind == 'video' and ResourceMode.VIDEO in modes:
                # 确保视频资源索引存在（按 location + kind 去重）
                ri = ResourceIndex.query.filter_by(location=path, kind='video_file').first()
                if not ri:
                    ri = _get_or_create_resource_index(library_id, path, 'video_file', meta)
                # 优先复用既有 watcher 的扫描/去重/缩略图逻辑建 Video
                v = None
                from library_watcher import get_watcher
                w = get_watcher()
                if w:
                    try:
                        v = w.upsert_video(path, library_id)
                    except Exception:
                        v = None
                # watcher 不可用（如脚本独立进程）时，直接构建 Video 实体并关联本资源索引
                if not v:
                    v = Video.query.filter_by(local_path=path).first()
                    if not v:
                        v = Video.query.join(ResourceIndex).filter(ResourceIndex.location == path).first()
                if not v:
                    vhash = Video.generate_hash(path)
                    v = Video(
                        title=os.path.basename(path),
                        url=f'/local_video/{quote(os.path.abspath(path))}',
                        hash=vhash,
                        local_path=path,
                        library_id=library_id,
                        resource_index_id=ri.id,
                    )
                    db.session.add(v)
                db.session.flush()
                if v.resource_index_id != ri.id:
                    v.resource_index_id = ri.id
                    db.session.flush()
                if meta:
                    ri.set_meta(meta)
            elif kind == 'gallery' and ResourceMode.GALLERY in modes:
                from backend.gallery.scanner import scan_library_galleries
                # scan_library_galleries 返回 dict（含 added/updated），不返回 Gallery 列表；
                # 它内部已按 location 复用/新建 ResourceIndex，这里直接按 location 取回即可。
                scan_library_galleries(library_id, app=app, specific_paths=[path])
                ri = ResourceIndex.query.filter(
                    ResourceIndex.kind == ri_kind,
                    db.func.lower(ResourceIndex.location) == os.path.abspath(path).lower(),
                ).first()
                if not ri:
                    ri = _get_or_create_resource_index(library_id, path, ri_kind, meta)
            else:
                # 非主模式（如只进帖子的 video、或 text）：直接建索引，不建富化实体
                ri = _get_or_create_resource_index(library_id, path, ri_kind, meta)

            # 2) 应用模式归属（membership 行 + 富化实体同步增删）
            ri.hidden = _hidden
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
