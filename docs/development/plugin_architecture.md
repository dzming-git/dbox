# 纯插件架构规范（Pure Plugin Architecture）

> 本文档定义 DBox 拓展脚本从「寄生式脚本」升级为「纯插件」的架构契约。
> 目标：一个插件 = 一个文件夹 = 一个压缩包，解压即用、删除即卸载，对框架零入侵。
> 新增任何插件均以此文档为唯一规范，无需改动框架业务代码。

---

## 1. 设计原则

| 原则 | 说明 |
|------|------|
| **自包含** | 插件逻辑、路由、前端、配置全部在自身文件夹内，不依赖框架内部模块 |
| **零入侵** | 删除插件文件夹，框架自动跳过，**不报错、不残留、不崩溃** |
| **契约通信** | 插件只通过框架注入的 `host` 宿主对象与框架交互，禁止 `import` 框架业务代码 |
| **独立命名空间** | 插件路由统一挂载在 `/api/ext/<plugin_id>/*`，互不冲突、可单独卸载 |
| **声明式** | 框架只需读取 `manifest.json`，不感知任何插件业务逻辑 |

---

## 2. 目录结构（压缩包内部）

```
<plugin_id>/                       ← 插件根目录（= 压缩包解压目标）
├── manifest.json                  ← 唯一入口：元信息 + 能力声明
├── backend/                       ← 插件后端（可选，脚本型插件可无）
│   ├── server.py                  ← 导出 create_blueprint(host) 工厂
│   ├── engine.py                  ← 业务逻辑（原 ai_chat.py 等）
│   ├── workflow_engine.py         ← 插件私有依赖（不共用框架模块）
│   └── db.py                      ← 自带 SQLite 封装
├── ui/                            ← 前端（可选）
│   ├── panel.html                 ← iframe 入口
│   └── assets/                    ← css/js 静态资源
├── workflows/                     ← 配置驱动的步骤定义（可选）
│   └── *.yaml
└── requirements.txt               ← 插件私有依赖（可选）
```

**关键约束**：`backend/` 内的模块**只 import 标准库、第三方库、以及自身目录**，
**严禁** `import extensions_host`、`import shared`、`import web`、`import manager` 等框架内部包。
需要框架能力时一律通过 `host` 对象获取（见 §4）。

---

## 3. manifest.json 规范

```json
{
  "id": "ai_chat",
  "name": "AI 助手对话",
  "version": "1.0.0",
  "description": "右下角悬浮球，与 AI 对话",
  "enabled": true,
  "api_version": 1,

  "ui": {
    "mount": "floating",          // floating | tab | sidebar | none
    "title": "AI 助手",
    "icon": "💬",
    "entry": "ui/panel.html",     // 相对插件根目录
    "sandbox": "allow-scripts allow-same-origin"
  },

  "backend": {                     // 省略则表示纯前端/脚本型插件
    "module": "backend.server",   // 框架动态 import 的模块路径
    "factory": "create_blueprint",// 该模块导出的工厂函数名
    "url_prefix": "/api/ext/ai_chat",
    "needs": ["codebuddy_token"]  // 声明需要的宿主能力（见 §4）
  }
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | ✅ | 全局唯一，作为路由前缀与数据目录名 |
| `name` / `description` | ✅ | 展示用 |
| `version` / `api_version` | ✅ | 插件契约版本，框架据此做兼容校验 |
| `ui.mount` | ❌ | 前端挂载形态；`none` 时不加载 UI |
| `backend.module` | ❌ | 有后端逻辑时必填 |
| `backend.factory` | ❌ | 默认 `create_blueprint` |
| `backend.url_prefix` | ❌ | 默认 `/api/ext/<id>` |
| `backend.needs` | ❌ | 能力声明清单，缺失则框架启动告警 |

---

## 4. 宿主对象（host）API 契约

框架在加载插件后端时，构造一个 `host` 对象注入工厂函数。插件**只依赖以下稳定接口**：

```python
def create_blueprint(host):
    bp = Blueprint('ext_ai_chat', __name__,
                   url_prefix=host.url_prefix)

    @bp.route('/chat', methods=['POST'])
    @host.login_required
    def chat():
        # 1) 数据目录（插件私有，删插件即清空）
        db_path = os.path.join(host.data_dir, 'ai_chat.db')

        # 2) 凭证读取（替代直接 import credential_vault）
        token = host.vault.get('codebuddy_token')

        # 3) 统一任务表注册（替代直接 import unified_tasks）
        host.tasks.create(kind='ai_chat', title='...', owner_id=host.user_id)

        # 4) 调用外部服务（替代 import platform_client）
        host.http.post('http://localhost:8080/internal/feedback', json={})

        # 5) 日志
        host.logger.info('ai_chat enqueue %s', task_id)

        # 6) 插件自维护状态（框架不感知）
        host.app_state['mgr'] = AIChatManager()
        return jsonify({'success': True})
    return bp
```

### host 成员清单

| 成员 | 类型 | 说明 |
|------|------|------|
| `host.data_dir` | str | 插件专属数据目录（自动创建） |
| `host.url_prefix` | str | 本插件路由前缀 |
| `host.plugin_id` | str | 插件 id |
| `host.vault` | object | `get(domain)` / `set(domain, token)` 凭证读写 |
| `host.tasks` | object | `create/update/delete/get` 统一任务表操作 |
| `host.http` | object | `get/post/...` 带鉴权的外部 HTTP 客户端 |
| `host.logger` | logging.Logger | 插件日志（自动带插件前缀） |
| `host.login_required` | decorator | 鉴权装饰器（框架处理 JWT，插件不碰 token） |
| `host.admin_required` | decorator | 管理员鉴权装饰器 |
| `host.app_state` | dict | 插件进程级状态容器（框架不干预内容） |
| `host.config` | dict | 来自 manifest 的 `backend` 段（只读） |

---

## 5. 框架加载流程（零业务耦合）

```python
# extensions_host/app.py —— 唯一需要改动的地方
def create_app():
    app = Flask('extensions_host')
    # ... error handlers ...
    app.register_blueprint(script_bp)        # 脚本引擎（保留，兼容旧脚本型插件）
    init_script_engine(app)
    _load_plugins(app)                        # 新增：纯插件加载
    return app

def _load_plugins(app):
    base = scripts_base_dir()
    for sc in load_all(base).values():
        be = sc.get('backend')
        if not be:
            continue
        try:
            mod = importlib.import_module(
                f"extensions.scripts.{sc['id']}.backend.server")
            factory = getattr(mod, be.get('factory', 'create_blueprint'))
            host = build_host(sc, app)        # 构造宿主对象
            bp = factory(host)
            app.register_blueprint(bp)
        except Exception as e:
            app.logger.error("插件 %s 加载失败: %s", sc['id'], e)
```

**删除插件文件夹 → `load_all` 扫不到 → 跳过 → 框架无感知。**

---

## 6. UI 挂载规范

- 前端只读取 `manifest.json` 的 `ui` 段决定挂载形态，**不缓存** `panel.html`（每次打开重新拉取，`Cache-Control: no-store`）。
- `panel.html` 通过标准 iframe 加载，框架注入 `token` 后通过 `postMessage` 下发。
- 插件前端调用自身后端：`/api/ext/<plugin_id>/*`，由框架代理鉴权。

---

## 7. 迁移检查清单（以 ai_chat 为例）

- [ ] 创建 `extensions/scripts/ai_chat/backend/server.py` 导出 `create_blueprint(host)`
- [ ] 将 `ai_chat.py` / `workflow_engine.py` / `plan_manager.py` 移入 `backend/`
- [ ] 替换所有 `from shared.xxx import` → `host.xxx`
- [ ] 替换 `from ai_chat import ai_mgr` / `from workflow_engine` → 同目录相对 import
- [ ] 路由前缀改为 `/api/ext/ai_chat/*`
- [ ] `manifest.json` 增加 `backend` 段
- [ ] 从 `routes.py` 删除所有 `/api/ai-chat/*` 硬编码路由
- [ ] 从 `extensions_host` 包移除 `ai_chat.py` / `workflow_engine.py` / `plan_manager.py`
- [ ] 验证：删除 `ai_chat/` 文件夹，框架启动不报错

---

## 8. 反模式（禁止）

```python
# ❌ 禁止：插件 import 框架内部模块
from extensions_host.ai_chat import ai_mgr
from shared.credential_vault import CredentialVault
from manager import mgr
import web.core.models

# ❌ 禁止：插件路由使用框架全局命名空间
@script_bp.route('/api/ai-chat', methods=['POST'])

# ❌ 禁止：插件直接解析 JWT / 处理鉴权
token = request.headers.get('Authorization')

# ✅ 正确：通过 host 契约
host.vault.get('codebuddy_token')
@host.login_required
def handler(): ...
```
