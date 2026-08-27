# -*- coding: utf-8 -*-
"""
图集扫描器

把资源库磁盘目录里的「扁平图片文件夹」识别为一本图集：
  - 图集 = 一个目录，其直接子文件里图片数 >= MIN_PAGES 且不含「带图片的子目录」
  - 支持递归（子目录若自身满足上述条件，也会被识别为独立的一本）
  - 每本图集按 内容指纹(hash) 去重入库；重命名（改变 folder_path）会被识别为同一本并更新路径
  - 扫描完成后，磁盘上已不存在的图集会被清理

图片格式：jpg/jpeg/png/webp/gif/bmp/avif
"""

import os
import re
import json
from datetime import datetime, timezone

IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.avif')


def _load_app_config():
    """读取用户运行时配置（兜底目标来源）。

    配置已迁移到系统数据区的用户配置文件，由 backend.system_helpers.load_config 统一加载，
    不再从项目目录读取（避免个人路径污染仓库）。
    """
    try:
        from backend.system_helpers import load_config
        return load_config()
    except Exception:
        return {}


def _gallery_targets_from_scan_directories():
    """兜底：使用 config.json 中的 scan_directories（已配置的扫描根目录）。"""
    cfg = _load_app_config()
    out = []
    for d in cfg.get('scan_directories', []) or []:
        path = d.get('path') if isinstance(d, dict) else None
        if path and os.path.isdir(path):
            out.append(path)
    return out


def _resolve_gallery_targets(library_id, app=None):
    """图集扫描的磁盘目标解析，按优先级回退，保证即使 resourced/watcher 不可用也能扫描已配置目录：
    1) 通过 library_watcher 单例（来自 resourced 的库路径 + 子文件夹）；
    2) 直接调用 resourced 服务获取库路径与其文件夹；
    3) config.json 的 scan_directories（兜底，已配置的扫描根目录）。
    """
    # 1) watcher 单例
    try:
        from library_watcher import get_watcher
        w = get_watcher()
        if w:
            t = w.library_disk_targets(library_id)
            if t:
                return t
    except Exception:
        pass

    # 2) 直接调用 resourced
    try:
        from servicebus import BusClient
        bus = BusClient(f'gallery-scan-{os.getpid()}', host='127.0.0.1', rpc_port=15555, pub_port=15556)
        res = bus.call_method('com.dbox.resourced', 'com.dbox.Resourced', 'ListLibraries', {}, timeout=5000)
        if res and res.get('success'):
            name = None
            if app:
                with app.app_context():
                    from core.models import ResourceLibrary
                    lib = ResourceLibrary.query.get(library_id)
                    name = lib.name if lib else None
            rl = {x['name']: x for x in res.get('libraries', [])}.get(name) if name else None
            paths = []
            if rl:
                if rl.get('path') and os.path.isdir(rl['path']):
                    paths.append(rl['path'])
                try:
                    fr = bus.call_method('com.dbox.resourced', 'com.dbox.Resourced', 'ListFolders',
                                         {'library_id': rl['id']}, timeout=5000)
                    if fr and fr.get('success'):
                        for f in fr.get('folders', []) or []:
                            fp = f.get('path')
                            if fp and os.path.isdir(fp):
                                paths.append(fp)
                except Exception:
                    pass
            if paths:
                return paths
    except Exception:
        pass

    # 3) 兜底：scan_directories
    return _gallery_targets_from_scan_directories()


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


def _sync_pages(gallery, pages):
    """重建某图集的页面记录（简单可靠；图集页变动时数量不多，开销可接受）。"""
    from core.models import db, GalleryPage
    GalleryPage.query.filter_by(gallery_id=gallery.id).delete()
    for i, p in enumerate(pages):
        db.session.add(GalleryPage(gallery_id=gallery.id, comic_id=gallery.id,
                                   page_index=i, file_path=p))


def scan_library_galleries(library_id, app, min_pages=2, max_depth=6, log=None, specific_paths=None):
    """扫描单个资源库，识别其中的图集并写入 galleries 表。

    Args:
        library_id: web 资源库 ID
        app: Flask app（用于 app_context）
        min_pages: 一个目录至少包含多少张图片才算图集
        max_depth: 从库根目录向下的最大递归层数
        log: 可选日志对象（提供 .debug(level, msg)）
        specific_paths: 若提供，则直接把给定目录当作图集登记（脚本产出常用），
            不再依赖资源库磁盘监控根目录，且单图目录也会登记为图集。
    Returns:
        dict: {success, added, updated, removed, total, message}
    """
    # 指定目录模式（脚本产出）：直接把给定目录作为图集登记。
    # 用于 X 等脚本把「一个 URL 的图片」放进同一目录、需聚合成一本图集的场景；
    # 此时资源库未必配置了磁盘监控根，且单图目录也应能成集。
    if specific_paths:
        # 允许传入「单文件」：取其所在目录作为图集目录（如 pixiv 把多张图下载到同一目录，
        # 但逐张以单文件路径调用 ingest/scan 的场景）。这样仍能聚合成一本图集。
        targets = []
        for sp in specific_paths:
            ap = os.path.abspath(sp)
            if os.path.isdir(ap):
                targets.append(ap)
            elif os.path.isfile(ap):
                d = os.path.dirname(ap)
                if d and d not in targets:
                    targets.append(d)
        if not targets:
            return {'success': False, 'message': '指定的图集目录不存在或不是文件夹'}
        added = updated = 0
        seen_hashes = set()
        with app.app_context():
            from core.models import db, Gallery, User, UserRole, ResourceIndex
            root_user = User.query.filter_by(role=UserRole.ROOT).order_by(User.id).first()
            root_id = root_user.id if root_user else 1
            for dirpath in targets:
                images = _list_images(dirpath)
                if not images:
                    continue
                chash = Gallery.generate_hash(dirpath, images)
                seen_hashes.add(chash)
                # 复用 ingest_file 已创建的、与该目录同 location 的资源索引，
                # 避免产生「孤儿」资源索引导致帖子引用找不到图集。
                ri = ResourceIndex.query.filter(
                    ResourceIndex.kind == 'gallery_folder',
                    db.func.lower(ResourceIndex.location) == dirpath.lower()
                ).first()
                existing = Gallery.query.filter_by(hash=chash).first()
                if existing:
                    if ri and existing.resource_index_id != ri.id:
                        existing.resource_index = ri
                    elif existing.resource_index is None:
                        existing.resource_index = ResourceIndex(
                            kind='gallery_folder', location=dirpath, library_id=library_id)
                    existing.folder_path = dirpath
                    existing.page_count = len(images)
                    existing.updated_at = datetime.utcnow()
                    _sync_pages(existing, images)
                    if existing.resource_index and not existing.resource_index.cover:
                        existing.resource_index.cover = f'/gallery-cover/{existing.hash}'
                    db.session.commit()
                    updated += 1
                else:
                    c = Gallery(hash=chash, title=os.path.basename(dirpath.rstrip(os.sep)),
                                page_count=len(images), library_id=library_id, owner_id=root_id)
                    if ri:
                        c.resource_index = ri
                    else:
                        c.folder_path = dirpath
                    db.session.add(c)
                    db.session.flush()
                    if c.resource_index and not c.resource_index.cover:
                        c.resource_index.cover = f'/gallery-cover/{c.hash}'
                    _sync_pages(c, images)
                    db.session.commit()
                    added += 1
        return {'success': True, 'added': added, 'updated': updated, 'removed': 0,
                'total': len(seen_hashes),
                'message': f'指定目录图集：新增 {added}，更新 {updated}'}

    from core.models import db, Gallery, ResourceLibrary

    def debug(level, msg):
        if log:
            try:
                log.debug(level, msg)
            except Exception:
                print(msg)
        else:
            print(msg)

    with app.app_context():
        from core.models import User, UserRole
        lib = ResourceLibrary.query.get(library_id)
        if not lib:
            return {'success': False, 'message': '资源库不存在'}
        # 扫描发现的资源归属 root 用户（管理员对所有资源有权限）
        root_user = User.query.filter_by(role=UserRole.ROOT).order_by(User.id).first()
        root_id = root_user.id if root_user else 1
        targets = _resolve_gallery_targets(library_id, app)
        if not targets:
            return {'success': False, 'message': '未找到该库的磁盘目录（resourced 不可用或配置缺失）'}

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
            # 若某个子目录本身含图片，则该子目录很可能是另一本图集，当前目录不算
            sub_has_images = any(
                os.path.isdir(os.path.join(dirpath, d)) and _dir_has_image_children(os.path.join(dirpath, d))
                for d in dirnames
            )
            if len(images) >= min_pages and not sub_has_images:
                pages = _list_images(dirpath)
                if not pages:
                    continue
                chash = Gallery.generate_hash(dirpath, pages)
                seen_hashes.add(chash)
                with app.app_context():
                    existing = Gallery.query.filter_by(hash=chash).first()
                    if existing:
                        changed = False
                        if existing.folder_path != dirpath:
                            existing.folder_path = dirpath
                            changed = True
                        # 图片集合变化则重建页面
                        if existing.page_count != len(pages):
                            changed = True
                        # 文件夹内容修改时间更新（图片被原地替换/增删）也需重建，
                        # 否则内部图片被替换但数量不变时不会被感知，看到旧图。
                        try:
                            folder_mtime = os.path.getmtime(dirpath)
                        except OSError:
                            folder_mtime = 0.0
                        existing_ts = existing.updated_at.replace(tzinfo=timezone.utc).timestamp() if existing.updated_at else 0.0
                        if folder_mtime > existing_ts + 1.0:  # 容忍 1 秒误差，避免时区/精度抖动误触发
                            changed = True
                        if changed:
                            existing.page_count = len(pages)
                            existing.updated_at = datetime.utcnow()
                            _sync_pages(existing, pages)
                            db.session.commit()
                            updated += 1
                    else:
                        c = Gallery(
                            hash=chash,
                            title=os.path.basename(dirpath.rstrip(os.sep)),
                            folder_path=dirpath,
                            page_count=len(pages),
                            library_id=library_id,
                            owner_id=root_id,  # 扫描发现的资源归属 root
                        )
                        db.session.add(c)
                        db.session.flush()
                        # 统一封面入口：新建图集时即把封面写入资源索引
                        if c.resource_index and not c.resource_index.cover:
                            c.resource_index.cover = f'/gallery-cover/{c.hash}'
                        _sync_pages(c, pages)
                        db.session.commit()
                        added += 1

    # 清理：库中已不存在（或磁盘目录已删除）的图集
    with app.app_context():
        for c in Gallery.query.filter_by(library_id=library_id).all():
            if c.hash not in seen_hashes or not (c.folder_path and os.path.isdir(c.folder_path)):
                db.session.delete(c)
                removed += 1
        db.session.commit()
        total = Gallery.query.filter_by(library_id=library_id).count()

    debug('INFO', f'[GalleryScan] 库 {library_id}: 新增 {added}, 更新 {updated}, 清理 {removed}, 现存 {total}')
    return {'success': True, 'added': added, 'updated': updated, 'removed': removed, 'total': total}


def scan_all_galleries(app, log=None):
    """扫描所有资源库（供需要时一次性全量扫描）。"""
    from core.models import ResourceLibrary
    results = []
    with app.app_context():
        libs = ResourceLibrary.query.filter_by(is_active=True).all()
    for lib in libs:
        results.append(scan_library_galleries(lib.id, app, log=log))
    return results
