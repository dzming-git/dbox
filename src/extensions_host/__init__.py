# -*- coding: utf-8 -*-
"""拓展管理宿主（extensions_host）。

独立进程（默认 8093）承载「拓展管理」全部能力：外部脚本执行引擎、脚本管理、
UI 扩展面板渲染、AI 对话助手、凭证保险库。与主 Web 服务（8080）完全解耦——
本模块不直接 import 任何 src/web 业务代码，仅通过 platform_client 以 HTTP
调用主服务暴露的内部契约接口（/internal/*）完成业务副作用（入库 / 解析资源 /
生成帖子等）。

代码单份：下载器（8092）与主 Web 网关也复用本包的应用工厂，从而获得独立的崩溃域。
"""
import os
import sys

# 保证本包与共享库可被 import（extensions_host / shared 均在 src/ 下）
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))           # src/extensions_host
_SRC_DIR = os.path.dirname(_THIS_DIR)                            # src/
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

__all__ = ['create_app']
