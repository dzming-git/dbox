"""
意见建议 / Issue 模块（参考 GitHub Issue 风格）

- Issue 唯一 id 格式：yyyymmdd + 4 位流水号，例如 202607250004
- 数据存储于 {runtime_dir}/data/issues.json（JSON 文件，单文件，线程安全写入）
- 数据迁移：首次访问时若 issues.json 不存在但旧的 suggestions.json 存在，
  自动将旧数据迁移为新的 Issue 结构（保留原文件作为备份，幂等）
- 权限：列表/详情对所有人公开（参考 GitHub 公开 issue）；提交允许游客；
  关闭/重新打开/评论仅管理员（role >= UserRole.ADMIN）
"""
import os
import json
import threading
from datetime import datetime

from flask import Blueprint, request, jsonify

from core.models import UserRole
from api.system_api import get_runtime_dir

suggestion_bp = Blueprint('suggestion', __name__)

_lock = threading.Lock()

ISSUES_FILE = os.path.join(get_runtime_dir(), 'data', 'issues.json')
SUGGESTIONS_FILE = os.path.join(get_runtime_dir(), 'data', 'suggestions.json')

# 关闭原因
REASON_RESOLVED = 'resolved'      # 以解决
REASON_DISMISSED = 'dismissed'    # 不处理


def _now():
    return datetime.now().isoformat(timespec='seconds')


def load_issues():
    if not os.path.exists(ISSUES_FILE):
        return []
    try:
        with open(ISSUES_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_issues(issues):
    os.makedirs(os.path.dirname(ISSUES_FILE), exist_ok=True)
    tmp = ISSUES_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(issues, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ISSUES_FILE)


def make_title(content, max_len=40):
    lines = [l.strip() for l in (content or '').split('\n') if l.strip()]
    first = lines[0] if lines else (content or '').strip()
    first = first or '(无标题)'
    if len(first) > max_len:
        return first[:max_len].rstrip() + '…'
    return first


def generate_issue_id(date=None):
    """生成 yyyymmdd + 4 位流水号，按当天最大序号 +1"""
    date = date or datetime.now()
    date_str = date.strftime('%Y%m%d')
    max_seq = 0
    for it in load_issues():
        iid = it.get('id', '')
        if isinstance(iid, str) and iid.startswith(date_str) and len(iid) == 12:
            try:
                seq = int(iid[8:12])
                if seq > max_seq:
                    max_seq = seq
            except ValueError:
                pass
    return f"{date_str}{max_seq + 1:04d}"


def migrate_if_needed():
    """自动迁移旧 suggestions.json -> issues.json（幂等）"""
    if os.path.exists(ISSUES_FILE):
        return
    if not os.path.exists(SUGGESTIONS_FILE):
        return
    try:
        with open(SUGGESTIONS_FILE, 'r', encoding='utf-8') as f:
            suggestions = json.load(f)
    except Exception:
        return
    if not isinstance(suggestions, list):
        return

    counters = {}
    issues = []
    for s in suggestions:
        created = s.get('created_at')
        try:
            dt = datetime.fromisoformat(created) if created else None
        except Exception:
            dt = None
        date_str = dt.strftime('%Y%m%d') if dt else datetime.now().strftime('%Y%m%d')
        counters[date_str] = counters.get(date_str, 0) + 1
        iid = f"{date_str}{counters[date_str]:04d}"

        comments = []
        if s.get('reply'):
            comments.append({
                'author': '管理员',
                'author_role': int(UserRole.ADMIN),
                'content': s['reply'],
                'created_at': s.get('updated_at') or created or _now(),
            })

        user = s.get('user')
        author = user if user else '游客'
        author_role = int(UserRole.USER) if user else int(UserRole.GUEST)

        issues.append({
            'id': iid,
            'title': make_title(s.get('content', '')),
            'content': s.get('content', ''),
            'author': author,
            'author_id': None,
            'author_role': author_role,
            'contact': s.get('contact', ''),
            'status': 'open',
            'closed_reason': None,
            'comments': comments,
            'created_at': created or _now(),
            'updated_at': s.get('updated_at') or created or _now(),
            'closed_at': None,
        })
    save_issues(issues)


def _auth():
    """返回 (user_id, role, username)，未登录返回 (None, 0, None)"""
    try:
        from main import resolve_identity
        from backend.utils.jwt_authlib import SECRET_KEY as JWT_SECRET_KEY
        uid, role = resolve_identity()
        if not uid:
            return None, 0, None
        username = None
        # 优先从 JWT Bearer Token 的 payload 取用户名（token 鉴权路径）
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            try:
                from authlib.jose import jwt as _jwt
                for _secret in (JWT_SECRET_KEY, 'dplayer-jwt-secret-key-change-in-production-2024'):
                    try:
                        _p = _jwt.decode(auth_header[7:], _secret)
                        if _p.get('type') == 'access':
                            username = _p.get('username')
                            break
                    except Exception:
                        continue
            except Exception:
                pass
        # 回退到 session 用户（session 鉴权路径）
        if not username:
            try:
                from services.auth_service import AuthService
                u = AuthService.get_current_user()
                if u:
                    username = u.username
            except Exception:
                pass
        return uid, int(role or 0), username
    except Exception:
        return None, 0, None


def _is_admin():
    return _auth()[1] >= UserRole.ADMIN


def _strip_contact(issue, admin):
    d = dict(issue)
    if not admin:
        d.pop('contact', None)
    return d


@suggestion_bp.route('', methods=['GET'])
def list_issues():
    migrate_if_needed()
    issues = load_issues()
    admin = _is_admin()

    status = request.args.get('status', 'all')
    keyword = (request.args.get('keyword') or '').strip().lower()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1
    try:
        page_size = max(1, min(100, int(request.args.get('page_size', 20))))
    except ValueError:
        page_size = 20

    filtered = issues
    if status in ('open', 'closed'):
        filtered = [i for i in filtered if i.get('status') == status]
    if keyword:
        filtered = [i for i in filtered
                    if keyword in (i.get('title', '') + i.get('content', '')).lower()]

    filtered.sort(key=lambda x: x.get('created_at', ''), reverse=True)

    total = len(filtered)
    start = (page - 1) * page_size
    page_items = filtered[start:start + page_size]

    out = [_strip_contact(it, admin) for it in page_items]
    open_count = sum(1 for i in issues if i.get('status') == 'open')
    closed_count = sum(1 for i in issues if i.get('status') == 'closed')

    return jsonify({
        'success': True,
        'issues': out,
        'total': total,
        'open_count': open_count,
        'closed_count': closed_count,
        'page': page,
        'page_size': page_size,
    })


@suggestion_bp.route('', methods=['POST'])
def create_issue():
    migrate_if_needed()
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()
    contact = (data.get('contact') or '').strip()

    if not content:
        return jsonify({'success': False, 'message': '内容不能为空', 'code': 400}), 400
    if len(content) < 5:
        return jsonify({'success': False, 'message': '建议内容太短，请详细描述', 'code': 400}), 400
    if not title:
        title = make_title(content)

    uid, role, username = _auth()
    if uid and username:
        author = username
        author_role = role
        author_id = uid
    else:
        author = '游客'
        author_role = int(UserRole.GUEST)
        author_id = None

    issue = {
        'id': generate_issue_id(),
        'title': title,
        'content': content,
        'author': author,
        'author_id': author_id,
        'author_role': author_role,
        'contact': contact,
        'status': 'open',
        'closed_reason': None,
        'comments': [],
        'created_at': _now(),
        'updated_at': _now(),
        'closed_at': None,
    }
    with _lock:
        issues = load_issues()
        issues.append(issue)
        save_issues(issues)

    return jsonify({'success': True, 'id': issue['id'], 'issue': issue})


@suggestion_bp.route('/<issue_id>', methods=['GET'])
def get_issue(issue_id):
    migrate_if_needed()
    admin = _is_admin()
    it = next((i for i in load_issues() if i.get('id') == issue_id), None)
    if not it:
        return jsonify({'success': False, 'message': 'issue 不存在', 'code': 404}), 404
    return jsonify({'success': True, 'issue': _strip_contact(it, admin)})


@suggestion_bp.route('/<issue_id>', methods=['PUT'])
def update_issue(issue_id):
    if not _is_admin():
        return jsonify({'success': False, 'message': '需要管理员权限', 'code': 403}), 403

    data = request.get_json(force=True, silent=True) or {}
    with _lock:
        issues = load_issues()
        it = next((i for i in issues if i.get('id') == issue_id), None)
        if not it:
            return jsonify({'success': False, 'message': 'issue 不存在', 'code': 404}), 404

        if 'status' in data:
            status = data['status']
            if status not in ('open', 'closed'):
                return jsonify({'success': False, 'message': '无效状态', 'code': 400}), 400
            it['status'] = status
            if status == 'closed':
                reason = data.get('closed_reason')
                if reason not in (REASON_RESOLVED, REASON_DISMISSED, None):
                    reason = REASON_DISMISSED
                it['closed_reason'] = reason
                it['closed_at'] = _now()
            else:
                it['closed_reason'] = None
                it['closed_at'] = None

        if data.get('title') is not None and str(data['title']).strip():
            it['title'] = str(data['title']).strip()
        if data.get('content') is not None:
            it['content'] = str(data['content'])
        it['updated_at'] = _now()
        save_issues(issues)

    return jsonify({'success': True, 'issue': it})


@suggestion_bp.route('/<issue_id>/comment', methods=['POST'])
def comment_issue(issue_id):
    if not _is_admin():
        return jsonify({'success': False, 'message': '需要管理员权限', 'code': 403}), 403

    data = request.get_json(force=True, silent=True) or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'success': False, 'message': '评论内容不能为空', 'code': 400}), 400

    uid, role, username = _auth()
    author = username or '管理员'

    with _lock:
        issues = load_issues()
        it = next((i for i in issues if i.get('id') == issue_id), None)
        if not it:
            return jsonify({'success': False, 'message': 'issue 不存在', 'code': 404}), 404

        comment = {
            'author': author,
            'author_role': role or int(UserRole.ADMIN),
            'content': content,
            'created_at': _now(),
        }
        it.setdefault('comments', []).append(comment)
        it['updated_at'] = _now()
        save_issues(issues)

    return jsonify({'success': True, 'issue': it})
