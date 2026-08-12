# -*- coding: utf-8 -*-
"""中立共享库（shared）。

只提供跨子系统复用的「能力」，不依赖任何业务模块（src/web、extensions_host）。
被主 Web 服务、扩展宿主、下载器共同引用，是三者之间唯一的共享代码边界。
"""
