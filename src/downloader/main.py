#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资源下载器服务（独立进程）

将「外部脚本 / 下载器」从主 Web 服务彻底剥离为独立服务：

  - 下载器以独立进程运行在 8082 端口，即使它崩溃 / 卡死 / 被脚本拖垮，
    也绝不会影响主 Web 服务（8080）及其他服务。
  - 对外暴露 /api/scripts/* 接口，鉴权方式与主服务完全一致（JWT Bearer），
    密钥直接读取与主服务相同的 DPLAYER_JWT_SECRET 环境变量 / 默认密钥。
  - 复用主服务的脚本引擎（script_engine）、Cookie 保险库、任务入库逻辑，
    通过共享的 DATA_DIR / dplayer.db 与主服务协同：下载产出文件经 upsert 自动入库。

注意：本文件是独立服务的入口，故意放在 src/downloader/（而非 src/web/），
避免与主 Web 服务耦合。其依赖的脚本引擎等共享模块位于 src/web，
通过下方 sys.path 注入以复用，而非拷贝代码。
"""
import os
import sys

# ---- 路径准备 ----
# 本文件位于 <root>/src/downloader
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))         # <root>/src/downloader
_SRC_DIR = os.path.dirname(_THIS_DIR)                          # <root>/src
_ROOT_DIR = os.path.dirname(_SRC_DIR)                          # <root>
_WEB_DIR = os.path.join(_SRC_DIR, 'web')                       # <root>/src/web（共享模块所在）
_CONFIGS_DIR = os.path.join(_ROOT_DIR, 'configs')
_SERVICES_DIR = os.path.join(_CONFIGS_DIR, 'services')

# 注入依赖路径：src/web 提供 script_engine / core / backend / library_watcher 等共享模块；
# configs/services 提供启动守卫；root 作为兜底。
for _p in (_WEB_DIR, _CONFIGS_DIR, _SERVICES_DIR, _ROOT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# configs/services 已在 sys.path，可直接导入启动守卫
from launcher_guard import check_service_launch

# 启动守卫：生产环境要求经由 NSSM 启动；开发环境（DPLAYER_DEV_MODE=1）才允许直接运行
try:
    check_service_launch('DPlayer Resource Downloader', 'src/downloader/main.py')
except SystemExit:
    raise

from flask import Flask, jsonify
from flask_cors import CORS

from script_engine.routes import script_bp, init_script_engine, mgr
from core.models import db

_DEFAULT_SECRET = 'dplayer-jwt-secret-key-change-in-production-2024'

app = Flask(__name__)
CORS(app, supports_credentials=True)
app.register_blueprint(script_bp)  # 通用外部脚本 / 下载器接口（/api/scripts, /api/admin/scripts, /api/admin/cookies）

# ---- 与主服务一致的配置（确保共享 DB / 保险库 / 缩略图）----
_data_dir = os.environ.get('DPLAYER_DATA_DIR', os.path.join(_ROOT_DIR, 'data'))
app.config['DATA_DIR'] = _data_dir
app.config['SECRET_KEY'] = os.environ.get('DPLAYER_JWT_SECRET', _DEFAULT_SECRET)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(_data_dir, 'databases', 'dplayer.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['ENABLE_EXTERNAL_SCRIPTS'] = True

db.init_app(app)

# 初始化脚本引擎（脚本发现 / 任务执行器 / Cookie 保险库 / 任务持久化）
with app.app_context():
    init_script_engine(app)

    # 构造一个 library watcher 对象，仅用于任务完成后把产出文件 upsert 入库。
    # 不调用 .start()，避免与主服务的文件系统监听（watchdog / 轮询）重复。
    try:
        import library_watcher as lw
        from library_watcher import ResourceLibraryWatcher
        _watcher = ResourceLibraryWatcher(app, None, {}, None, app.logger)
        lw._watcher_instance = _watcher
        app.logger.info('[Downloader] 入库 watcher 已就绪（仅用于任务产出文件入库）')
    except Exception as e:
        app.logger.warning(f'[Downloader] 初始化入库 watcher 失败（下载文件将不会被自动入库）: {e}')


@app.route('/api/health')
def health():
    return jsonify({
        'success': True,
        'service': 'dplayer-downloader',
        'scripts': len(mgr.scripts),
    })


if __name__ == '__main__':
    port = int(os.environ.get('DOWNLOADER_PORT', 8082))
    app.run(host='0.0.0.0', port=port, threaded=True)
