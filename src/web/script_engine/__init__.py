"""通用外部脚本接口引擎。

用户可在 extensions/scripts/<id>/ 下放置脚本包（manifest + 可执行文件），
系统自动发现、管理员启用后，任何管理员都可通过 API 触发运行。
脚本通过 stdin 接收 JSON 参数，通过 stdout 逐行输出 JSONL 进度/日志，
完成后调用 context.notify 接口通知 Dbox 入库新资源。
"""

from .manager import ScriptJobManager
from .routes import script_bp, init_script_engine, mgr

__all__ = ['ScriptJobManager', 'script_bp', 'init_script_engine', 'mgr']
