"""系统资源监控面板（本地版，运行于主 Web 服务 dbox-web 进程）。

逻辑在 backend.system_monitor_core，本文件只承载 Flask 蓝图，复用核心逻辑。
系统资源监控是平台系统功能，不依赖被管理的 dbox-extensions 进程。
"""
from backend.access import admin_required
from backend.system_monitor_core import create_blueprint

bp = create_blueprint(admin_required)
