"""入库（拓展宿主侧代理）。

拓展宿主是独立进程，不直接操作主服务的数据库；实际入库逻辑驻留在主 Web
服务（backend/internal_ingest），本模块仅把调用转发给主服务的平台内部接口
/platform/ingest（经 platform_client），保持与主模块解耦。
"""
from platform_client import ingest_file as _platform_ingest


def ingest_file(library_id, path, app=None, kind=None, modes=('video',),
                collection_id=None, meta=None, user_id=None, hidden=False):
    """把文件/目录入库请求转发给主服务执行，返回主服务的入库结果 dict。"""
    return _platform_ingest(
        library_id, path, kind=kind, modes=modes,
        collection_id=collection_id, meta=meta, user_id=user_id, hidden=hidden,
    )
