"""
建议反馈API接口
用户提交建议，管理员查看建议列表
"""
from flask import Blueprint, jsonify, request
from datetime import datetime
from pathlib import Path
import json
import uuid
from liblog import get_service_logger

log = get_service_logger('dplayer-web')

# 创建蓝图
suggestion_bp = Blueprint('suggestion', __name__, url_prefix='/api/suggestion')


def get_suggestions_file():
    """获取建议存储文件路径"""
    from api.system_api import get_runtime_dir
    runtime_dir = get_runtime_dir()
    suggestions_dir = Path(runtime_dir) / 'data'
    suggestions_dir.mkdir(parents=True, exist_ok=True)
    return suggestions_dir / 'suggestions.json'


def load_suggestions():
    """加载所有建议"""
    suggestions_file = get_suggestions_file()
    if suggestions_file.exists():
        try:
            with open(suggestions_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            log.error(f'加载建议失败: {e}')
    return []


def save_suggestions(suggestions):
    """保存建议列表"""
    suggestions_file = get_suggestions_file()
    try:
        with open(suggestions_file, 'w', encoding='utf-8') as f:
            json.dump(suggestions, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log.error(f'保存建议失败: {e}')
        return False


@suggestion_bp.route('', methods=['POST'])
def submit_suggestion():
    """
    提交建议
    请求体: { "content": "建议内容", "contact": "联系方式(可选)" }
    """
    data = request.get_json()

    if not data or not data.get('content'):
        return jsonify({'success': False, 'error': '建议内容不能为空'}), 400

    content = data.get('content', '').strip()
    contact = data.get('contact', '').strip()

    if len(content) < 5:
        return jsonify({'success': False, 'error': '建议内容太短，请详细描述'}), 400

    if len(content) > 2000:
        return jsonify({'success': False, 'error': '建议内容过长，请控制在2000字以内'}), 400

    # 获取用户信息（如果已登录）
    user_info = None
    try:
        from flask import session
        user_session = session.get('user_session')
        username = session.get('username')
        if username:
            user_info = username
    except Exception:
        pass

    suggestion = {
        'id': str(uuid.uuid4())[:8],
        'content': content,
        'contact': contact,
        'user': user_info,
        'created_at': datetime.now().isoformat(),
        'status': 'pending',  # pending, reviewed, replied
        'reply': None
    }

    suggestions = load_suggestions()
    suggestions.insert(0, suggestion)  # 新建议在前

    if save_suggestions(suggestions):
        log.info('suggestion', f'收到新建议 from {user_info or "游客"}: {content[:50]}...')
        return jsonify({
            'success': True,
            'message': '感谢您的建议！',
            'suggestion_id': suggestion['id']
        })
    else:
        return jsonify({'success': False, 'error': '保存失败，请重试'}), 500


@suggestion_bp.route('/list', methods=['GET'])
def list_suggestions():
    """
    获取建议列表（仅管理员）
    """
    try:
        from flask import session
        role = session.get('role', 0)
        if role > 1:  # 非管理员
            return jsonify({'success': False, 'error': '权限不足'}), 403
    except Exception:
        return jsonify({'success': False, 'error': '请先登录'}), 401

    suggestions = load_suggestions()

    # 返回脱敏后的数据
    result = []
    for s in suggestions:
        result.append({
            'id': s['id'],
            'content': s['content'],
            'contact': s['contact'] if s.get('contact') else '',
            'user': s.get('user') or '游客',
            'created_at': s['created_at'],
            'status': s.get('status', 'pending'),
            'reply': s.get('reply')
        })

    return jsonify({
        'success': True,
        'suggestions': result,
        'total': len(result)
    })


@suggestion_bp.route('/<suggestion_id>', methods=['PUT'])
def update_suggestion(suggestion_id):
    """
    更新建议状态/回复（仅管理员）
    """
    try:
        from flask import session
        role = session.get('role', 0)
        if role > 1:
            return jsonify({'success': False, 'error': '权限不足'}), 403
    except Exception:
        return jsonify({'success': False, 'error': '请先登录'}), 401

    data = request.get_json()
    suggestions = load_suggestions()

    for s in suggestions:
        if s['id'] == suggestion_id:
            if 'status' in data:
                s['status'] = data['status']
            if 'reply' in data:
                s['reply'] = data['reply']
            s['updated_at'] = datetime.now().isoformat()

            if save_suggestions(suggestions):
                return jsonify({'success': True})
            else:
                return jsonify({'success': False, 'error': '保存失败'}), 500

    return jsonify({'success': False, 'error': '建议不存在'}), 404