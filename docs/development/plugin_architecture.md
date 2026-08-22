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
| **框架零硬编码** | **框架任何源码（后端 / 前端）不得出现具体插件 id**。插件是否启用、如何挂载、是否有独立路由、是否轮询忙碌态，全部由 manifest 字段声明，前端按字段动态渲染。删掉插件目录后，其所有行为自动消失，框架代码原样不变 |

---

## 2. 目录结构（压缩包内部）

所有插件**平铺**于 `extensions/` 一级子目录（无 `scripts` 中间层）：

```
extensions/                        ← 所有插件的根（框架仅扫描此一级）
├── <plugin_id>/                   ← 插件根目录（= 压缩包解压目标）
│   ├── manifest.json              ← 唯一入口：元信息 + 能力声明
│   ├── backend/                   ← 插件后端（可选，纯前端插件可无）
│   │   ├── server.py              ← 导出 create_blueprint(host) 工厂
│   │   ├── engine.py              ← 业务逻辑
│   │   └── db.py                  ← 自带 SQLite 封装
│   ├── ui/                        ← 前端（可选）
│   │   ├── panel.html             ← iframe 入口
│   │   └── assets/                ← css/js 静态资源
│   ├── workflows/                 ← 配置驱动的步骤定义（可选）
│   │   └── *.yaml
│   └── requirements.txt           ← 插件私有依赖（可选）

> **注**：`extensions/` 下的每个插件都是自包含目录，插件本体可独立维护、按需放置；框架扫描 `extensions/` 一级子目录即可发现并加载，无需在本仓库登记。
└── ...
```

> **为什么没有 `scripts` 这一层？** 历史上插件曾放在 `extensions/scripts/<id>/`，
> 但 `extensions` 与 `scripts` 语义重复（都是「扩展/脚本」）。现已扁平化：
> `extensions/<id>/` 直接一个插件一目录，框架扫描 `extensions/` 一级子目录。
> `scripts_base_dir()` 返回 `extensions`，不再拼接 `scripts`。

**关键约束**：`backend/` 内的模块**只 import 标准库、第三方库、以及自身目录**，
**严禁** `import extensions_host`、`import shared`、`import web`、`import manager` 等框架内部包。
需要框架能力时一律通过 `host` 对象获取（见 §4）。

---

## 3. manifest.json 规范

```json
{
  "id": "<plugin_id>",
  "name": "插件显示名",
  "version": "1.0.0",
  "description": "插件描述",
  "enabled": true,
  "api_version": 1,

  "ui": {
    "mount": "floating",          // floating | tab | sidebar | none
    "title": "插件标题",
    "icon": "💬",
    "entry": "panel.html",        // ⚠️ 相对 ui/ 目录，不是 "ui/panel.html"（框架自动拼 ui/）
    "sandbox": "allow-scripts allow-same-origin",
    "needs_credential": { "kind": "token", "domain": "codebuddy" },
    "standalone_route": "/<route>",   // 可选：声明后框架动态注册独立全屏路由
    "busy_poll": "/api/ext/<plugin_id>/tasks"  // 可选：声明后悬浮气泡周期轮询该接口（驱动忙碌/未读态）
  },

  "backend": {                     // 省略则表示纯前端/脚本型插件
    "module": "backend.server",   // 框架动态 import 的模块路径
    "factory": "create_blueprint",// 该模块导出的工厂函数名
    "url_prefix": "/api/ext/<plugin_id>",
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
| `ui.entry` | ❌ | UI 入口文件，**相对 `ui/` 目录**（框架拼接 `ui/`），如 `panel.html` |
| `ui.standalone_route` | ❌ | 独立全屏路由路径（如 `/ai-assistant`）；声明后框架 `addRoute` 注册，不声明则无独立页 |
| `ui.busy_poll` | ❌ | 忙碌态轮询接口（相对路径）；声明且 `mount=floating` 时，宿主周期轮询驱动气泡动画/未读角标 |
| `ui.needs_credential` | ❌ | 凭据声明，框架据此在 UI 提示用户配置 |
| `backend.module` | ❌ | 有后端逻辑时必填 |
| `backend.factory` | ❌ | 默认 `create_blueprint` |
| `backend.url_prefix` | ❌ | 默认 `/api/ext/<id>` |
| `backend.needs` | ❌ | 能力声明清单，缺失则框架启动告警 |

> **`ui.entry` 的坑**：框架 `get_panel` 路由会自动在 `entry` 前拼接 `ui/` 目录，
> 因此 `entry` 必须是 `ui/` 内的相对路径（如 `panel.html`），写成 `ui/panel.html`
> 会得到 `ui/ui/panel.html` 导致 404。

---

## 4. 宿主对象（host）API 契约

框架在加载插件后端时，构造一个 `host` 对象注入工厂函数。插件**只依赖以下稳定接口**：

```python
def create_blueprint(host):
    bp = Blueprint('ext_<plugin_id>', __name__,
                   url_prefix=host.url_prefix)

    @bp.route('/chat', methods=['POST'])
    @host.login_required
    def chat():
        # 1) 数据目录（插件私有，删插件即清空）
        db_path = os.path.join(host.data_dir, '<plugin_id>.db')

        # 2) 凭证读取（替代直接 import credential_vault）
        token = host.vault.get('codebuddy_token')

        # 3) 统一任务表注册（替代直接 import unified_tasks）
        host.tasks.create(kind='<plugin_id>', title='...', owner_id=host.user_id)

        # 4) 调用外部服务（替代 import platform_client）
        host.http.post('http://localhost:8080/internal/feedback', json={})

        # 5) 日志
        host.logger.info('<plugin_id> enqueue %s', task_id)

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
    base = scripts_base_dir()                # -> <root>/extensions
    for sc in load_all(base).values():
        be = sc.get('backend')
        if not be:
            continue
        try:
            # ⚠️ 扁平化后模块路径为 extensions.<id>.backend.server（不再有 scripts 层）
            mod = importlib.import_module(
                f"extensions.{sc['id']}.backend.server")
            factory = getattr(mod, be.get('factory', 'create_blueprint'))
            host = build_host(sc, app)        # 构造宿主对象
            bp = factory(host)
            app.register_blueprint(bp)
        except Exception as e:
            app.logger.error("插件 %s 加载失败: %s", sc['id'], e)
```

**删除插件文件夹 → `load_all` 扫不到 → 跳过 → 框架无感知。**

### 前端加载流程（零硬编码）

- 前端在启动时调用 `GET /api/ui-extensions` 拿到所有声明了 `ui` 段的已启用插件。
- **悬浮面板**（`ExtensionHost.vue`）：遍历列表渲染每个 `mount=floating` 的插件气泡；
  若插件声明了 `ui.busy_poll`，宿主周期轮询该接口驱动忙碌动画与未读角标；
  若插件声明了 `ui.standalone_route`，则当路由正处于该路径时自动隐藏悬浮气泡（避免重复）。
  **全程不出现任何具体插件 id。**
- **独立全屏路由**（`main.ts` → `registerExtensionRoutes()`）：遍历列表，
  对每个声明了 `ui.standalone_route` 的插件动态 `router.addRoute()`，
  挂载通用 `ExtensionStandalone.vue`（按 `props.id` 取对应 panel.html）。
  **框架路由表不写死任何插件路径。**

---

## 6. UI 挂载规范

- 前端只读取 `manifest.json` 的 `ui` 段决定挂载形态，**不缓存** `panel.html`（每次打开重新拉取，`Cache-Control: no-store`）。
- `panel.html` 通过标准 iframe 加载，框架注入 `token` 后通过 `postMessage` 下发。
- 插件前端调用自身后端：`/api/ext/<plugin_id>/*`，由框架代理鉴权。
- 主服务网关（`src/web/main.py`）以通用前缀 `/api/ext` 代理所有插件后端，
  **不在 `_SCRIPT_PREFIXES` 中硬编码任何具体插件的路径**。

---

## 7. 迁移检查清单（以任一插件为例，下文用 `<plugin_id>` 泛指）

- [ ] 将插件目录放到 `extensions/<plugin_id>/`（扁平，无 `scripts` 中间层）
- [ ] 创建 `extensions/<plugin_id>/backend/server.py` 导出 `create_blueprint(host)`
- [ ] 将插件主逻辑模块移入 `backend/`
- [ ] 替换所有 `from shared.xxx import` → `host.xxx`
- [ ] 替换跨模块顶层 import → 同目录相对 import
- [ ] 路由前缀改为 `/api/ext/<plugin_id>/*`（manifest `backend.url_prefix`）
- [ ] `manifest.json` 增加 `backend` 段；`ui.entry` 写 `panel.html`（非 `ui/panel.html`）
- [ ] 若需独立全屏页：`ui.standalone_route`；若需气泡轮询：`ui.busy_poll`
- [ ] 从 `routes.py` 删除所有该插件的硬编码路由
- [ ] 从 `extensions_host` 包移除插件专有模块
- [ ] **前端**：`router/index.ts` 不得写死具体路由，改为 `registerExtensionRoutes()` 动态注册
- [ ] **前端**：`ExtensionHost.vue` 不得写死具体插件 id，改为遍历 `busy_poll` / `standalone_route`
- [ ] 验证：删除该插件文件夹，框架启动不报错；刷新前端对应路由自然失效
- [ ] 更新本文档与 `ai_workflow_selection.md` 中的路径引用

---

## 8. 反模式（禁止）

```python
# ❌ 禁止：插件 import 框架内部模块
from extensions_host.<some_module> import some_mgr
from shared.credential_vault import CredentialVault
from manager import mgr
import web.core.models

# ❌ 禁止：插件路由使用框架全局命名空间
@script_bp.route('/api/<some-route>', methods=['POST'])

# ❌ 禁止：插件直接解析 JWT / 处理鉴权
token = request.headers.get('Authorization')

# ✅ 正确：通过 host 契约
host.vault.get('codebuddy_token')
@host.login_required
def handler(): ...
```

```typescript
// ❌ 禁止：前端源码写死具体插件 id
if (ext.id === '<plugin_id>') { ... }
const resp = await fetch('/api/ext/<plugin_id>/tasks')
router.addRoute({ path: '/<some-route>', ... })

// ✅ 正确：按 manifest 字段驱动，id 完全来自数据
if (ext.ui?.standalone_route) router.addRoute({ path: ext.ui.standalone_route, ... })
if (ext.ui?.busy_poll) poll(ext.ui.busy_poll)
```

> **零硬编码是这条规范的核心红线**：任何新增插件都不应要求修改框架的
> 后端 `main.py` / `routes.py` 或前端 `router` / `ExtensionHost` / `App.vue`。
> 如需新能力，先扩展 manifest 字段与框架的通用处理逻辑，而非特判某个插件。
