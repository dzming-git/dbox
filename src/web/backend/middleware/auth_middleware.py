# 全局路由鉴权中间件
# 在 Flask 应用的 before_request 钩子中统一校验 JWT，
# 命中白名单的路由直接放行，其余 /api/* 路由需要有效的 Bearer Token。

from flask import request, jsonify, g
from liblog import get_module_logger
log = get_module_logger()

# ──────────────────────────────────────────────
# 白名单：匹配这些前缀/路径的请求直接放行，不需要鉴权
# ──────────────────────────────────────────────
#
# 规则说明：
#   - 字符串条目：request.path 必须以该字符串 **开头** 才放行
#   - 可根据需要扩展（如健康检查、静态资源等）
#
AUTH_WHITELIST = [
    # ── 登录 / 注册 / Token 刷新 / 登出（v2 JWT）──
    '/api/v2/auth/login',
    '/api/v2/auth/register',
    '/api/v2/auth/refresh',
    '/api/v2/auth/logout',

    # ── 登录 / 注册 / 登出（v1 Session，兼容旧前端）──
    '/api/auth/login',
    '/api/auth/register',
    '/api/auth/logout',
    '/api/auth/me',           # 获取当前用户信息（未登录时返回 guest，不强制）

    # ── 健康检查 ──
    '/health',
    '/api/health',
    '/api/status',
]

# 需要鉴权的路径前缀（仅拦截这些前缀，其余路由不干预）
AUTH_REQUIRED_PREFIXES = [
    '/api/',
]


def _is_whitelisted(path: str) -> bool:
    """判断请求路径是否在白名单中"""
    for pattern in AUTH_WHITELIST:
        if path == pattern or path.startswith(pattern + '/') or path.startswith(pattern + '?'):
            return True
        # 精确匹配（处理末尾不带斜杠的情况）
        if path == pattern.rstrip('/'):
            return True
    return False


def _needs_auth(path: str) -> bool:
    """判断请求路径是否需要鉴权"""
    for prefix in AUTH_REQUIRED_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def setup_auth_middleware(app):
    """
    注册全局鉴权 before_request 钩子。

    调用方式（在 app.py 中）：
        from backend.middleware.auth_middleware import setup_auth_middleware
        setup_auth_middleware(app)
    """

    @app.before_request
    def check_auth():
        """全局请求鉴权"""
        path = request.path

        # 1. 不需要鉴权的路径前缀 → 直接放行
        if not _needs_auth(path):
            return None

        # 2. 白名单 → 直接放行
        if _is_whitelisted(path):
            return None

        # 3. OPTIONS 预检请求 → 直接放行（CORS preflight）
        if request.method == 'OPTIONS':
            return None

        # 4. 从请求头提取 Bearer Token
        auth_header = request.headers.get('Authorization', '')
        if not auth_header or not auth_header.startswith('Bearer '):
            log.debug('WARN', f"[Auth] 未携带 Token，拒绝访问: {path}")
            return jsonify({
                'success': False,
                'data': None,
                'message': '未授权，请先登录',
                'code': 401
            }), 401

        token = auth_header[7:]  # 去掉 'Bearer ' 前缀

        # 5. 验证 Token
        from backend.utils.jwt_authlib import verify_token
        payload = verify_token(token)

        if not payload:
            log.debug('WARN', f"[Auth] Token 无效或已过期，拒绝访问: {path}")
            return jsonify({
                'success': False,
                'data': None,
                'message': 'Token 无效或已过期，请重新登录',
                'code': 401
            }), 401

        if payload.get('type') != 'access':
            log.debug('WARN', f"[Auth] Token 类型错误: {payload.get('type')}，路径: {path}")
            return jsonify({
                'success': False,
                'data': None,
                'message': 'Token 类型错误',
                'code': 401
            }), 401

        # 6. 将用户信息注入 g，后续路由处理函数可直接使用
        g.user_id = payload.get('user_id')
        g.user_role = payload.get('role')
        g.username = payload.get('username')

        log.debug('DEBUG', f"[Auth] 鉴权通过: user={g.username}, path={path}")
        return None  # 继续处理请求

    return app
