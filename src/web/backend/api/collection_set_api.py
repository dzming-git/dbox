# -*- coding: utf-8 -*-
"""用户自建合集（跨类型清单）。

⚠️ 这段接口是被「补」出来的：前端 Collections 页面与视频详情的「加入合集」
面板一直在调用 `/api/collections`，而**后端从来没有这个路由**（实测 404），
导致整个合集功能（建合集 / 加条目 / 排序 / 详情页显示所属合集）长期不可用。
前端代码与产品文档都把它当成既有能力，因此这里按前端既有契约补齐后端，
而不是改前端去迁就后端。

与 `/api/mode-collections`（模式内分组，服务于资源组织）是两套东西：
那是「某次爬取的一批图文」，这是「用户想凑在一起看的清单」。
"""
import os
from urllib.parse import quote

from flask import Blueprint, request, jsonify, Response

from core.models import db, CollectionSet, CollectionSetItem, Video, Gallery, Post
from backend.access import current_interaction_key
from liblog import get_service_logger

log = get_service_logger('dbox-web')

bp = Blueprint('collection_set', __name__)

_ITEM_TYPES = ('video', 'gallery', 'post', 'text')


def _owned(query):
    """当前身份可见的合集：自己的 + 公开的。"""
    key = current_interaction_key()
    return query.filter(
        db.or_(CollectionSet.owner_key == key, CollectionSet.is_public.is_(True))
    ) if key else query.filter(CollectionSet.is_public.is_(True))


def _enrich(item):
    """把一条成员记录富化成前端需要的 { id, media: {...} }。

    展示信息一律回源富化实体，不在成员表里存快照——否则资源改名或换封面后，
    合集里会一直显示旧信息。
    """
    media = None
    if item.item_type == 'video':
        v = Video.query.filter_by(hash=item.item_id).first()
        if v:
            media = {
                'type': 'video',
                'hash': v.hash,
                'title': v.title,
                'thumbnail': v.cover_url,
                'duration': v.duration,
            }
    elif item.item_type == 'gallery':
        c = Gallery.query.filter_by(hash=item.item_id).first()
        if c:
            media = {
                'type': 'gallery',
                'hash': c.hash,
                'title': c.title,
                'cover_url': c.cover_path,
                'page_count': c.page_count,
            }
    elif item.item_type == 'post':
        p = Post.query.get(item.item_id)
        if p:
            media = {'type': 'post', 'id': p.id, 'title': p.title}
    if media is None:
        # 实体已被删除：仍然返回占位，让人能在合集里看到并移除它
        media = {'type': item.item_type,
                 'hash' if item.item_type in ('video', 'gallery') else 'id': item.item_id,
                 'title': '(内容已不存在)', 'missing': True}
    return {'id': item.id, 'item_type': item.item_type, 'item_id': item.item_id,
            'media': media}


@bp.route('/api/collections', methods=['GET'])
def list_collections():
    try:
        rows = _owned(CollectionSet.query).order_by(
            CollectionSet.updated_at.desc()).all()
        return jsonify({'success': True, 'collections': [c.to_dict() for c in rows]})
    except Exception as e:
        log.debug('ERROR', f'获取合集列表失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/collections', methods=['POST'])
def create_collection():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'message': '名称不能为空'}), 400
    key = current_interaction_key()
    if not key:
        return jsonify({'success': False, 'message': '无法识别身份'}), 401
    try:
        c = CollectionSet(
            name=name,
            description=(data.get('description') or '').strip() or None,
            is_public=bool(data.get('is_public')),
            owner_key=key,
        )
        db.session.add(c)
        db.session.commit()
        return jsonify({'success': True, 'collection': c.to_dict()})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f'创建合集失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/collections/<int:collection_id>', methods=['GET'])
def get_collection(collection_id):
    c = CollectionSet.query.get(collection_id)
    if not c:
        return jsonify({'success': False, 'message': '合集不存在'}), 404
    return jsonify({'success': True, 'collection': c.to_dict()})


@bp.route('/api/collections/<int:collection_id>', methods=['PUT'])
def update_collection(collection_id):
    c = CollectionSet.query.get(collection_id)
    if not c:
        return jsonify({'success': False, 'message': '合集不存在'}), 404
    key = current_interaction_key()
    # 只有作者本人能改；管理员（后台）不受此限——此处按作者判定即可，
    # 前台界面同样只在作者视角展示编辑入口。
    if key and c.owner_key != key:
        return jsonify({'success': False, 'message': '无权修改他人合集'}), 403
    data = request.get_json(silent=True) or {}
    try:
        if 'name' in data:
            name = (data.get('name') or '').strip()
            if not name:
                return jsonify({'success': False, 'message': '名称不能为空'}), 400
            c.name = name
        if 'description' in data:
            c.description = (data.get('description') or '').strip() or None
        if 'is_public' in data:
            c.is_public = bool(data.get('is_public'))
        db.session.commit()
        return jsonify({'success': True, 'collection': c.to_dict()})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f'更新合集失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/collections/<int:collection_id>', methods=['DELETE'])
def delete_collection(collection_id):
    c = CollectionSet.query.get(collection_id)
    if not c:
        return jsonify({'success': False, 'message': '合集不存在'}), 404
    key = current_interaction_key()
    if key and c.owner_key != key:
        return jsonify({'success': False, 'message': '无权删除他人合集'}), 403
    try:
        db.session.delete(c)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f'删除合集失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/collections/<int:collection_id>/m3u', methods=['GET'])
def export_m3u(collection_id):
    """把合集导出为 M3U 播放列表（通用格式，任何播放器都能打开）。

    只写仍然存在的本地视频：导一份点不开的列表没有意义。
    归属判定与读取一致——自己的、公开的合集可导出。
    """
    c = _owned(CollectionSet.query).filter(CollectionSet.id == collection_id).first()
    if not c:
        return jsonify({'success': False, 'message': '合集不存在或无权导出'}), 404
    rows = (CollectionSetItem.query
            .filter_by(collection_id=collection_id)
            .order_by(CollectionSetItem.position, CollectionSetItem.id)
            .all())
    lines = ['#EXTM3U']
    kept = 0
    for it in rows:
        if it.item_type != 'video':
            continue  # M3U 只承载可播放的视频
        v = Video.query.filter_by(hash=it.item_id).first()
        path = (v.resource_index.location if (v and v.resource_index) else None)
        if not path or not os.path.exists(path):
            continue
        lines.append(f'#EXTINF:-1,{v.title or os.path.splitext(os.path.basename(path))[0]}')
        lines.append(path)
        kept += 1

    body = '\n'.join(lines) + '\n'
    safe = ''.join(ch for ch in (c.name or '') if ch not in r'\/:*?"<>|').strip() or 'collection'
    # ⚠️ 文件名必须百分号编码（RFC 5987）：直接把中文塞进 Content-Disposition
    # 会产生非法响应头，表现为**请求永远挂着不返回**（实测中文名超时、ASCII 名 0.0s 正常）。
    # 同时给出 ASCII 兜底名，老客户端也能存下文件。
    encoded = quote(f'{safe}.m3u')
    return Response(
        body.encode('utf-8'),
        mimetype='audio/x-mpegurl; charset=utf-8',
        headers={
            'Content-Disposition': f"attachment; filename=\"playlist.m3u\"; filename*=UTF-8''{encoded}",
            'X-Export-Kept': str(kept),
        },
    )


@bp.route('/api/collections/<int:collection_id>/items', methods=['GET'])
def list_items(collection_id):
    c = CollectionSet.query.get(collection_id)
    if not c:
        return jsonify({'success': False, 'message': '合集不存在'}), 404
    try:
        rows = (CollectionSetItem.query
                .filter_by(collection_id=collection_id)
                .order_by(CollectionSetItem.position, CollectionSetItem.id)
                .all())
        return jsonify({'success': True, 'items': [_enrich(r) for r in rows]})
    except Exception as e:
        log.debug('ERROR', f'获取合集条目失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/collections/<int:collection_id>/items', methods=['POST'])
def add_item(collection_id):
    c = CollectionSet.query.get(collection_id)
    if not c:
        return jsonify({'success': False, 'message': '合集不存在'}), 404
    data = request.get_json(silent=True) or {}
    item_type = (data.get('item_type') or '').strip()
    item_id = str(data.get('item_hash') or data.get('item_id') or '').strip()
    if item_type not in _ITEM_TYPES or not item_id:
        return jsonify({'success': False, 'message': '条目类型或标识无效'}), 400
    try:
        exists = CollectionSetItem.query.filter_by(
            collection_id=collection_id, item_type=item_type, item_id=item_id).first()
        if exists:
            return jsonify({'success': True, 'item': _enrich(exists), 'duplicated': True})
        nxt = (db.session.query(db.func.max(CollectionSetItem.position))
               .filter_by(collection_id=collection_id).scalar() or 0)
        it = CollectionSetItem(collection_id=collection_id, item_type=item_type,
                               item_id=item_id, position=nxt + 1)
        db.session.add(it)
        db.session.commit()
        return jsonify({'success': True, 'item': _enrich(it)})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f'添加合集条目失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/collections/<int:collection_id>/items/reorder', methods=['POST'])
def reorder_items(collection_id):
    c = CollectionSet.query.get(collection_id)
    if not c:
        return jsonify({'success': False, 'message': '合集不存在'}), 404
    data = request.get_json(silent=True) or {}
    ordered = data.get('ordered_ids') or []
    try:
        for idx, item_id in enumerate(ordered):
            it = CollectionSetItem.query.filter_by(id=item_id,
                                                   collection_id=collection_id).first()
            if it:
                it.position = idx
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f'合集排序失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/collections/<int:collection_id>/items/<int:item_id>', methods=['DELETE'])
def remove_item(collection_id, item_id):
    it = CollectionSetItem.query.filter_by(id=item_id,
                                           collection_id=collection_id).first()
    if not it:
        return jsonify({'success': False, 'message': '条目不存在'}), 404
    try:
        db.session.delete(it)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f'移除合集条目失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/collections/by-item', methods=['GET'])
def collections_by_item():
    """某条内容属于哪些合集（详情面板用来显示已加入状态）。"""
    item_type = (request.args.get('item_type') or '').strip()
    item_id = (request.args.get('item_hash') or '').strip()
    if not item_type or not item_id:
        return jsonify({'success': False, 'message': '缺少条目标识'}), 400
    try:
        q = (CollectionSet.query
             .join(CollectionSetItem,
                   CollectionSetItem.collection_id == CollectionSet.id)
             .filter(CollectionSetItem.item_type == item_type,
                     CollectionSetItem.item_id == item_id))
        rows = _owned(q).all()
        return jsonify({'success': True, 'collections': [c.to_dict() for c in rows]})
    except Exception as e:
        log.debug('ERROR', f'查询条目所属合集失败: {e}')
        return jsonify({'success': False, 'message': str(e)}), 500
