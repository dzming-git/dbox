# 扩展脚本 UI 注入机制（设计草案 · 待评审）

> 状态：草案。目标：让扩展脚本不仅能"后台跑任务"，还能"在前端注入自己的常驻 UI"
> （悬浮框、抽屉、面板等），实现复杂交互功能（如 AI 对话窗、下载前预览）。

## 1. 背景与动机

现有脚本引擎（`src/web/script_engine`）已经具备：

- manifest 驱动的发现与启用机制
- 凭证保险库（`common/credential_vault`）—— 统一管理 Cookie/Token/APIKey
- 子进程隔离执行 + JSON 行协议（progress / log / await_input / result）
- 双向通道：`/api/scripts/<job>/notify`（脚本回调主程序入库）与
  `/api/scripts/<job>/input`（主程序向前端要输入、脚本侧长轮询）
- 结果自动入库（ingest_file + 多模式）

但**所有交互都发生在"脚本中心"页面里**，UI 是主程序预先写死的
（表单由 `params` 声明式渲染，`interface: x_download` 是唯一的特例面板）。
脚本无法在前端"长出一个自己的界面"。

目标能力（用户原话）：

1. 脚本可注入**多个悬浮框**，点开展开内容
2. 脚本可调用凭证保险库里的 AI token，直接弹出**对话窗**实时对话
3. X 下载器可在下载前**先预览**（图/视频/元数据），再决定是否下载

## 2. 设计原则（不可破坏现有安全模型）

| 现有约束 | 草案如何保持 |
|---|---|
| 脚本只在白名单目录内、绝不用 shell | UI 静态资源同样限定在脚本自己的 `assets/` 子目录，路由带脚本 ID 鉴权 |
| 子进程隔离、凭证物化到临时目录 | UI 扩展**不直接拿原始凭证**，统一经后端代理调用（token 永不进前端 JS） |
| 管理员启用才可用 | UI 扩展跟随脚本 `enabled` 开关，未启用不加载 |
| 单向 JSON 行协议 | UI 复用既有 `notify` / `input` 通道与同一套 job token 鉴权 |

## 3. 总体架构（三层解耦）

```
┌──────────────────────────────────────────────────────────┐
│  前端 Shell（App.vue / 全局挂载层）                         │
│   ├─ 脚本中心页（现有：表单 + 任务列表）                    │
│   └─ UI 扩展挂载区（新增）：按需渲染各脚本声明的悬浮组件     │
└───────────────┬──────────────────────────┬───────────────┘
                │ 拉取 /api/scripts/list（含 ui 信息）        │ 用户交互事件
                ▼                                            ▼
┌──────────────────────────┐                 ┌──────────────────────────┐
│  后端 routes（script_bp） │                 │  脚本 UI 静态资源（iframe）│
│  /api/scripts/<id>/ui     │◄──代理──┐       │  assets/index.html        │
│  /api/scripts/<id>/proxy  │        └──────►│  （sandbox，隔离 DOM/window）│
└────────────┬─────────────┘                 └──────────────────────────┘
             │ 读 manifest + 凭证保险库
             ▼
┌──────────────────────────┐
│  CredentialVault         │  ← token 只在这里，绝不暴露给前端
└──────────────────────────┘
```

**关键分离**：执行层（子进程任务）与 UI 层（常驻组件）是两个独立维度。
一个脚本可以：
- 只有任务（现有行为）
- 只有 UI 扩展（如 AI 对话窗，纯前端+后端代理，不跑子进程）
- 两者都有（如 X 下载器：预览 UI + 下载任务）

## 4. Manifest 扩展

在现有 manifest.json 增加可选 `ui` 段：

```json
{
  "id": "ai_assistant",
  "name": "AI 对话助手",
  "command": "run.py",
  "runtime": "python",
  "enabled_by_default": false,
  "ui": {
    "entry": "assets/index.html",
    "mount": "floating",
    "label": "AI",
    "icon": "💬",
    "title": "AI 对话",
    "width": 380,
    "height": 520,
    "needs_credential": { "kind": "token", "domain": "codebuddy" }
  }
}
```

字段说明：
- `entry`：脚本目录内相对路径，限定 `assets/` 前缀（白名单校验）
- `mount`：`floating`（右下悬浮球）/ `drawer`（侧边抽屉）/ `panel`（嵌入脚本中心）
- `needs_credential`：声明该 UI 需要的凭证种类+域名，后端加载前预检，缺失则禁用并提示去凭证保险库配置

## 5. 前端挂载机制

新增全局组件 `<ScriptExtensionsHost>`，挂载在 App.vue 根部（不在路由内，常驻）：

1. 启动时调用 `GET /api/scripts/list`（已有接口，扩展返回 `ui` 字段）
2. 对每个 `enabled && ui` 的脚本：
   - `mount=floating`：渲染一个悬浮触发按钮（用 `icon`/`label`），点击展开 iframe 容器（`width`/`height`）
   - `mount=drawer`：在侧边挂一个抽屉入口
   - `mount=panel`：在脚本中心页该脚本卡片下嵌入 iframe
3. iframe 用 `sandbox="allow-scripts allow-same-origin"`（或进一步用 `allow-scripts` 仅，
   通过 postMessage 通信，杜绝直读主程序 cookie/路由）
4. iframe `src` 指向 `GET /api/scripts/<id>/ui`（后端校验 enabled + 白名单路径后返回静态文件）

## 6. UI 与后端的通信协议

UI 内部（iframe 沙箱）**不允许直连外部 AI/下载 API**（token 不出保险库）。
统一走后端代理：

### 6.1 后端代理通道（新增）

```
POST /api/scripts/<id>/proxy
  body: { "action": "...", "payload": {...} }
  后端：
    1. 校验脚本 enabled
    2. 从 CredentialVault 取出 needs_credential 对应的 token
    3. 按 manifest.ui 里声明的 proxy 白名单（如 https://*.codebuddy.ai）
       转发请求，注入 Authorization
    4. 把响应返回给 iframe（可流式 SSE）
```

manifest.ui 需声明 `proxy_allowlist`（域名白名单），后端强制校验，
防止脚本 UI 借代理访问任意内网地址。

### 6.2 iframe ↔ 主程序（postMessage）

沙箱内 UI 通过 `window.parent.postMessage` 通知主程序做"触发下载任务"等动作：

```
// UI -> 主程序：请求发起一个下载任务（复用现有 run 接口）
parent.postMessage({ type: 'dbox:run-script', scriptId, params }, '*')
// 主程序 -> UI：任务进度（复用 job 状态）
parent.postMessage({ type: 'dbox:job-progress', jobId, percent }, '*')
```

主程序侧用一个轻量 `ScriptBridge` 监听 message，做权限校验后调用
`mgr.run(...)` / 转发 job 进度。

## 7. 两个示范实现

### 7.1 AI 对话悬浮窗（ai_assistant）

- manifest.ui.mount = floating，needs_credential = codebuddy token
- assets/index.html：一个聊天界面（输入框 + 消息流）
- 发消息 → `POST /api/scripts/ai_assistant/proxy` → 后端用保险库 token 调 AI → SSE 流式返回
- 不跑子进程、不落临时文件，纯 UI + 代理

### 7.2 X 下载器预览（x_downloader 增强）

- 现有 x_downloader 增加 `ui` 段（mount=floating，label="X预览"）
- assets/index.html：输入推文 URL → 调 `/proxy`（白名单 X 预览接口）
  → 展示作者/图集缩略图/视频预览
- 用户勾选要下载的项 → `postMessage` 触发主程序 `mgr.run(x_downloader, {url, selected})`
- 后台子进程照常下载并入库（现有流程不变）

## 8. 安全清单（落地前必须实现）

- [ ] `entry` 强制 `assets/` 前缀，且经 `os.path.abspath` 防 `../` 逃逸
- [ ] iframe `sandbox` 不含 `allow-same-origin` 直读主程序存储；跨域通信只走 postMessage + 白名单 origin 校验
- [ ] 代理 `proxy_allowlist` 域名白名单，拒绝内网/私有地址（防 SSRF）
- [ ] UI 扩展跟随脚本 `enabled`，管理员未启用则不加载、不暴露任何路由
- [ ] `needs_credential` 缺失时 UI 禁用并提示，token 绝不以任何形式下发前端
- [ ] 代理调用计审计日志（谁、何时、调了哪个外部域名）

## 9. 与现有代码的改动点（预估）

| 文件 | 改动 |
|---|---|
| `script_engine/manifest.py` | 解析 `ui` 段，校验 `entry` 白名单 |
| `script_engine/routes.py` | 新增 `/ui`、 `/proxy` 路由；list 接口附带 `ui` 信息 |
| `script_engine/manager.py` | `needs_credential` 预检辅助方法 |
| `src/webui/src/App.vue` | 挂载 `<ScriptExtensionsHost>` |
| `src/webui/src/components/ScriptExtensionsHost.vue` | 新增：轮询 list、渲染悬浮/抽屉、ScriptBridge |
| 各示例脚本 `manifest.json` + `assets/` | 新增 UI 声明与静态资源 |

## 10. 开放问题（评审时讨论）

1. iframe 沙箱粒度：用 `sandbox="allow-scripts"`（最严，纯 postMessage）还是
   允许 `allow-same-origin`（开发简单但风险高）？建议默认最严。
2. 代理是否支持流式 SSE（AI 对话需要）；后端 Flask 需 `Response(stream_with_context)`。
3. UI 扩展的版本/热更新：脚本更新后前端如何感知（reload 扫描 vs 自动）。
4. 是否允许脚本 UI 调用主程序既有 API（如读视频列表）？需定义最小权限集。
