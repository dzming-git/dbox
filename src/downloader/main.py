#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资源下载器服务（独立进程）

将「外部脚本 / 下载器」从主 Web 服务彻底剥离为独立服务：

  - 下载器以独立进程运行在 8092 端口，即使它崩溃 / 卡死 / 被脚本拖垮，
    也绝不会影响主 Web 服务（8080）及其他服务。
  - 复用「拓展管理宿主」的同一份引擎代码（src/extensions_host）：本服务与
    extensions_host（8093）共享 script_engine / 凭证保险库 / 任务入库逻辑，
    但作为独立进程提供故障隔离域。前端统一经主服务网关（8080）访问 8093 的
    脚本接口，8092 作为下载专用的隔离实例存在。
  - 脚本回调（notify/input）由脚本进程打到主服务网关（8080），再由网关转发到
    实际执行该任务的一方，任务状态自洽。

注意：本文件是独立服务的入口，故意放在 src/downloader/（而非 src/web/），
仅负责以 8092 端口启动 extensions_host 的同一份引擎，不拷贝任何业务逻辑。
"""
import os
import sys

# ---- 路径准备 ----
# 本文件位于 <root>/src/downloader
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))         # <root>/src/downloader
_SRC_DIR = os.path.dirname(_THIS_DIR)                          # <root>/src
_ROOT_DIR = os.path.dirname(_SRC_DIR)                         # <root>
_CONFIGS_DIR = os.path.join(_ROOT_DIR, 'configs')
_SERVICES_DIR = os.path.join(_CONFIGS_DIR, 'services')

# 注入依赖路径：src/（提供 extensions_host / shared 等共享模块）；
# configs/services 提供启动守卫；root 作为兜底。
for _p in (_SRC_DIR, _CONFIGS_DIR, _SERVICES_DIR, _ROOT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# configs/services 已在 sys.path，可直接导入启动守卫
from launcher_guard import check_service_launch

# 解析用户数据区（与 web 主服务保持一致：环境变量 > 平台系统数据区）
import backend.paths as _paths  # noqa: E402
_paths._ensure_user_dirs()

# 启动守卫：生产环境要求经由 NSSM 启动；开发环境（DBOX_DEV_MODE=1）才允许直接运行
try:
    check_service_launch('Dbox Resource Downloader', 'src/downloader/main.py')
except SystemExit:
    raise

# 复用拓展管理宿主的同一份引擎（独立崩溃域，代码单份）。
from extensions_host.app import create_app

app = create_app()


@app.route('/api/health')
def health():
    return jsonify({
        'success': True,
        'service': 'dbox-downloader',
        'note': '复用 extensions_host 引擎，前端经 8080 网关访问 8093',
    })


if __name__ == '__main__':
    port = int(os.environ.get('DOWNLOADER_PORT', 8092))
    # 关闭 werkzeug reloader：与 Flask reloader / zmq 不兼容，且避免旧实例抢端口。
    app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)
