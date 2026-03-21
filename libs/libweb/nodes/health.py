# -*- coding: utf-8 -*-
"""
HealthNode - 健康检查节点

提供简单的健康检查功能，返回服务状态。
"""

from ..core import Node, TaskContext


class HealthNode(Node):
    """健康检查Node示例"""

    def __init__(self, url_template: str = '/api/health'):
        super().__init__(url_template)

    async def do_get(self, context: TaskContext):
        """处理GET健康检查请求"""
        context.set_response(200, body={
            'status': 'ok',
            'message': 'Service is healthy'
        })
