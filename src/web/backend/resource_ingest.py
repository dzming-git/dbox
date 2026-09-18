# -*- coding: utf-8 -*-
"""资源入库的**唯一入口**：索引 + 实体 + 归属行在同一事务内写就。

为什么要收敛（事故复盘）：
    视频入库此前散在 4 处，各自直接 `Video(...)` 建实体：
      · ResourceIndex 其实是 `Video.local_path` 的 setter **顺带**创建的 ——
        它只在 `self.library_id` 已赋值时才带 library_id，而 SQLAlchemy 对构造
        参数的赋值顺序不确定，于是索引可能缺 library_id（漂移）；
      · **归属行（resource_memberships）根本没人写**。而归属行才是可见性的
        唯一真相源，于是出现「有实体无归属」（历史上 1097 条视频）。

这里把入库收敛成一个函数：先按 location 取/建 ResourceIndex（显式带
library_id），再取/建 Video 并**显式关联**该索引，最后由 set_resource_modes()
幂等同步归属行与富化实体 —— 三步一个事务，不再有漂移窗口。

约定：调用方必须已在 app_context 内（与 _get_or_create_resource_index 同款约定）。
"""
import os
from urllib.parse import quote

from core.models import (
    db, Video, ResourceIndex, Tag, VideoTag, set_resource_modes,
)

VIDEO_RI_KIND = 'video_file'


def get_or_create_resource_index(library_id, path, kind=VIDEO_RI_KIND, meta=None):
    """按 (location, kind) 取/建 ResourceIndex；索引缺 library_id 时补齐。"""
    ri = ResourceIndex.query.filter_by(location=path, kind=kind).first()
    if not ri:
        ri = ResourceIndex(kind=kind, location=path, library_id=library_id)
        if meta:
            ri.set_meta(meta)
        db.session.add(ri)
        db.session.flush()
        return ri
    if ri.library_id is None and library_id is not None:
        ri.library_id = library_id
    if meta:
        ri.set_meta(meta)
        db.session.flush()
    return ri


def _apply_tags(video, tags):
    """默认标签：标签不存在则创建，已存在则不重复关联。"""
    for tag_name in (tags or []):
        if not tag_name:
            continue
        tag = Tag.query.filter_by(name=tag_name).first()
        if not tag:
            tag = Tag(name=tag_name, category='类型')
            tag.path = f'/{tag_name}'
            db.session.add(tag)
            db.session.flush()
        exists = VideoTag.query.filter_by(video_id=video.id, tag_id=tag.id).first()
        if not exists:
            db.session.add(VideoTag(video_id=video.id, tag_id=tag.id))


def ingest_video_file(path, library_id, *, modes=('video',), meta=None,
                      title=None, description=None, owner_id=None, user_id=None,
                      tags=None, priority=None, duration=None, file_size=None,
                      is_downloaded=True, hidden=False, collection_id=None):
    """把一个本地视频文件登记进资源库（索引 + 实体 + 归属，同一事务）。

    返回 dict：{ video, resource_index, hash, is_new }
    """
    path = os.path.abspath(path)
    base = os.path.basename(path)
    vhash = Video.generate_hash(path)

    # 1) 索引：显式建，保证带 library_id（不走 local_path setter，避免顺序漂移）
    ri = get_or_create_resource_index(library_id, path, VIDEO_RI_KIND, meta)

    # 2) 实体：按 索引 → 内容指纹 → 路径 依次复用，避免同一文件重复入库
    video = Video.query.filter_by(resource_index_id=ri.id).first()
    if video is None:
        video = Video.query.filter_by(hash=vhash).first()
    if video is None:
        video = (Video.query.join(ResourceIndex)
                 .filter(ResourceIndex.location == path).first())
    is_new = video is None

    if is_new:
        video = Video(
            hash=vhash,
            title=title or os.path.splitext(base)[0],
            description=description or f'本地视频: {base}',
            url=f'/local_video/{quote(path.replace(chr(92), "/"), safe=":/")}',
            thumbnail=f'/thumbnail/{vhash}',
        )
        db.session.add(video)
        db.session.flush()

    # 3) 显式关联索引（这是消除「有实体无索引」的关键一步）
    if video.resource_index_id != ri.id:
        video.resource_index_id = ri.id
    video.resource_index = ri

    # 4) 物理与展示信息
    video.hash = vhash
    video.library_id = library_id
    video.file_name = base
    video.is_downloaded = is_downloaded
    if priority is not None:
        video.priority = priority
    if owner_id is not None:
        video.owner_id = owner_id
    # 标题与文件名解耦：已有条目不因文件名变化而改标题，除非调用方显式给了标题
    if title:
        video.title = title
    if description and is_new:
        video.description = description
    video.url = f'/local_video/{quote(path.replace(chr(92), "/"), safe=":/")}'
    if not video.thumbnail:
        video.thumbnail = f'/thumbnail/{vhash}'

    # 文件重新出现：此前若因「文件缺失」进了回收站，这里自动恢复（只清标记，不搬文件）
    if getattr(video, 'in_trash', False):
        video.in_trash = False
        video.trashed_at = None

    if file_size is None:
        try:
            file_size = os.path.getsize(path)
        except OSError:
            file_size = None
    if file_size is not None:
        video.file_size = file_size
    if duration is None and not video.duration:
        try:
            from backend.utils.media import extract_duration
            duration = extract_duration(path)
        except Exception:
            duration = None
    if duration is not None:
        video.duration = duration

    db.session.flush()

    # 5) 标签
    _apply_tags(video, tags)

    # 6) 归属行 + 富化实体同步（唯一真相源；post 模式由 Post/PostRef 表达，此处跳过）
    ri.hidden = bool(hidden)
    set_resource_modes(ri, list(modes or ('video',)),
                       collection_id=collection_id,
                       user_id=user_id or owner_id)

    # 7) 封面统一入口：索引封面缺失时用视频缩略图兜底
    if not ri.cover:
        ri.cover = video.thumbnail or f'/thumbnail/{vhash}'

    db.session.commit()
    return {'video': video, 'resource_index': ri, 'hash': vhash, 'is_new': is_new}
