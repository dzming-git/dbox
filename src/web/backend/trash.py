"""资源回收站（软删除）逻辑。

删除资源（视频 / 图集）时，文件 / 文件夹不会立即消失，而是移动到
``data/trash`` 目录下，并在数据库记录上标记 ``in_trash=True``。
管理员可在回收站中将其「恢复」（移回原路径）或「永久删除」（清除文件与记录）。
"""
import os
import shutil
from datetime import datetime

from core.models import (
    db, User, Video, Gallery, ResourceLibrary,
    UserInteraction, VideoTag,
    VideoMarker, CollectionVideo, PlaylistItem,
    GalleryPage, GalleryInteraction, GalleryProgress, GalleryTag,
    GalleryPlaylistItem, WatchLater,
)

_THIS = os.path.dirname(os.path.abspath(__file__))
# src/web/backend/trash.py -> 上三级即项目根
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, '..', '..', '..'))
TRASH_ROOT = os.path.join(PROJECT_ROOT, 'data', 'trash')


# ---------------------------------------------------------------------------
# 路径工具
# ---------------------------------------------------------------------------
def _trash_dir(kind: str) -> str:
    """kind: 'video' -> data/trash/videos；'gallery' -> data/trash/galleries"""
    d = os.path.join(TRASH_ROOT, kind + 's')
    os.makedirs(d, exist_ok=True)
    return d


def _trash_path(obj, kind: str) -> str:
    return os.path.join(_trash_dir(kind), obj.hash)


def _source_path(obj, kind: str) -> str:
    return obj.local_path if kind == 'video' else obj.folder_path


def _trash_size(obj, kind: str) -> int:
    p = _trash_path(obj, kind)
    if not os.path.exists(p):
        return 0
    if os.path.isdir(p):
        total = 0
        for root, _dirs, files in os.walk(p):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        return total
    try:
        return os.path.getsize(p)
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# 核心操作
# ---------------------------------------------------------------------------
def _tombstone_watch_later(obj, kind: str):
    """资源移入回收站时，将其在「稍后再看」中的条目一并打墓碑。

    否则条目仅被可见性过滤隐藏，待视频恢复 / 重新入库后会「复活」重新出现，
    这正是「删了又回来」的根因之一。墓碑态下即使资源恢复也不会复活。
    """
    item_type = 'video' if kind == 'video' else 'gallery'
    (WatchLater.query
     .filter_by(item_type=item_type, item_id=obj.hash)
     .update({'deleted_at': datetime.utcnow()}, synchronize_session=False))


def _purge_watch_later(obj, kind: str):
    """资源永久删除时，物理清除其「稍后再看」条目（资源已不存在，无需保留墓碑）。"""
    item_type = 'video' if kind == 'video' else 'gallery'
    WatchLater.query.filter_by(item_type=item_type, item_id=obj.hash).delete()


def move_to_trash(obj, kind: str):
    """软删除：将文件 / 文件夹移入回收站，并标记 in_trash。"""
    src = _source_path(obj, kind)
    if src and os.path.exists(src):
        dst = _trash_path(obj, kind)
        if os.path.exists(dst):
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            else:
                os.remove(dst)
        try:
            shutil.move(src, dst)
        except Exception as e:  # 移动失败不应阻断删除流程
            print(f'[TRASH] move failed {src}: {e}')
    obj.in_trash = True
    obj.trashed_at = datetime.utcnow()
    _tombstone_watch_later(obj, kind)
    db.session.commit()
    return obj


def restore_from_trash(obj, kind: str):
    """恢复：从回收站移回原路径，并取消标记。

    注意：不在此处复活「稍后再看」条目——其墓碑保持有效，否则会重新引入
    「删了又回来」。用户若仍需稍后再看，可主动重新加入。
    """
    dst = _source_path(obj, kind)
    src = _trash_path(obj, kind)
    if os.path.exists(src):
        parent = os.path.dirname(dst)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if os.path.exists(dst):
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            else:
                os.remove(dst)
        shutil.move(src, dst)
    obj.in_trash = False
    obj.trashed_at = None
    db.session.commit()
    return obj


def _delete_video_dependents(video):
    """删除视频前先清理其全部子表记录，避免外键约束导致删除失败。

    这些子表通过 ``videos.id`` 外键关联但未配置 ORM 级联删除，
    直接 ``db.session.delete(video)`` 会触发 ``FOREIGN KEY constraint failed``。
    """
    VideoMarker.query.filter_by(video_id=video.id).delete()
    CollectionVideo.query.filter_by(video_id=video.id).delete()
    PlaylistItem.query.filter_by(video_id=video.id).delete()
    VideoTag.query.filter_by(video_id=video.id).delete()
    UserInteraction.query.filter_by(video_id=video.id).delete()


def _delete_gallery_dependents(gallery):
    """删除图集前先清理其全部子表记录（同 ``_delete_video_dependents`` 的原因）。"""
    GalleryPage.query.filter_by(gallery_id=gallery.id).delete()
    GalleryInteraction.query.filter_by(gallery_id=gallery.id).delete()
    GalleryProgress.query.filter_by(gallery_id=gallery.id).delete()
    GalleryTag.query.filter_by(gallery_id=gallery.id).delete()
    GalleryPlaylistItem.query.filter_by(gallery_id=gallery.id).delete()
    CollectionVideo.query.filter_by(gallery_id=gallery.id).delete()


def purge_trash(obj, kind: str):
    """永久删除：清除回收站（或原位置残留）的物理文件及数据库记录。"""
    # 物理文件可能仍在原位置（管理员直接永久删除，未经过回收站）
    # 也可能已在回收站中，两种情况都尝试清理
    for p in (_source_path(obj, kind), _trash_path(obj, kind)):
        if p and os.path.exists(p):
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)

    # 先清理所有外键子表，再删除主体，避免 FOREIGN KEY 约束失败
    if kind == 'video':
        _delete_video_dependents(obj)
        _delete_thumbnails(obj.hash)
    elif kind == 'gallery':
        _delete_gallery_dependents(obj)
    _purge_watch_later(obj, kind)

    db.session.delete(obj)
    db.session.commit()


def _delete_thumbnails(video_hash: str):
    thumb_dir = os.path.join(PROJECT_ROOT, 'data', 'thumbnails')
    if not os.path.isdir(thumb_dir):
        return
    # 删除该 hash 的完整缩略图文件集（poster / 旧 gif / png / sprite 雪碧图 / vtt 索引）
    for fname in (f'{video_hash}.gif', f'{video_hash}.jpg', f'{video_hash}.png',
                  f'{video_hash}.sprite.jpg', f'{video_hash}.vtt'):
        tp = os.path.join(thumb_dir, fname)
        if os.path.exists(tp):
            try:
                os.remove(tp)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# 列表 / 查询
# ---------------------------------------------------------------------------
def get_trash_obj(kind: str, hash_value: str):
    if kind == 'video':
        return Video.query.filter_by(hash=hash_value, in_trash=True).first()
    if kind == 'gallery':
        return Gallery.query.filter_by(hash=hash_value, in_trash=True).first()
    return None


def _library_is_active(library_id):
    """资源所属库是否处于激活状态（已停用的库其资源对外不可见）。"""
    if library_id is None:
        return False
    lib = ResourceLibrary.query.get(library_id)
    return bool(lib and lib.is_active)


def get_trash_list(only_active_library=True):
    """返回回收站中所有资源（视频 + 图集），按删除时间倒序。

    only_active_library=True（默认）：仅返回归属「已激活资源库」的已删资源，
    未激活库的资源连同其回收站条目一并对外不可见（资源库管理模块完整收敛）。
    管理员如需查看全部（含已停用库的资源），传 only_active_library=False。
    """
    items = []

    for v in Video.query.filter_by(in_trash=True).all():
        if only_active_library and not _library_is_active(v.library_id):
            continue
        owner = None
        if v.owner_id:
            u = db.session.get(User, v.owner_id)
            owner = u.username if u else None
        items.append({
            'type': 'video',
            'hash': v.hash,
            'title': v.title,
            'owner_id': v.owner_id,
            'owner': owner,
            'trashed_at': v.trashed_at.isoformat() if v.trashed_at else None,
            'size': _trash_size(v, 'video'),
        })

    for c in Gallery.query.filter_by(in_trash=True).all():
        if only_active_library and not _library_is_active(c.library_id):
            continue
        owner = None
        if c.owner_id:
            u = db.session.get(User, c.owner_id)
            owner = u.username if u else None
        items.append({
            'type': 'gallery',
            'hash': c.hash,
            'title': c.title,
            'owner_id': c.owner_id,
            'owner': owner,
            'trashed_at': c.trashed_at.isoformat() if c.trashed_at else None,
            'size': _trash_size(c, 'gallery'),
        })

    items.sort(key=lambda x: x['trashed_at'] or '', reverse=True)
    return items
