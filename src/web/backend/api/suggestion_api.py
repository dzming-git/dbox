"""意见建议 / Issue 模块（参考 GitHub Issue 风格）。

原 src/web/api/suggestion_api.py 迁移而来，统一到 backend/api 体系：
- 鉴权改用 backend.access.resolve_identity（cookie + JWT Bearer 双通道）
- 数据存储从原 issues.json 单文件改为独立的反馈数据库
  （{runtime_dir}/databases/feedback.db，见 backend.feedback_db）

对外 API 契约（路径、字段、状态枚举、分页、评论）保持不变，前端无需改动。
Issue 唯一 id 格式：yyyymmdd + 4 位流水号。
权限：列表/详情公开；提交允许游客；关闭/重开/评论仅管理员。
"""
from datetime import datetime

from flask import Blueprint, request, jsonify

from core.models import UserRole
from backend.access import resolve_identity
from backend.feedback_db import (
    init_feedback_db, get_session, FeedbackIssue, FeedbackComment,
    issue_to_dict, STATUS_MAP, db_create_issue, db_append_comment,
)

suggestion_bp = Blueprint('suggestion_api', __name__)

# 状态（与前端契约一致）
STATUS_OPEN = 'open'                          # 开放
STATUS_IN_PROGRESS = 'in_progress'           # 处理中（自动助手正在处理）
STATUS_PENDING = 'pending'                    # 待验证（已修复，等待管理员验证）
STATUS_PENDING_VERIFICATION = 'pending_verification'  # 待验证（自动助手处理完成，语义同 pending）
STATUS_CLOSED = 'closed'                      # 已关闭

# 允许写入的状态白名单（status 为自由字符串，无需迁移）
ALLOWED_STATUSES = {
    STATUS_OPEN, STATUS_IN_PROGRESS,
    STATUS_PENDING, STATUS_PENDING_VERIFICATION, STATUS_CLOSED,
}

# 关闭原因
REASON_RESOLVED = 'resolved'      # 以解决
REASON_DISMISSED = 'dismissed'    # 不处理


def _now():
    return datetime.now().isoformat(timespec='seconds')


def make_title(content, max_len=40):
    lines = [l.strip() for l in (content or '').split('\n') if l.strip()]
    first = lines[0] if lines else (content or '').strip()
    first = first or '(无标题)'
    if len(first) > max_len:
        return first[:max_len].rstrip() + '…'
    return first


def migrate_if_needed():
    """确保反馈独立数据库已初始化并迁移旧数据（幂等）。"""
    init_feedback_db()


def _auth():
    """返回 (user_id, role, username)，未登录返回 (None, 0, None)。"""
    try:
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
                for _secret in (JWT_SECRET_KEY, 'dbox-jwt-secret-key-change-in-production-2024'):
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


def _strip_contact(issue_dict, admin):
    d = dict(issue_dict)
    if not admin:
        d.pop('contact', None)
    return d


@suggestion_bp.route('/api/suggestion', methods=['GET'])
def list_issues():
    migrate_if_needed()
    admin = _is_admin()

    status = request.args.get('status', 'all')
    ftype = request.args.get('type', 'all')
    keyword = (request.args.get('keyword') or '').strip().lower()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1
    try:
        page_size = max(1, min(100, int(request.args.get('page_size', 20))))
    except ValueError:
        page_size = 20

    with get_session() as session:
        issues = [issue_to_dict(i) for i in session.query(FeedbackIssue).all()]

    # 兼容前端：category 作为 type 透出
    for it in issues:
        it['type'] = it.get('category') or 'suggestion'

    filtered = issues
    if status in ALLOWED_STATUSES:
        # pending 与 pending_verification 语义相同（均为「待验证」），合并匹配，
        # 与下方的 pending_count 计数逻辑保持一致，避免筛选为空。
        if status == STATUS_PENDING:
            filtered = [i for i in filtered
                        if i.get('status') in (STATUS_PENDING, STATUS_PENDING_VERIFICATION)]
        else:
            filtered = [i for i in filtered if i.get('status') == status]
    if ftype in ('bug', 'suggestion', 'other'):
        filtered = [i for i in filtered if i.get('type', 'suggestion') == ftype]
    if keyword:
        filtered = [i for i in filtered
                    if keyword in (i.get('title', '') + i.get('content', '')).lower()]

    filtered.sort(key=lambda x: x.get('created_at', ''), reverse=True)

    total = len(filtered)
    start = (page - 1) * page_size
    page_items = filtered[start:start + page_size]

    def _with_type(it):
        d = _strip_contact(it, admin)
        d['type'] = it.get('type', 'suggestion')
        return d

    out = [_with_type(it) for it in page_items]
    open_count = sum(1 for i in issues if i.get('status') == STATUS_OPEN)
    in_progress_count = sum(1 for i in issues if i.get('status') == STATUS_IN_PROGRESS)
    # pending 与 pending_verification 语义相同（待验证），合并计数
    pending_count = sum(1 for i in issues
                        if i.get('status') in (STATUS_PENDING, STATUS_PENDING_VERIFICATION))
    closed_count = sum(1 for i in issues if i.get('status') == STATUS_CLOSED)

    return jsonify({
        'success': True,
        'issues': out,
        'total': total,
        'open_count': open_count,
        'in_progress_count': in_progress_count,
        'pending_count': pending_count,
        'closed_count': closed_count,
        'page': page,
        'page_size': page_size,
    })


@suggestion_bp.route('/api/suggestion', methods=['POST'])
def create_issue():
    migrate_if_needed()
    data = request.get_json(force=True, silent=True) or {}
    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()
    contact = (data.get('contact') or '').strip()
    ftype = data.get('type') or 'suggestion'
    if ftype not in ('bug', 'suggestion', 'other'):
        ftype = 'suggestion'

    if not title and content:
        title = make_title(content)
    if not title:
        title = '(无标题)'

    uid, role, username = _auth()
    if uid and username:
        author = username
        author_role = role
        author_id = uid
    else:
        author = '游客'
        author_role = int(UserRole.GUEST)
        author_id = None

    # 建单逻辑统一走 feedback_db.db_create_issue（AI 助手提单亦复用同一函数）
    new_id = db_create_issue(
        title=title, content=content, category=ftype,
        submitter=author, source='web', auto_classified=False,
    )
    # 兼容历史：把游客联系方式暂存进 classification 之外的 meta 不合适，
    # 这里保留 contact 仅在 admin 可见——通过 submitter 备注不够，故在评论区不展示。
    # 由于 DB 模型无 contact 列，将联系方式作为首条系统留言（仅管理员可见由 _strip_contact 控制）。
    if contact:
        db_append_comment(
            new_id, '系统', int(UserRole.ROOT), f'联系方式：{contact}',
        )

    with get_session() as session:
        issue = session.get(FeedbackIssue, new_id)
        # 必须在 session 关闭前序列化，否则访问 issue.comments 会因 detached 抛出 500
        out = issue_to_dict(issue) if issue else {'id': new_id}
        out['type'] = out.get('category') or 'suggestion'
        out['author'] = author
        out['author_id'] = author_id
        out['author_role'] = author_role
        out['contact'] = contact

    return jsonify({'success': True, 'id': new_id, 'issue': out})


@suggestion_bp.route('/api/suggestion/<issue_id>', methods=['GET'])
def get_issue(issue_id):
    migrate_if_needed()
    admin = _is_admin()
    with get_session() as session:
        issue = session.get(FeedbackIssue, issue_id)
        if not issue:
            return jsonify({'success': False, 'message': 'issue 不存在', 'code': 404}), 404
        out = issue_to_dict(issue)
    out['type'] = out.get('category') or 'suggestion'
    return jsonify({'success': True, 'issue': _strip_contact(out, admin)})




@suggestion_bp.route('/api/suggestion/<issue_id>', methods=['PUT'])
def update_issue(issue_id):
    if not _is_admin():
        return jsonify({'success': False, 'message': '需要管理员权限', 'code': 403}), 403

    data = request.get_json(force=True, silent=True) or {}
    with get_session() as session:
        issue = session.get(FeedbackIssue, issue_id)
        if not issue:
            return jsonify({'success': False, 'message': 'issue 不存在', 'code': 404}), 404

        if 'status' in data:
            status = data['status']
            if status not in ALLOWED_STATUSES:
                return jsonify({'success': False, 'message': '无效状态', 'code': 400}), 400
            issue.status = status
            if status == STATUS_CLOSED:
                reason = data.get('closed_reason')
                if reason not in (REASON_RESOLVED, REASON_DISMISSED, None):
                    reason = REASON_DISMISSED
                issue.classification = reason  # 复用字段记录关闭原因
            else:
                issue.classification = None
            issue.processed_at = datetime.now()

        if data.get('title') is not None and str(data['title']).strip():
            issue.title = str(data['title']).strip()
        if data.get('content') is not None:
            issue.content = str(data['content'])
        issue.updated_at = datetime.now()
        session.commit()
        out = issue_to_dict(issue)
    out['type'] = out.get('category') or 'suggestion'
    return jsonify({'success': True, 'issue': out})


@suggestion_bp.route('/api/suggestion/<issue_id>/comment', methods=['POST'])
def comment_issue(issue_id):
    if not _is_admin():
        return jsonify({'success': False, 'message': '需要管理员权限', 'code': 403}), 403

    data = request.get_json(force=True, silent=True) or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'success': False, 'message': '评论内容不能为空', 'code': 400}), 400

    uid, role, username = _auth()
    author = username or '管理员'

    with get_session() as session:
        issue = session.get(FeedbackIssue, issue_id)
        if not issue:
            return jsonify({'success': False, 'message': 'issue 不存在', 'code': 404}), 404
        issue.comments.append(FeedbackComment(
            author=author,
            author_role=role or int(UserRole.ADMIN),
            content=content,
            created_at=datetime.now(),
        ))
        issue.updated_at = datetime.now()
        session.commit()
        out = issue_to_dict(issue)
    out['type'] = out.get('category') or 'suggestion'
    return jsonify({'success': True, 'issue': out})


@suggestion_bp.route('/api/suggestion/<issue_id>/reply_reopen', methods=['POST'])
def reply_reopen_issue(issue_id):
    """回复并重新打开（原子操作）。

    一次性追加管理员回复并把状态置为 open（重新打开），单次提交只产生
    1 个 feedback.status_changed 事件，避免「先回复、再重开」两步操作各自
    触发事件、导致同一问题产生多个事件/任务。
    """
    if not _is_admin():
        return jsonify({'success': False, 'message': '需要管理员权限', 'code': 403}), 403

    data = request.get_json(force=True, silent=True) or {}
    content = (data.get('content') or '').strip()
    if not content:
        return jsonify({'success': False, 'message': '评论内容不能为空', 'code': 400}), 400

    uid, role, username = _auth()
    author = username or '管理员'

    with get_session() as session:
        issue = session.get(FeedbackIssue, issue_id)
        if not issue:
            return jsonify({'success': False, 'message': 'issue 不存在', 'code': 404}), 404
        issue.comments.append(FeedbackComment(
            author=author,
            author_role=role or int(UserRole.ADMIN),
            content=content,
            created_at=datetime.now(),
        ))
        # 重新打开：进入处理流水线（与重新打开按钮语义一致，仅一次状态变更）
        issue.status = STATUS_OPEN
        issue.classification = None
        issue.processed_at = datetime.now()
        issue.updated_at = datetime.now()
        session.commit()
        out = issue_to_dict(issue)
    out['type'] = out.get('category') or 'suggestion'
    return jsonify({'success': True, 'issue': out})


@suggestion_bp.route('/api/suggestion/<issue_id>/verify_close', methods=['POST'])
def verify_close_issue(issue_id):
    """验证完成并关闭（原子操作）。

    管理员验证反馈已处理完成时，一次性（可选追加回复 + ）将状态置为 closed、
    closed_reason=resolved（已解决），单次提交只产生 1 个 feedback.status_changed
    事件，避免「先回复、再关闭」两步操作各自触发事件。评论内容可选：仅当
    填写时才追加管理员回复。
    """
    if not _is_admin():
        return jsonify({'success': False, 'message': '需要管理员权限', 'code': 403}), 403

    data = request.get_json(force=True, silent=True) or {}
    content = (data.get('content') or '').strip()

    uid, role, username = _auth()
    author = username or '管理员'

    with get_session() as session:
        issue = session.get(FeedbackIssue, issue_id)
        if not issue:
            return jsonify({'success': False, 'message': 'issue 不存在', 'code': 404}), 404
        if content:
            issue.comments.append(FeedbackComment(
                author=author,
                author_role=role or int(UserRole.ADMIN),
                content=content,
                created_at=datetime.now(),
            ))
        # 验证完成：置为已关闭（已解决），仅一次状态变更
        issue.status = STATUS_CLOSED
        issue.classification = REASON_RESOLVED
        issue.processed_at = datetime.now()
        issue.updated_at = datetime.now()
        session.commit()
        out = issue_to_dict(issue)
    out['type'] = out.get('category') or 'suggestion'
    return jsonify({'success': True, 'issue': out})
