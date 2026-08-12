# -*- coding: utf-8 -*-
"""扩展宿主（extensions_host）。

独立的扩展管理服务进程，承载脚本引擎、UI 扩展面板、AI 助手等扩展能力。
完全不依赖主 Web 服务的业务模块（src/web），只通过 shared 中立库与
主模块的 IPlatformAPI 契约接口通信。

进程边界：
- 主 Web 服务   :8080  （领域能力 + IPlatformAPI 服务提供方）
- 扩展宿主       :8093  （本包）
- 下载器         :8092  （独立，仅处理重型下载脚本）
"""
