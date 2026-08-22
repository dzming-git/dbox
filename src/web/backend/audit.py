# -*- coding: utf-8 -*-
"""
User-aware audit logging.

All log content emitted here is in English (except externally-determined
values such as filenames, titles or raw exception messages that originate
outside this module).

Operation-log content (the `content` segment written to operation.log)
uses a uniform format:

    action=... | user=... | result=... | target=... | detail=...

This module embeds the "actor" into the content segment; parse_log_line
(located in main.py) extracts the independent `user` field from it again.
"""

from flask import request, g
from liblog import get_service_logger

log = get_service_logger('dbox-web')

# Role id -> English role name (for log display only). 数值越小权限越高：0=ROOT,1=ADMIN,2=USER,3=GUEST
_ROLE_NAMES = {0: 'super_admin', 1: 'admin', 2: 'user', 3: 'guest'}

# Endpoints that should not be recorded by the automatic after_request hook
_AUTO_AUDIT_EXCLUDE_PREFIXES = (
    '/api/videos/stream',
    '/api/videos/play',
    '/static/',
    '/thumbnail/',
    '/api/v2/auth/refresh',
)
_AUTO_AUDIT_EXCLUDE_SUFFIXES = ('/view',)


def get_client_ip():
    """Best-effort client IP extraction (English output only)."""
    if request is None:
        return 'unknown'
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def _current_identity():
    """
    Return (user_id, username, role) for the current request.
    Priority: explicit login (g.current_user) > current_user global > anonymous.
    """
    cu = getattr(g, 'current_user', None)
    if cu:
        return cu.get('user_id'), cu.get('username') or '', cu.get('role', 3)
    cug = getattr(g, 'current_user', None)
    if cug:
        return cug.get('user_id'), cug.get('username') or '', cug.get('role', 3)
    return None, '', 3


def _format_actor(user_id, username, role):
    """Build a language-neutral actor description."""
    if user_id is None:
        return 'anonymous'
    name = username or f'id={user_id}'
    role_name = _ROLE_NAMES.get(role, str(role)) if role is not None else ''
    if role_name:
        return f'{name}(id={user_id},role={role_name})'
    return f'{name}(id={user_id})'


def log_operation(action, target='', detail='', success=True, user=None, ip=None):
    """
    Record an audited user operation (all text in English).

    :param action: operation name, e.g. 'user login'
    :param target: affected object, e.g. 'root' or 'library=3'
    :param detail: extra context (keep externally-determined values as-is)
    :param success: whether the operation succeeded
    :param user: optional explicit {'user_id','username','role'} override
    :param ip: optional client IP override
    """
    if ip is None:
        ip = get_client_ip()

    if user is not None:
        uid = user.get('user_id')
        uname = user.get('username') or ''
        role = user.get('role', 3)
    else:
        uid, uname, role = _current_identity()

    actor = _format_actor(uid, uname, role)
    result = 'success' if success else 'failed'

    parts = [
        f'action={action}',
        f'user={actor}',
        f'result={result}',
    ]
    if target:
        parts.append(f'target={target}')
    if detail:
        parts.append(f'detail={detail}')

    content = ' | '.join(parts)

    try:
        log.operation(content, source_ip=ip)
    except TypeError:
        # Compatible with older liblog whose operation() does not accept source_ip
        log.operation(content)
    except Exception:
        pass


def auto_audit_hook(response):
    """
    after_request hook: automatically record audited API calls.
    Skips GET/HEAD/OPTIONS and excluded endpoints; also skips when a manual
    log_operation already ran for this request (g._audited flag).
    """
    try:
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return response
        path = request.path or ''
        if any(path.startswith(p) for p in _AUTO_AUDIT_EXCLUDE_PREFIXES):
            return response
        if any(path.endswith(s) for s in _AUTO_AUDIT_EXCLUDE_SUFFIXES):
            return response
        if getattr(g, '_audited', False):
            return response

        uid, uname, role = _current_identity()
        actor = _format_actor(uid, uname, role)

        method = request.method
        status = response.status_code if response else 0
        ip = get_client_ip()

        content = (f'action=API call | method={method} | path={path} | '
                   f'user={actor} | status={status}')
        try:
            log.operation(content, source_ip=ip)
        except TypeError:
            log.operation(content)
    except Exception:
        pass
    return response
