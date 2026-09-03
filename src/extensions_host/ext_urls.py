"""扩展 API URL 的唯一事实来源。

框架所有插件后端蓝图挂载前缀、前端面板占位符 __EXT_API_PREFIX__ 的推导，
都来自本模块的 EXT_API_BASE + 插件 key。插件**不得**在 manifest / 代码中声明或
硬编码完整 URL（见 routes.py / plugin_host 契约）：平台若要变更扩展基础路径，
只改这里的 EXT_API_BASE 一处，全部插件前后端自动跟随。
"""

# 扩展 API 基础路径（唯一事实来源）。
EXT_API_BASE = '/api/ext'


def ext_api_prefix(key: str) -> str:
    """返回某插件的完整 API 前缀（含结尾斜杠），如 /api/ext/x/。"""
    return '%s/%s/' % (EXT_API_BASE, key)
