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
