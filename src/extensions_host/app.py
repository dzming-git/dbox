"""拓展管理宿主应用工厂（独立进程，默认端口 8093）。

承载「拓展管理」全部能力：外部脚本执行引擎、脚本管理、UI 扩展面板、AI 助手对话、
凭证保险库。与主 Web 服务（8080）完全解耦——本进程不直接 import 任何 src/web
业务代码，仅通过 platform_client 以 HTTP 调用主服务暴露的内部契约接口
（/internal/*）完成业务副作用（入库 / 解析资源 / 生成帖子等）。

下载器（8092）与主 Web 网关也会复用本工厂，从而获得独立的崩溃域而共享同一份引擎代码。
"""
import os
import sys

from flask import Flask, jsonify

# 保证本包与共享库可被 import
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))            # src/extensions_host
_SRC_DIR = os.path.dirname(_THIS_DIR)                             # src/
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from routes import script_bp, init_script_engine


def create_app():
    app = Flask('extensions_host')

    @app.before_request
    def _no_cache():
        # 本宿主主要服务 admin 面板与脚本接口，统一禁用缓存避免旧面板/脚本被命中
        pass

    @app.errorhandler(404)
    def _not_found(e):
        return jsonify({'success': False, 'message': 'not found'}), 404

    @app.errorhandler(500)
    def _server_error(e):
        # 业务处理中的 500 必须如实上报，不得被装饰器吞成 401
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': 'internal error: %s' % e}), 500

    app.register_blueprint(script_bp)
    init_script_engine(app)
    return app


def _data_dir():
    env = os.environ.get('DBOX_DATA_DIR')
    if env:
        return env
    pkg_dir = os.path.dirname(os.path.abspath(__file__))           # src/extensions_host
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(pkg_dir)))
    return os.path.join(project_root, 'data')


def main():
    port = int(os.environ.get('EXTENSIONS_HOST_PORT', '8093'))
    host = os.environ.get('EXTENSIONS_HOST_HOST', '0.0.0.0')
    app = create_app()
    # 关闭 werkzeug reloader：避免 fork worker 使用旧 .pyc 导致代码修改不刷新，
    # 也避免同一端口出现多 main 实例抢端口（旧实例未退出时新代码不生效）。
    app.run(host=host, port=port, threaded=True, use_reloader=False)


if __name__ == '__main__':
    main()
