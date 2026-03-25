"""
DPlayer Thumbnail Service - Windows Service

使用 waitress WSGI 服务器作为 Windows 服务运行
"""
import win32serviceutil
import win32service
import win32event
import sys
import os
from pathlib import Path
import json

# 添加项目根目录到 Python 路径
PROJECT_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_DIR))

from waitress import serve

# 导入 Flask 应用
from services.thumbnail_service import app as thumbnail_app

# 从配置文件读取端口
def load_config():
    config_path = PROJECT_DIR / 'config' / 'config.json'
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

config = load_config()
HOST = '0.0.0.0'
PORT = config.get('ports', {}).get('thumbnail', 5001)


class ThumbnailService(win32serviceutil.ServiceFramework):
    """Thumbnail Service Windows 服务"""

    _svc_name_ = "DPlayer-Thumbnail"
    _svc_display_name_ = "DPlayer Thumbnail Service"
    _svc_description_ = f"DPlayer Thumbnail Microservice, Port {PORT}"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)

        # 切换到项目目录
        os.chdir(str(PROJECT_DIR))

        # Waitress 不需要预先创建服务器对象
        self.server = None
        self.server_thread = None

    def SvcStop(self):
        """停止服务"""
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.hWaitStop)

        # 停止服务器
        if self.server:
            try:
                self.server.close()
            except:
                pass

        self.ReportServiceStatus(win32service.SERVICE_STOPPED)

    def SvcDoRun(self):
        """运行服务"""
        # 报告服务正在运行
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)

        # 使用 waitress 启动 Flask 应用
        import threading
        import time

        def run_server():
            self.server = serve(
                thumbnail_app,
                host=HOST,
                port=PORT,
                threads=4,
                url_scheme='http'
            )

        # 在独立线程中运行服务器
        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()

        # 等待停止信号
        win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)


if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(ThumbnailService)
