"""缓存管理面板（Web 代理层，运行于主 Web 服务 dbox-web 进程）。

把缓存微服务 dbox-cached（com.dbox.cached）的总线方法暴露为管理员 HTTP 接口，
供管理后台 core-panels/cache.html 调用：

- GET  /api/admin/cache/namespaces  → 各托管分区统计 + 汇总
- POST /api/admin/cache/cap         body {namespace, bytes}    → 设置容量上限
- POST /api/admin/cache/clear       body {namespace}           → 清空（不传或 '*' 清空全部）
- POST /api/admin/cache/refresh                                → 重新扫描磁盘

鉴权由传入的 admin_required 统一处理；总线不可用时返回 503。
"""
import logging

from backend.runtime import runtime

logger = logging.getLogger('cache_admin')

_BUS_NAME = 'com.dbox.cached'
_BUS_IFACE = 'com.dbox.Cached'
_TIMEOUT_MS = 6000


def _call(method, params=None):
    """调用缓存微服务总线方法，返回 (result_dict, error_str)。"""
    bus = runtime.cached_bus
    if bus is None:
        return None, '缓存微服务未连接（cached_bus 不可用）'
    try:
        r = bus.call_method(_BUS_NAME, _BUS_IFACE, method, params or {}, timeout=_TIMEOUT_MS)
        return r, None
    except Exception as e:
        logger.warning('cache proxy %s failed: %s', method, e)
        return None, '调用缓存微服务失败: %s' % e


def create_blueprint(admin_required):
    from flask import Blueprint, jsonify, request

    bp = Blueprint('cache_admin_local', __name__, url_prefix='/api/admin/cache')

    @bp.route('/namespaces', methods=['GET'])
    @admin_required
    def namespaces():
        r, err = _call('GetNamespaces')
        if err:
            return jsonify({'success': False, 'message': err}), 503
        nss = (r or {}).get('namespaces', [])
        total_bytes = sum(x.get('bytes', 0) or 0 for x in nss)
        total_count = sum(x.get('count', 0) or 0 for x in nss)
        total_cap = sum(x.get('cap', 0) or 0 for x in nss)
        return jsonify({
            'success': True,
            'namespaces': nss,
            'totals': {'bytes': total_bytes, 'count': total_count, 'cap': total_cap},
        })

    @bp.route('/cap', methods=['POST'])
    @admin_required
    def set_cap():
        body = request.get_json(force=True, silent=True) or {}
        ns = body.get('namespace')
        bytes_ = body.get('bytes')
        if not ns or bytes_ is None:
            return jsonify({'success': False, 'message': 'namespace 与 bytes 必填'}), 400
        try:
            bytes_ = int(bytes_)
        except Exception:
            return jsonify({'success': False, 'message': 'bytes 必须为整数'}), 400
        r, err = _call('SetCap', {'namespace': ns, 'bytes': bytes_})
        if err:
            return jsonify({'success': False, 'message': err}), 503
        return jsonify(r or {'success': True})

    @bp.route('/clear', methods=['POST'])
    @admin_required
    def clear():
        body = request.get_json(force=True, silent=True) or {}
        ns = body.get('namespace') or '*'
        r, err = _call('Clear', {'namespace': ns})
        if err:
            return jsonify({'success': False, 'message': err}), 503
        return jsonify(r or {'success': True})

    @bp.route('/refresh', methods=['POST'])
    @admin_required
    def refresh():
        r, err = _call('Refresh')
        if err:
            return jsonify({'success': False, 'message': err}), 503
        return jsonify(r or {'success': True})

    return bp
