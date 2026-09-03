"""扩展 API URL 的唯一事实来源。

框架所有插件后端蓝图挂载前缀、前端面板占位符 __EXT_API_PREFIX__ 的推导，
都来自本模块的 EXT_API_BASE + 插件 key。插件**不得**在 manifest / 代码中声明或
硬编码完整 URL（见 routes.py / plugin_host 契约）：平台若要变更扩展基础路径，
只改这里的 EXT_API_BASE 一处，全部插件前后端自动跟随。

两种形态（同源推导）：
- ext_api_prefix(key)：带结尾斜杠，如 /api/ext/x/，注入前端面板占位符
  __EXT_API_PREFIX__（前端再 .replace(/\/$/, '') 去掉斜杠后拼 '/xxx'）。
- ext_api_path(key)：不带结尾斜杠，如 /api/ext/x，供后端蓝图注册（Flask 蓝图
  url_prefix 末尾不能带斜杠，否则与路由拼接出双斜杠导致 404）。
"""

# 扩展 API 基础路径（唯一事实来源）。
EXT_API_BASE = '/api/ext'


def ext_api_prefix(key: str) -> str:
    """带结尾斜杠，供前端面板占位符 __EXT_API_PREFIX__ 注入。"""
    return '%s/%s/' % (EXT_API_BASE, key)


def ext_api_path(key: str) -> str:
    """不带结尾斜杠，供后端蓝图注册（避免 url_prefix 尾斜杠与路由拼出双斜杠）。"""
    return '%s/%s' % (EXT_API_BASE, key)
