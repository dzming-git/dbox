# 错误处理中间件
from flask import jsonify
import traceback
from liblog import get_module_logger
log = get_module_logger()

def setup_error_handlers(app):
    """配置错误处理"""
    
    @app.errorhandler(400)
    def bad_request(error):
        log.debug('WARN', f"400 Bad Request: {error}")
        return jsonify({
            'success': False,
            'data': None,
            'message': str(error) if str(error) else '请求参数错误',
            'code': 400
        }), 400
    
    @app.errorhandler(401)
    def unauthorized(error):
        log.debug('WARN', f"401 Unauthorized: {error}")
        return jsonify({
            'success': False,
            'data': None,
            'message': '未授权，请先登录',
            'code': 401
        }), 401
    
    @app.errorhandler(403)
    def forbidden(error):
        log.debug('WARN', f"403 Forbidden: {error}")
        return jsonify({
            'success': False,
            'data': None,
            'message': '禁止访问，权限不足',
            'code': 403
        }), 403
    
    @app.errorhandler(404)
    def not_found(error):
        log.debug('WARN', f"404 Not Found: {error}")
        return jsonify({
            'success': False,
            'data': None,
            'message': '资源不存在',
            'code': 404
        }), 404
    
    @app.errorhandler(405)
    def method_not_allowed(error):
        log.debug('WARN', f"405 Method Not Allowed: {error}")
        return jsonify({
            'success': False,
            'data': None,
            'message': '请求方法不允许',
            'code': 405
        }), 405
    
    @app.errorhandler(500)
    def internal_error(error):
        log.debug('ERROR', f"500 Internal Server Error: {error}")
        log.debug('ERROR', traceback.format_exc())
        return jsonify({
            'success': False,
            'data': None,
            'message': '服务器内部错误',
            'code': 500
        }), 500
    
    return app
