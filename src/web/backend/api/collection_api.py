"""Auto-split blueprint: collection_api (moved from main.py)."""
from flask import Blueprint, request, jsonify, send_file, send_from_directory, session, g, abort, Response, current_app

bp = Blueprint('collection_api', __name__)

@bp.route('/api/favorite-collections', methods=['GET'])
def list_favorite_collections():
    import main
    try:
        key = main.current_interaction_key()
        cols = main.FavoriteCollection.query.filter_by(user_session=key).order_by(
            main.FavoriteCollection.position.asc(), main.FavoriteCollection.created_at.asc()
        ).all()
        return main.jsonify({'success': True, 'collections': [c.to_dict() for c in cols]})
    except Exception as e:
        return main.jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/favorite-collections', methods=['POST'])
def create_favorite_collection():
    import main
    try:
        data = main.request.get_json(force=True) or {}
        name = (data.get('name') or '').strip()
        if not name:
            return main.jsonify({'success': False, 'message': '名称不能为空'}), 400
        key = main.current_interaction_key()
        max_pos = main.db.session.query(main.db.func.max(main.FavoriteCollection.position)).filter_by(
            user_session=key).scalar() or 0
        col = main.FavoriteCollection(user_session=key, name=name, position=(max_pos + 1))
        main.db.session.add(col)
        main.db.session.commit()
        return main.jsonify({'success': True, 'collection': col.to_dict()})
    except Exception as e:
        main.db.session.rollback()
        return main.jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/favorite-collections/<int:collection_id>', methods=['DELETE'])
def delete_favorite_collection(collection_id):
    import main
    try:
        key = main.current_interaction_key()
        col = main.FavoriteCollection.query.filter_by(id=collection_id, user_session=key).first_or_404()
        main.db.session.delete(col)
        main.db.session.commit()
        return main.jsonify({'success': True})
    except Exception as e:
        main.db.session.rollback()
        return main.jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/favorite-collections/<int:collection_id>/videos', methods=['GET'])
def list_collection_videos(collection_id):
    import main
    """收藏夹内容（视频 + 图集，通过 type 区分）。"""
    try:
        key = main.current_interaction_key()
        col = main.FavoriteCollection.query.filter_by(id=collection_id, user_session=key).first_or_404()
        items = main.CollectionVideo.query.filter_by(collection_id=col.id, user_session=key).all()
        videos = []
        for it in items:
            if it.item_type == 'gallery':
                c = main.Gallery.query.get(it.gallery_id)
                if not c:
                    continue
                d = c.to_dict()
                d['type'] = 'gallery'
                d['cover_url'] = c.cover_url or f'/gallery-cover/{c.hash}'
                d['favorited_at'] = it.created_at.isoformat() if it.created_at else None
                videos.append(d)
            else:
                video = main.Video.query.get(it.video_id)
                if not video or video.in_trash:
                    continue
                v = video.to_dict()
                v['type'] = 'video'
                v['favorited_at'] = it.created_at.isoformat() if it.created_at else None
                videos.append(v)
        return main.jsonify({'success': True, 'videos': videos, 'total': len(videos)})
    except Exception as e:
        return main.jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/favorite-collections/<int:collection_id>/videos', methods=['POST'])
def add_to_collection(collection_id):
    import main
    """加入收藏夹，支持视频或图集（body: {type, hash}）。"""
    data = main.request.get_json(force=True) or {}
    try:
        key = main.current_interaction_key()
        col = main.FavoriteCollection.query.filter_by(id=collection_id, user_session=key).first_or_404()
        item_type = data.get('type', 'video')
        item_hash = data.get('hash')
        if not item_hash:
            return main.jsonify({'success': False, 'message': '缺少资源标识'}), 400
        if item_type == 'gallery':
            gallery = main.Gallery.query.filter_by(hash=item_hash).first_or_404()
            exists = main.CollectionVideo.query.filter_by(
                collection_id=col.id, user_session=key, item_type='gallery', gallery_id=gallery.id).first()
            if not exists:
                main.db.session.add(main.CollectionVideo(
                    collection_id=col.id, user_session=key, item_type='gallery', gallery_id=gallery.id))
        else:
            video = main.Video.query.filter_by(hash=item_hash).first_or_404()
            exists = main.CollectionVideo.query.filter_by(
                collection_id=col.id, user_session=key, item_type='video', video_id=video.id).first()
            if not exists:
                main.db.session.add(main.CollectionVideo(
                    collection_id=col.id, user_session=key, item_type='video', video_id=video.id))
        main.db.session.commit()
        return main.jsonify({'success': True})
    except Exception as e:
        main.db.session.rollback()
        return main.jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/favorite-collections/<int:collection_id>/videos', methods=['DELETE'])
def remove_from_collection(collection_id):
    import main
    """从收藏夹移除（body: {type, hash}）。"""
    data = main.request.get_json(force=True) or {}
    try:
        key = main.current_interaction_key()
        col = main.FavoriteCollection.query.filter_by(id=collection_id, user_session=key).first_or_404()
        item_type = data.get('type', 'video')
        item_hash = data.get('hash')
        if item_type == 'gallery':
            gallery = main.Gallery.query.filter_by(hash=item_hash).first_or_404()
            item = main.CollectionVideo.query.filter_by(
                collection_id=col.id, user_session=key, item_type='gallery', gallery_id=gallery.id).first()
        else:
            video = main.Video.query.filter_by(hash=item_hash).first_or_404()
            item = main.CollectionVideo.query.filter_by(
                collection_id=col.id, user_session=key, item_type='video', video_id=video.id).first()
        if item:
            main.db.session.delete(item)
            main.db.session.commit()
        return main.jsonify({'success': True})
    except Exception as e:
        main.db.session.rollback()
        return main.jsonify({'success': False, 'message': str(e)}), 500
