# -*- coding: utf-8 -*-
"""跨蓝图共享的纯业务辅助函数。

从 main.py 下沉而来，统一收敛到本模块，供所有蓝图直接 import。

本模块只依赖 core.models / resource.models（可选）/ liblog，不依赖 main。
"""
import os
from flask import request, jsonify, Response

from core.models import (
    db, Video, Tag, VideoTag, UserInteraction, UserPreference,
    ResourceIndex, Gallery, PostRef, ResourceLibrary,
)
from liblog import get_service_logger

log = get_service_logger('dbox-web')


def _json_response(payload):
    """构造 JSON 响应（不依赖应用上下文，便于在任意位置调用）。"""
    return Response(
        __import__('json').dumps(payload, ensure_ascii=False),
        mimetype='application/json',
    )


def success_response(data=None, message='', code=0):
    """统一成功响应：{success, data, code, message}。"""
    return _json_response({'success': True, 'code': code, 'message': message, 'data': data})


def error_response(message='', code=1, data=None):
    """统一错误响应：{success, data, code, message}。"""
    return _json_response({'success': False, 'code': code, 'message': message, 'data': data})


def _do_update_tag(tag_id):
    """更新标签的实际逻辑"""
    try:
        tag = Tag.query.get_or_404(tag_id)
        data = request.get_json()

        name = data.get('name', '').strip()
        if name:
            if len(name) < 2 or len(name) > 20:
                return jsonify({'success': False, 'message': '标签名长度需在2-20字符之间'}), 400

            existing = Tag.query.filter_by(name=name).first()
            if existing and existing.id != tag_id:
                return jsonify({'success': False, 'message': '标签名已存在'}), 400

            tag.name = name

        if 'category' in data:
            tag.category = data['category'].strip() or '类型'

        if 'qualifiers' in data:
            tag.set_qualifiers(data['qualifiers'])

        if 'parent_id' in data:
            new_parent_id = data['parent_id']
            if new_parent_id:
                parent_tag = Tag.query.get(new_parent_id)
                if not parent_tag:
                    return jsonify({'success': False, 'message': '父标签不存在'}), 400
                child_ids = tag.get_all_child_ids()
                if new_parent_id in child_ids:
                    return jsonify({'success': False, 'message': '不能设置自己的子标签为父标签'}), 400
            tag.parent_id = new_parent_id

        db.session.commit()
        log.maintenance('INFO', f"更新标签: {tag.name} (ID: {tag_id})")
        return jsonify({'success': True, 'tag': tag.to_dict()})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"更新标签失败: {tag_id}, {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# ---------------------------------------------------------------------------
# 资源库 ID 映射（dbox.db <-> resource.db）
# ---------------------------------------------------------------------------
try:
    from resource.models import ResourceLibraryDB, ResourceFolderDB
    _HAS_RESOURCE_DB = True
except Exception:
    _HAS_RESOURCE_DB = False


def _resolve_resource_library_id(dbox_library_id: int) -> int:
    """将 dbox.db 的资源库 ID 映射为 resource.db 的资源库 ID（按名称匹配）。"""
    if not _HAS_RESOURCE_DB:
        return dbox_library_id

    library = ResourceLibrary.query.get(dbox_library_id)
    if not library:
        return dbox_library_id

    all_resources = ResourceLibraryDB.get_all()
    for res_lib in all_resources:
        if res_lib.name == library.name:
            return res_lib.id
    return dbox_library_id


def _ensure_resource_library(dbox_library_id: int, fallback_path: str = None) -> int:
    """确保 dbox.db 的资源库已在 resource 服务（resourced）中注册。

    资源服务以自身维护的 resource.db 为准，按名称匹配。若同名库不存在，
    则通过总线调用 AddLibrary 完成注册（用首个文件夹路径或兜底目录作为库路径），
    避免后续 AddFolder / 扫描等操作因「库不存在」而失败。

    返回 resource.db 中的库 ID；注册失败时回退为 dbox 库 ID，由调用方继续处理。
    """
    res_lib_id = _resolve_resource_library_id(dbox_library_id)
    if res_lib_id != dbox_library_id:
        # 已注册
        return res_lib_id

    if not _HAS_RESOURCE_DB:
        return dbox_library_id

    library = ResourceLibrary.query.get(dbox_library_id)
    if not library:
        return dbox_library_id

    # 延迟导入运行时总线，避免循环依赖
    try:
        from backend.runtime import runtime
    except Exception:
        return dbox_library_id

    if not runtime.resource_bus:
        return dbox_library_id

    # 选择一个有效的目录作为库路径：优先传入的文件夹路径，其次首个已登记文件夹
    path = fallback_path
    if not path or not os.path.isdir(path):
        try:
            folders = ResourceFolderDB.query.filter_by(library_id=res_lib_id).all()
            for f in folders:
                if f.path and os.path.isdir(f.path):
                    path = f.path
                    break
        except Exception:
            pass
    if not path or not os.path.isdir(path):
        from backend.paths import DATA_DIR
        path = DATA_DIR

    try:
        result = runtime.resource_bus.call_method(
            'com.dbox.resourced', 'com.dbox.Resourced', 'AddLibrary',
            {'name': library.name, 'path': path},
            timeout=3000,
        )
    except Exception as e:
        log.debug('ERROR', f"注册资源库到 resourced 失败: {e}")
        return dbox_library_id

    if result and result.get('success'):
        new_id = result.get('library_id') or result.get('id')
        if new_id:
            return new_id
    log.debug('WARN', f"资源库({library.name})注册未返回成功: {result}")
    return dbox_library_id



def _resolve_dbox_library_id_by_folder(folder_id):
    """folder_id 为 resourced 的文件夹 id，反查对应的 dbox 资源库 id。"""
    if not _HAS_RESOURCE_DB:
        return None
    try:
        folder = ResourceFolderDB.get_by_id(folder_id)
        if not folder:
            return None
        rl = ResourceLibraryDB.get_by_id(folder.library_id)
        if not rl:
            return None
        lib = ResourceLibrary.query.filter_by(name=rl.name).first()
        return lib.id if lib else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 用户交互（点赞/踩/收藏偏好）
# ---------------------------------------------------------------------------
def record_interaction(video_id, user_session, interaction_type, score=1.0):
    try:
        interaction = UserInteraction(
            video_id=video_id,
            user_session=user_session,
            interaction_type=interaction_type,
            interaction_score=score,
        )
        db.session.add(interaction)

        video_tags = VideoTag.query.filter_by(video_id=video_id).all()
        for vt in video_tags:
            pref = UserPreference.query.filter_by(
                user_session=user_session, tag_id=vt.tag_id
            ).first()
            if pref:
                pref.preference_score += score * 0.1
                pref.interaction_count += 1
            else:
                pref = UserPreference(
                    user_session=user_session,
                    tag_id=vt.tag_id,
                    preference_score=1.0 + score * 0.1,
                    interaction_count=1,
                )
                db.session.add(pref)
        db.session.commit()
    except Exception as e:
        log.debug('ERROR', f'记录交互失败: {e}')
        db.session.rollback()


def _ensure_interaction(video, user_session, itype, score):
    """确保存在某条交互记录（用于批量添加，幂等）。"""
    interaction = UserInteraction.query.filter_by(
        video_id=video.id, user_session=user_session, interaction_type=itype
    ).first()
    if not interaction:
        interaction = UserInteraction(
            video_id=video.id, user_session=user_session,
            interaction_type=itype, interaction_score=score,
        )
        db.session.add(interaction)
        db.session.flush()
    return interaction


# ---------------------------------------------------------------------------
# 标签树 / 层级标签
# ---------------------------------------------------------------------------
def _build_tag_tree(tags):
    """将扁平标签列表转换为树形结构。"""
    tag_map = {tag['id']: {**tag, 'children': []} for tag in tags}
    tree = []
    for tag in tags:
        tag_node = tag_map[tag['id']]
        if tag['parent_id'] is None or tag['parent_id'] not in tag_map:
            tree.append(tag_node)
        else:
            tag_map[tag['parent_id']]['children'].append(tag_node)
    return tree


def get_or_create_tag_by_path(tag_path: str, library_id=None, category='类型'):
    """根据路径获取或创建标签（支持层级），如 "/动物/狗/哈士奇"。"""
    tag_path = tag_path.strip()
    if not tag_path.startswith('/'):
        tag_path = '/' + tag_path

    parts = [p for p in tag_path.split('/') if p]
    if not parts:
        return None

    parent_id = None
    current_path = ''

    for i, part in enumerate(parts):
        current_path = '/' + part if i == 0 else current_path + '/' + part
        existing_tag = Tag.query.filter(Tag.path == current_path).order_by(Tag.id.asc()).first()
        if existing_tag:
            parent_id = existing_tag.id
        else:
            new_tag = Tag(
                name=part,
                path=current_path,
                category=category,
                parent_id=parent_id,
                library_id=library_id,
            )
            db.session.add(new_tag)
            db.session.flush()
            parent_id = new_tag.id

    return Tag.query.filter(Tag.path == current_path).order_by(Tag.id.asc()).first()


# ---------------------------------------------------------------------------
# 帖子引用解析
# ---------------------------------------------------------------------------
def _resolve_post_refs(refs):
    """将请求体中的引用解析为 (ResourceIndex, note) 列表。"""
    result = []
    if not refs:
        return result
    for r in refs:
        if not isinstance(r, dict):
            continue
        ri_id = r.get('resource_index_id')
        if not ri_id:
            typ = (r.get('type') or r.get('kind') or '').lower()
            eid = r.get('id')
            if typ in ('video', 'video_file') and eid:
                v = Video.query.get(eid)
                if v and v.resource_index_id:
                    ri_id = v.resource_index_id
            elif typ in ('gallery', 'gallery_folder', 'image_set') and eid:
                c = Gallery.query.get(eid)
                if c and c.resource_index_id:
                    ri_id = c.resource_index_id
        if ri_id:
            ri = ResourceIndex.query.get(ri_id)
            if ri:
                result.append((ri, r.get('note', '') or ''))
    return result


def _build_post_refs(content, refs_param):
    """由帖子正文的内联标记构建 PostRef 列表（含 display_mode）。"""
    from core.models import parse_post_content_tokens
    tokens = parse_post_content_tokens(content or '')
    built = []
    if tokens:
        for pos, t in enumerate(tokens):
            ri = ResourceIndex.query.get(t['resource_index_id'])
            if ri:
                built.append(PostRef(
                    resource_index_id=ri.id, position=pos,
                    note='', display_mode=t['display_mode']))
        return built
    for pos, (ri, note) in enumerate(_resolve_post_refs(refs_param)):
        built.append(PostRef(
            resource_index_id=ri.id, position=pos,
            note=note, display_mode='embed'))
    return built
