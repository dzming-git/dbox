"""服务总线客户端初始化。

从 main.py 收敛而来：集中创建各 BusClient 并注入 backend.runtime。
main.py 只需调用 init_service_buses() 即可完成总线接线，保持组合根（composition root）轻量。

总线连接失败时所有客户端置为 None，runtime 注入容忍 None，不影响主服务其余功能。
"""
import os
import sys

from backend.runtime import runtime
from liblog import get_service_logger

log = get_service_logger('dbox-web')


def _make_bus(name, src_dir):
    """创建单个 BusClient（连接 thumbnaild / servicemgr / historyd / collectiond / searchd / resourced）。

    注意：BusClient 在 __init__ 内部已调用 BusEndpoint.start_listening() 启动
    后台接收线程，call_method 才能收到 METHOD_REPLY/ERROR 回复，无需外部额外调用。
    """
    sys.path.insert(0, os.path.join(src_dir, 'servicebus'))
    from servicebus import BusClient
    return BusClient(
        name,
        host='127.0.0.1',
        rpc_port=15555,
        pub_port=15556,
    )


def init_service_buses(src_dir):
    """创建全部总线客户端并注入 runtime。

    Args:
        src_dir: src/ 目录（用于定位 servicebus 模块）
    Returns:
        dict: 各总线客户端（失败时对应值为 None）
    """
    buses = {
        'thumbnail_bus': None,
        'svc_mgr_bus': None,
        'history_bus': None,
        'collection_bus': None,
        'search_bus': None,
        'resource_bus': None,
    }
    try:
        buses['thumbnail_bus'] = _make_bus('web-client', src_dir)
        buses['svc_mgr_bus'] = _make_bus('web-svc-mgr', src_dir)
        buses['history_bus'] = _make_bus('web-history', src_dir)
        buses['collection_bus'] = _make_bus('web-collection', src_dir)
        buses['search_bus'] = _make_bus('web-search', src_dir)
        buses['resource_bus'] = _make_bus('web-resource', src_dir)
    except Exception as e:
        log.maintenance('WARN', f'总线客户端初始化失败: {e}')

    runtime.init(
        thumbnail_bus=buses['thumbnail_bus'],
        resource_bus=buses['resource_bus'],
        svc_mgr_bus=buses['svc_mgr_bus'],
        history_bus=buses['history_bus'],
        collection_bus=buses['collection_bus'],
        search_bus=buses['search_bus'],
    )
    return buses
