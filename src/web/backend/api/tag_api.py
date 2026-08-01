"""Auto-split blueprint: tag_api (moved from main.py)."""
from backend.helpers import _do_update_tag
from core.models import Tag
from core.models import VideoTag
from core.models import db
from flask import Blueprint, request, jsonify, send_file, send_from_directory, session, g, abort, Response, current_app
from liblog import get_service_logger
log = get_service_logger('dplayer-web')

bp = Blueprint('tag_api', __name__)

@bp.route('/api/tags', methods=['POST'])
def create_tag():
    """创建新标签 - 支持多级标签，按路径+资源库判断唯一性"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        qualifiers_raw = data.get('qualifiers')
        if not name:
            return jsonify({'success': False, 'message': '标签名不能为空'}), 400
        
        if len(name) < 1 or len(name) > 20:
            return jsonify({'success': False, 'message': '标签名长度需在1-20字符之间'}), 400
        
        # 获取资源库ID（可选，null表示全局标签）
        library_id = data.get('library_id')
        
        # 计算路径
        parent_id = data.get('parent_id')
        if parent_id:
            parent_tag = Tag.query.get(parent_id)
            if not parent_tag:
                return jsonify({'success': False, 'message': '父标签不存在'}), 400
            # 避免循环引用
            if parent_tag.parent_id == int(parent_id) if parent_tag else False:
                return jsonify({'success': False, 'message': '不能设置自己的子标签为父标签'}), 400
            # 计算子标签路径
            parent_path = parent_tag.path if parent_tag.path != '/' else ''
            tag_path = f"{parent_path}/{name}"
        else:
            tag_path = f"/{name}"
        
        # 基于路径判断唯一性（标签路径全局唯一，跨资源库复用，避免重复创建）
        existing = Tag.query.filter_by(path=tag_path).first()
        if existing:
            return jsonify({'success': False, 'message': f'标签路径已存在: {tag_path}'}), 400
        
        tag = Tag(
            name=name,
            path=tag_path,
            category=data.get('category', '类型'),
            parent_id=parent_id,
            library_id=library_id
        )
        tag.set_qualifiers(qualifiers_raw)
        db.session.add(tag)
        db.session.commit()
        log.maintenance('INFO', f"创建标签: {name} (路径: {tag_path})")
        return jsonify({'success': True, 'tag': tag.to_dict()})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"创建标签失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@bp.route('/api/tags/add', methods=['POST'])
def add_tag():
    """创建新标签 - 旧路径兼容"""
    return create_tag()

@bp.route('/api/tags/<int:tag_id>', methods=['PUT'])
def update_tag(tag_id):
    """更新标签 - PUT方法"""
    return _do_update_tag(tag_id)

@bp.route('/api/tags/update/<int:tag_id>', methods=['POST'])
def update_tag_post(tag_id):
    """更新标签 - POST方法（兼容前端）"""
    return _do_update_tag(tag_id)

@bp.route('/api/tags/<int:tag_id>', methods=['DELETE'])
def delete_tag(tag_id):
    try:
        tag = Tag.query.get_or_404(tag_id)
        
        # 处理子标签：将子标签提升为顶级标签
        for child in tag.children:
            child.parent_id = None
        
        # 删除标签与视频的关联
        VideoTag.query.filter_by(tag_id=tag_id).delete()
        
        # 删除标签
        db.session.delete(tag)
        db.session.commit()
        log.maintenance('INFO', f"删除标签: {tag.name} (ID: {tag_id})")
        return jsonify({'success': True, 'message': '标签已删除'})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"删除标签失败: {tag_id}, {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


def _rebuild_tag_path(tag: Tag) -> str:
    """根据父级链重算标签路径，并同步所有后代标签路径。"""
    chain = []
    cur = tag
    seen = set()
    while cur is not None and cur.id not in seen:
        seen.add(cur.id)
        chain.append(cur)
        cur = Tag.query.get(cur.parent_id) if cur.parent_id else None
    chain.reverse()
    parts = [t.name for t in chain]
    base = '/' + '/'.join(parts)
    tag.path = base
    # 同步所有后代
    for child in tag.children:
        _rebuild_tag_path(child)
    return base


@bp.route('/api/tags/batch-delete', methods=['POST'])
def batch_delete_tags():
    """批量删除标签：子标签提升为顶级，关联一并移除。"""
    try:
        data = request.get_json()
        ids = data.get('ids', [])
        if not isinstance(ids, list) or not ids:
            return jsonify({'success': False, 'message': '未提供要删除的标签'}), 400
        deleted = 0
        for tid in ids:
            tag = Tag.query.get(tid)
            if not tag:
                continue
            for child in tag.children:
                child.parent_id = None
            VideoTag.query.filter_by(tag_id=tag.id).delete()
            db.session.delete(tag)
            deleted += 1
        db.session.commit()
        log.maintenance('INFO', f"批量删除标签: {deleted} 个")
        return jsonify({'success': True, 'deleted': deleted})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"批量删除标签失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/tags/batch-move', methods=['POST'])
def batch_move_tags():
    """批量移动标签到指定父级（parent_id 为 null 表示顶级）。"""
    try:
        data = request.get_json()
        ids = data.get('ids', [])
        parent_id = data.get('parent_id')
        if not isinstance(ids, list) or not ids:
            return jsonify({'success': False, 'message': '未提供要移动的标签'}), 400
        if parent_id:
            parent_tag = Tag.query.get(parent_id)
            if not parent_tag:
                return jsonify({'success': False, 'message': '父标签不存在'}), 400
        moved = 0
        for tid in ids:
            if tid == parent_id:
                continue
            tag = Tag.query.get(tid)
            if not tag:
                continue
            if parent_id:
                child_ids = tag.get_all_child_ids()
                if parent_id in child_ids:
                    continue
            tag.parent_id = parent_id
            _rebuild_tag_path(tag)
            moved += 1
        db.session.commit()
        log.maintenance('INFO', f"批量移动标签: {moved} 个 -> 父级 {parent_id}")
        return jsonify({'success': True, 'moved': moved})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"批量移动标签失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@bp.route('/api/tags/merge', methods=['POST'])
def merge_tags():
    """合并标签：将 source_ids 中的所有标签合并进 target_id，
    源标签与视频的关联转移到目标标签后删除源标签，子标签提升为顶级。"""
    try:
        data = request.get_json()
        source_ids = data.get('source_ids', [])
        target_id = data.get('target_id')
        if not isinstance(source_ids, list) or not source_ids or not target_id:
            return jsonify({'success': False, 'message': '参数不完整'}), 400
        target = Tag.query.get(target_id)
        if not target:
            return jsonify({'success': False, 'message': '目标标签不存在'}), 400
        if target_id in source_ids:
            return jsonify({'success': False, 'message': '目标标签不能是源标签之一'}), 400
        target_child_ids = set(target.get_all_child_ids())
        merged = 0
        for sid in source_ids:
            if sid == target_id:
                continue
            src = Tag.query.get(sid)
            if not src:
                continue
            # 不能把目标的祖先合并进来（避免产生环）
            if sid in target_child_ids:
                continue
            # 转移视频关联（避免重复关联同一视频）
            for vt in VideoTag.query.filter_by(tag_id=src.id).all():
                dup = VideoTag.query.filter_by(video_id=vt.video_id, tag_id=target.id).first()
                if not dup:
                    db.session.add(VideoTag(video_id=vt.video_id, tag_id=target.id))
            VideoTag.query.filter_by(tag_id=src.id).delete()
            # 子标签提升为顶级
            for child in src.children:
                child.parent_id = None
                _rebuild_tag_path(child)
            db.session.delete(src)
            merged += 1
        db.session.commit()
        log.maintenance('INFO', f"合并标签: {merged} 个 -> {target.name} (ID {target_id})")
        return jsonify({'success': True, 'merged': merged, 'target': target.to_dict()})
    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"合并标签失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
