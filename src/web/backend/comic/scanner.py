# -*- coding: utf-8 -*-
"""
漫画扫描器

把视频库磁盘目录里的「扁平图片文件夹」识别为一本漫画：
  - 漫画 = 一个目录，其直接子文件里图片数 >= MIN_PAGES 且不含「带图片的子目录」
  - 支持递归（子目录若自身满足上述条件，也会被识别为独立的一本）
  - 每本漫画按 内容指纹(hash) 去重入库；重命名（改变 folder_path）会被识别为同一本并更新路径
  - 扫描完成后，磁盘上已不存在的漫画会被清理

图片格式：jpg/jpeg/png/webp/gif/bmp/avif
"""

import os
import re
from datetime import datetime

IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif')


def _natural_key(s: str):
    """自然排序键：让 1,2,10 而不是 1,10,2"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]


def _list_images(folder: str):
    try:
        entries = sorted(os.listdir(folder), key=_natural_key)
    except Exception:
        return []
    return [os.path.join(folder, f) for f in entries if f.lower().endswith(IMAGE_EXTS)]


def _dir_has_image_children(folder: str) -> bool:
    try:
        for name in os.listdir(folder):
            full = os.path.join(folder, name)
            if os.path.isfile(full) and name.lower().endswith(IMAGE_EXTS):
                return True
    except Exception:
        return False
    return False


def _sync_pages(comic, pages):
    """重建某漫画的页面记录（简单可靠；漫画页变动时数量不多，开销可接受）。"""
    from core.models import db, ComicPage
    ComicPage.query.filter_by(comic_id=comic.id).delete()
    for i, p in enumerate(pages):
        db.session.add(ComicPage(comic_id=comic.id, page_index=i, file_path=p))


def scan_library_comics(library_id, app, min_pages=2, max_depth=6, log=None):
    """扫描单个视频库，识别其中的漫画并写入 comics 表。

    Args:
        library_id: web 视频库 ID
        app: Flask app（用于 app_context）
        min_pages: 一个目录至少包含多少张图片才算漫画
        max_depth: 从库根目录向下的最大递归层数
        log: 可选日志对象（提供 .debug(level, msg)）
    Returns:
        dict: {success, added, updated, removed, total, message}
    """
    from core.models import db, Comic, VideoLibrary
    from library_watcher import get_watcher

    def debug(level, msg):
        if log:
            try:
                log.debug(level, msg)
            except Exception:
                print(msg)
        else:
            print(msg)

    with app.app_context():
        lib = VideoLibrary.query.get(library_id)
        if not lib:
            return {'success': False, 'message': '视频库不存在'}
        watcher = get_watcher()
        targets = watcher.library_disk_targets(library_id) if watcher else []
        if not targets:
            return {'success': False, 'message': '未找到该库的磁盘目录（resourced 不可用或路径缺失）'}

    added = updated = removed = 0
    seen_hashes = set()

    for root in targets:
        root = os.path.abspath(root)
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath[len(root):].count(os.sep)
            if depth > max_depth:
                dirnames[:] = []
                continue
            images = [f for f in filenames if f.lower().endswith(IMAGE_EXTS)]
            # 若某个子目录本身含图片，则该子目录很可能是另一本漫画，当前目录不算
            sub_has_images = any(
                os.path.isdir(os.path.join(dirpath, d)) and _dir_has_image_children(os.path.join(dirpath, d))
                for d in dirnames
            )
            if len(images) >= min_pages and not sub_has_images:
                pages = _list_images(dirpath)
                if not pages:
                    continue
                chash = Comic.generate_hash(dirpath, pages)
                seen_hashes.add(chash)
                with app.app_context():
                    existing = Comic.query.filter_by(hash=chash).first()
                    if existing:
                        changed = False
                        if existing.folder_path != dirpath:
                            existing.folder_path = dirpath
                            existing.cover_path = pages[0]
                            changed = True
                        # 图片集合变化则重建页面
                        if existing.page_count != len(pages):
                            changed = True
                        if changed:
                            existing.page_count = len(pages)
                            existing.cover_path = pages[0]
                            existing.updated_at = datetime.utcnow()
                            _sync_pages(existing, pages)
                            db.session.commit()
                            updated += 1
                    else:
                        c = Comic(
                            hash=chash,
                            title=os.path.basename(dirpath.rstrip(os.sep)),
                            folder_path=dirpath,
                            cover_path=pages[0],
                            page_count=len(pages),
                            library_id=library_id,
                        )
                        db.session.add(c)
                        db.session.flush()
                        _sync_pages(c, pages)
                        db.session.commit()
                        added += 1

    # 清理：库中已不存在（或磁盘目录已删除）的漫画
    with app.app_context():
        for c in Comic.query.filter_by(library_id=library_id).all():
            if c.hash not in seen_hashes or not (c.folder_path and os.path.isdir(c.folder_path)):
                db.session.delete(c)
                removed += 1
        db.session.commit()
        total = Comic.query.filter_by(library_id=library_id).count()

    debug('INFO', f'[ComicScan] 库 {library_id}: 新增 {added}, 更新 {updated}, 清理 {removed}, 现存 {total}')
    return {'success': True, 'added': added, 'updated': updated, 'removed': removed, 'total': total}


def scan_all_comics(app, log=None):
    """扫描所有视频库（供需要时一次性全量扫描）。"""
    from core.models import VideoLibrary
    results = []
    with app.app_context():
        libs = VideoLibrary.query.filter_by(is_active=True).all()
    for lib in libs:
        results.append(scan_library_comics(lib.id, app, log=log))
    return results
