"""合集模块 API（独立于收藏夹）。

合集是「视频/图集的属性」，全站共享、不跟随用户：
- 任意登录用户看到的是同一套合集；
- 一个资源可同时属于多个合集；
- owner_key 仅作为创建者审计字段保留，不再用于查询隔离。

权限：
- 查看：所有登录用户；
- 删除/重命名合集：仅创建者（owner_key 匹配）或管理员（role 2/3）可操作。
  其余变更（增删项、排序）开放给登录用户协作编辑。

接口统一前缀 /api/collections。资源身份使用 hash（视频 Video.hash / 图集 Gallery.hash），
与文件名称/路径解耦，与系统现有“hash 为唯一 key”的约定保持一致。
"""
from flask import Blueprint, jsonify, request

from core.models import db, MediaCollection, MediaCollectionItem, Video, Gallery

collection_set_api = Blueprint('collection_set_api', __name__, url_prefix='/api/collections')


def _owner():
    # 创建者审计字段（仅记录，不用于查询隔离）。延迟导入避免循环依赖。
    from main import current_interaction_key
    return current_interaction_key()


def _can_manage(collection):
    """删除/重命名等结构性操作：仅创建者或管理员可操作，否则返回 403 响应。"""
    from main import current_interaction_key, resolve_identity
    user_id, role = resolve_identity()
    if user_id and role in (2, 3):
        return None
    if collection.owner_key == current_interaction_key():
        return None
    return jsonify({'success': False, 'message': '无权操作该合集（仅创建者或管理员可修改）'}), 403


def _resolve_media(item_type, item_hash):
    """把合集项解析为前端可直接渲染的媒体信息。"""
    if item_type == 'gallery':
        c = Gallery.query.filter_by(hash=item_hash).first()
        if not c:
            return None
        d = c.to_dict()
        d['type'] = 'gallery'
        d['cover_url'] = f'/gallery-cover/{c.hash}'
        d['added_at'] = None
        return d
    v = Video.query.filter_by(hash=item_hash).first()
    if not v:
        return None
    d = v.to_dict()
    d['type'] = 'video'
    d['added_at'] = None
    return d


def _collection_cover(cid):
    """取合集内第一个资源作为封面（视频用 thumbnail，图集用 gallery-cover）。"""
    first = MediaCollectionItem.query.filter_by(collection_id=cid).order_by(
        MediaCollectionItem.position, MediaCollectionItem.id).first()
    if not first:
        return ''
    media = _resolve_media(first.item_type, first.item_hash)
    if not media:
        return ''
    return media.get('cover_url') or media.get('thumbnail') or ''


def _serialize(collection, item_count=None):
    d = collection.to_dict(item_count=item_count)
    d['cover_url'] = _collection_cover(collection.id)
    return d


@collection_set_api.route('/', methods=['GET'], strict_slashes=False)
def list_collections():
    try:
        cols = MediaCollection.query.order_by(
            MediaCollection.position, MediaCollection.id).all()
        result = []
        for c in cols:
            count = MediaCollectionItem.query.filter_by(collection_id=c.id).count()
            result.append(_serialize(c, item_count=count))
        return jsonify({'success': True, 'collections': result})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@collection_set_api.route('/', methods=['POST'], strict_slashes=False)
def create_collection():
    try:
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'success': False, 'message': '名称不能为空'}), 400
        max_pos = db.session.query(db.func.max(MediaCollection.position)).scalar() or 0
        col = MediaCollection(
            owner_key=_owner(),
            name=name,
            description=data.get('description'),
            is_public=bool(data.get('is_public', True)),
            position=max_pos + 1,
        )
        db.session.add(col)
        db.session.commit()
        return jsonify({'success': True, 'collection': _serialize(col, item_count=0)})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@collection_set_api.route('/<int:cid>', methods=['GET'])
def get_collection(cid):
    try:
        col = MediaCollection.query.filter_by(id=cid).first_or_404()
        count = MediaCollectionItem.query.filter_by(collection_id=col.id).count()
        return jsonify({'success': True, 'collection': _serialize(col, item_count=count)})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@collection_set_api.route('/<int:cid>', methods=['PUT'])
def update_collection(cid):
    try:
        col = MediaCollection.query.filter_by(id=cid).first_or_404()
        denied = _can_manage(col)
        if denied:
            return denied
        data = request.get_json(silent=True) or {}
        if 'name' in data and data['name']:
            col.name = data['name'].strip()
        if 'description' in data:
            col.description = data['description']
        if 'is_public' in data:
            col.is_public = bool(data['is_public'])
        if 'position' in data:
            col.position = int(data['position'])
        db.session.commit()
        count = MediaCollectionItem.query.filter_by(collection_id=col.id).count()
        return jsonify({'success': True, 'collection': _serialize(col, item_count=count)})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@collection_set_api.route('/<int:cid>', methods=['DELETE'])
def delete_collection(cid):
    try:
        col = MediaCollection.query.filter_by(id=cid).first_or_404()
        denied = _can_manage(col)
        if denied:
            return denied
        db.session.delete(col)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@collection_set_api.route('/<int:cid>/items', methods=['GET'])
def list_collection_items(cid):
    try:
        col = MediaCollection.query.filter_by(id=cid).first_or_404()
        items = MediaCollectionItem.query.filter_by(collection_id=col.id).order_by(
            MediaCollectionItem.position, MediaCollectionItem.id).all()
        result = []
        for it in items:
            media = _resolve_media(it.item_type, it.item_hash)
            if media is None:
                continue
            result.append(it.to_dict(media=media))
        return jsonify({'success': True, 'items': result, 'collection': _serialize(col, item_count=len(result))})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@collection_set_api.route('/<int:cid>/items', methods=['POST'])
def add_collection_item(cid):
    try:
        col = MediaCollection.query.filter_by(id=cid).first_or_404()
        data = request.get_json(silent=True) or {}
        item_type = data.get('item_type')
        item_hash = data.get('item_hash')
        if item_type not in ('video', 'gallery') or not item_hash:
            return jsonify({'success': False, 'message': '参数错误'}), 400
        media = _resolve_media(item_type, item_hash)
        if media is None:
            return jsonify({'success': False, 'message': '资源不存在'}), 404
        existing = MediaCollectionItem.query.filter_by(
            collection_id=cid, item_type=item_type, item_hash=item_hash).first()
        if existing:
            return jsonify({'success': True, 'item': existing.to_dict(media=media), 'message': '已在合集中'})
        pos = data.get('position')
        if pos is None:
            pos = (db.session.query(db.func.max(MediaCollectionItem.position)).filter_by(collection_id=cid).scalar() or 0) + 1
        item = MediaCollectionItem(
            collection_id=cid, owner_key=_owner(), item_type=item_type,
            item_hash=item_hash, position=int(pos))
        db.session.add(item)
        db.session.commit()
        return jsonify({'success': True, 'item': item.to_dict(media=media)})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@collection_set_api.route('/<int:cid>/items/reorder', methods=['POST'])
def reorder_collection_items(cid):
    try:
        col = MediaCollection.query.filter_by(id=cid).first_or_404()
        data = request.get_json(silent=True) or {}
        ordered_ids = data.get('ordered_ids') or []
        for idx, item_id in enumerate(ordered_ids):
            it = MediaCollectionItem.query.filter_by(id=item_id, collection_id=cid).first()
            if it:
                it.position = idx
        db.session.commit()
        items = MediaCollectionItem.query.filter_by(collection_id=cid).order_by(
            MediaCollectionItem.position, MediaCollectionItem.id).all()
        result = [it.to_dict(media=_resolve_media(it.item_type, it.item_hash)) for it in items]
        return jsonify({'success': True, 'items': result})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@collection_set_api.route('/<int:cid>/items/<int:item_id>', methods=['DELETE'])
def remove_collection_item(cid, item_id):
    try:
        col = MediaCollection.query.filter_by(id=cid).first_or_404()
        it = MediaCollectionItem.query.filter_by(id=item_id, collection_id=cid).first_or_404()
        db.session.delete(it)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500


@collection_set_api.route('/by-item', methods=['GET'])
def collections_by_item():
    """反向查询：某资源所属的全部合集（全站共享，不按用户隔离）。供播放器/阅读器展示“所属合集”。"""
    try:
        item_type = request.args.get('item_type')
        item_hash = request.args.get('item_hash')
        if item_type not in ('video', 'gallery') or not item_hash:
            return jsonify({'success': False, 'message': '参数错误'}), 400
        rows = MediaCollectionItem.query.filter_by(item_type=item_type, item_hash=item_hash).all()
        collection_ids = {r.collection_id for r in rows}
        result = []
        for cid in collection_ids:
            col = MediaCollection.query.filter_by(id=cid).first()
            if not col:
                continue
            count = MediaCollectionItem.query.filter_by(collection_id=cid).count()
            d = _serialize(col, item_count=count)
            d['item_position'] = next((r.position for r in rows if r.collection_id == cid), None)
            result.append(d)
        result.sort(key=lambda x: (x['position'] or 0, x['id']))
        return jsonify({'success': True, 'collections': result})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
