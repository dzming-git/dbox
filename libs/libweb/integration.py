# -*- coding: utf-8 -*-
"""
NodeManager Flask集成示例

这个文件展示如何将NodeManager集成到Flask应用。
"""

from flask import Flask, jsonify
from . import NodeManager, FlaskAdapter, register_all_routes


def create_app():
    """
    创建集成了NodeManager的Flask应用

    Returns:
        Flask应用实例
    """
    app = Flask(__name__)

    # 创建NodeManager并注册所有路由
    node_manager = NodeManager()
    register_all_routes(node_manager)

    # 创建Flask适配器并注册到Flask
    adapter = FlaskAdapter(node_manager)
    adapter.register_to_flask(app)

    return app


if __name__ == '__main__':
    # 示例运行
    app = create_app()
    print("Starting Flask app with NodeManager...")
    print("Routes registered:", len(app.url_map._rules))
    app.run(host='0.0.0.0', port=5000, debug=True)
