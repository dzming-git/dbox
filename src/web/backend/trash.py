"""资源回收站（软删除）逻辑。

删除资源（视频 / 漫画）时，文件 / 文件夹不会立即消失，而是移动到
``data/trash`` 目录下，并在数据库记录上标记 ``in_trash=True``。
管理员可在回收站中将其「恢复」（移回原路径）或「永久删除」（清除文件与记录）。
"""
import os
import shutil
from datetime import datetime

from core.models import (
    db, User, Video, Comic,
    UserInteraction, VideoTag,
    ComicPage, ComicInteraction, ComicProgress, ComicTag,
)

_THIS = os.path.dirname(os.path.abspath(__file__))
# src/web/backend/trash.py -> 上三级即项目根
PROJECT_ROOT = os.path.abspath(os.path.join(_THIS, '..', '..', '..'))
TRASH_ROOT = os.path.join(PROJECT_ROOT, 'data', 'trash')


# ---------------------------------------------------------------------------
# 路径工具
# ---------------------------------------------------------------------------
def _trash_dir(kind: str) -> str:
    """kind: 'video' -> data/trash/videos；'comic' -> data/trash/comics"""
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
    db.session.commit()
    return obj


def restore_from_trash(obj, kind: str):
    """恢复：从回收站移回原路径，并取消标记。"""
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

    if kind == 'video':
        _delete_thumbnails(obj.hash)
    elif kind == 'comic':
        ComicTag.query.filter_by(comic_id=obj.id).delete()

    db.session.delete(obj)
    db.session.commit()


def _delete_thumbnails(video_hash: str):
    thumb_dir = os.path.join(PROJECT_ROOT, 'data', 'thumbnails')
    if not os.path.isdir(thumb_dir):
        return
    for ext in ('gif', 'jpg', 'png'):
        tp = os.path.join(thumb_dir, f'{video_hash}.{ext}')
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
    if kind == 'comic':
        return Comic.query.filter_by(hash=hash_value, in_trash=True).first()
    return None


def get_trash_list():
    """返回回收站中所有资源（视频 + 漫画），按删除时间倒序。"""
    items = []

    for v in Video.query.filter_by(in_trash=True).all():
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

    for c in Comic.query.filter_by(in_trash=True).all():
        owner = None
        if c.owner_id:
            u = db.session.get(User, c.owner_id)
            owner = u.username if u else None
        items.append({
            'type': 'comic',
            'hash': c.hash,
            'title': c.title,
            'owner_id': c.owner_id,
            'owner': owner,
            'trashed_at': c.trashed_at.isoformat() if c.trashed_at else None,
            'size': _trash_size(c, 'comic'),
        })

    items.sort(key=lambda x: x['trashed_at'] or '', reverse=True)
    return items
