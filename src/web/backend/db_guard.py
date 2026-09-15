# -*- coding: utf-8 -*-
"""长连接场景下的数据库连接归还。

为什么需要它：
鉴权装饰器（auth_required / admin_required）与 resolve_identity() 里都会
`User.query.get(...)`，这会从 SQLAlchemy 连接池**借出一个连接**。普通请求在
结束后由 Flask-SQLAlchemy 的 teardown 归还；但 **SSE / 流式响应不结束**，
teardown 就永远不执行 —— 于是每条长连接都永久占住一个连接。

连接池默认 size=5 + overflow=10（共 15），被占满之后，所有需要查库的请求
都会在 checkout 时排队 30 秒然后抛 TimeoutError，表现为：
接口全部超时/500、首页「无数据」、整个站点像瘫痪一样。

因此：**凡是返回流式响应的路由，必须在 return 之前调用本函数**。
调用之后不要再触碰 SQLAlchemy（改用直连 sqlite 或纯内存数据）。
"""


def release_db():
    """归还当前上下文借用的数据库连接；失败静默（不影响业务）。"""
    try:
        from core.models import db
        db.session.remove()
    except Exception:
        pass
