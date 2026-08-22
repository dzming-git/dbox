# AI 助手工作流选择：设计方案（配置驱动）

> 状态：设计稿（待评审）。本文档描述把现有「意图判断」重构为「工作流选择」的完整方案。
> 目标产物：先评审本方案，评审通过后按「后端框架 → 配置文件 → 前端按钮」顺序落地。

---

## 1. 背景与问题

当前 AI 助手在用户每次发消息时，后端 `analyze_intent()` 会调用一次 CodeBuddy 判断 4 类意图
（建议 / 缺陷 / 继续 / 聊天），结果存入任务 `extra['intent']` 并拼进 prompt 系统提示。

存在的问题：

1. **概念不直观**：「意图」对用户是黑盒，用户无法感知、无法干预，也无法复用。
2. **无差异流程**：4 类意图只是改了 prompt 措辞，没有真正分叉执行步骤
   （例如「缺陷」明明应该「先查 git → 建单 → 处理 → 最后查 git」，但实际没有这几步）。
3. **不可扩展**：判断逻辑与提示词写死在具体模块里，新增一类工作流必须改代码。

用户诉求：

- 更名为「**工作流选择**」，做一个**醒目的按钮**，用户可点击设置当前工作流。
- 支持**实时推断**：根据用户输入自动猜测工作流（技术可行时）；用户一旦手动设置，就停止自动推断。
- 每个工作流**独立设计不同流程 / 提示词 / 步骤**，例如：
  - 改代码类（建议、缺陷）：先检查 git → 最后再检查 git → 建单。
  - 继续类：选择要对哪个问题单继续（不先查 git，因为可能是上轮任务中途中断，git 改动不完整）。
  - 聊天类：不涉及代码改动，正常聊天。
- 采用**方案 2（配置驱动）**：代码里做框架，流程用配置文件描述。

---

## 2. 总体架构

```
┌───────────────────────── 前端 panel.html ─────────────────────────┐
│  醒目「工作流」按钮（顶部）                                           │
│    ├─ 当前工作流徽标（如 🔧 缺陷 / 💬 聊天 / ⏯ 继续）                 │
│    └─ 点击展开：工作流选择面板 + 「自动推断：开/关」开关               │
│  输入框（发送前带上 workflow_id，可选 manual_override 标志）          │
└───────────────┬───────────────────────────────────────────────────┘
                │  POST /api/<chat-route>  { message, workflow_id?, manual? }
                ▼
┌───────────────────────── 后端 chat 模块 ──────────────────────────┐
│  WorkflowEngine（框架，代码固定）                                    │
│    ├─ load_workflows()     读取 workflows/*.yaml                    │
│    ├─ infer_workflow(msg)  实时推断（可选，调 CodeBuddy 分类）       │
│    ├─ compile_prompt()     按 workflow 的 steps 拼装系统提示         │
│    └─ run_steps()          逐 step 执行：                                         │
│         step.kind = shell  → 跑 step.cmd，读 stdout 的 0/1 判定       │
│         step.kind = llm    → 把 step.prompt 注入本轮系统提示           │
│         step.kind = ask    → 向 UI 发问（等待用户选择，如选问题单）     │
│  CodeBuddyChatManager（现有 FIFO 队列 + 单 worker，不变）            │
└────────────────────────────────────────────────────────────────────┘
```

**核心改动点**：把 `analyze_intent()` 替换为 `WorkflowEngine`；prompt 拼装从「单段意图提示」
升级为「按 workflow 的 steps 拼装的多段提示」；前端新增可见按钮与设置面板。

---

## 3. 配置文件 Schema（方案 2 的核心）

文件位置：`extensions/<plugin_id>/workflows/*.yaml`（每个工作流一个文件，便于独立维护）。

统一字段：

```yaml
id: defect                 # 唯一 id，前端 / 入参都用它
name: 缺陷                  # 显示名
icon: 🐞                    # 醒目按钮上的图标
color: "#e5484d"           # 按钮主题色（前端高亮）
description: 修复代码缺陷，先查 git、建单、处理后复查 git
auto_infer: true           # 是否允许被实时推断命中（false=只能手动选，如「继续」默认手动）
infer_hint: |              # 给推断模型的样例描述（仅 auto_infer=true 时参与）
  用户说某功能坏了、报错、异常、不符合预期、要修 bug 时为「缺陷」

# 步骤链：worker 处理一轮对话时按顺序执行。
# 每个 step 是一条独立指令，最终汇聚成给 CodeBuddy 的系统提示 + 可选的前置/后置动作。
steps:
  - kind: shell            # 前置检查：运行命令，stdout 末行 0/1 决定是否满足
    id: git_clean_before
    when: start            # start=入队后立即跑（建单/处理前）；end=回复后跑
    cmd: git status --porcelain | findstr /R /C:"." >nul && echo 1 || echo 0
    expect: "1"            # 输出含 1 表示「git 不干净」
    on_expect_prompt: |    # 命中 expect 时，把这段文本注入系统提示，让 AI 处理
      ⚠️ 当前 git 工作区不干净（有未提交改动）。
      先判断这些改动属于本任务还是杂项：
      - 属于本任务的：确认有用且完整后提交（一次 git 只描述一个问题/优化，不提反馈中心/单号）。
      - 无用的临时文件/截图：删除，不要提交。
      提交后用文件方式写入 UTF-8 提交消息（避免 PowerShell 中文乱码）。

  - kind: ask              # 交互步骤：向用户提问，挂起等待答案
    id: create_ticket
    when: start
    question: 是否为本次修复在反馈中心建单？
    options: [建单, 跳过]
    inject_on:            # 用户选择后注入对应提示
      "建单": 处理完成后请通过反馈中心接口建单，并描述根因。
      "跳过": 本次不建单。

  - kind: llm              # 主处理提示：直接指导 CodeBuddy 如何干活
    id: main_task
    when: main
    prompt: |
      你是修复缺陷的工程师。定位根因、给出最小修改、验证、提交。
      每完成一个独立功能立即提交 git；禁止泄露开发者信息。

  - kind: shell
    id: git_clean_after
    when: end
    cmd: git status --porcelain | findstr /R /C:"." >nul && echo 1 || echo 0
    expect: "1"
    on_expect_prompt: |
      🔍 处理完成，但 git 工作区仍有未提交改动，请复查并清理/提交，
      保证仓库干净再结束。
```

`step.kind` 枚举：

| kind   | 含义                                                         | 关键字段                          |
|--------|--------------------------------------------------------------|-----------------------------------|
| shell  | 跑命令，stdout 末行匹配 `expect` 则把 `on_expect_prompt` 注入 | `cmd`, `expect`, `on_expect_prompt` |
| llm    | 把 `prompt` 直接注入系统提示（主流程指导）                    | `prompt`                          |
| ask    | 向 UI 提问并挂起，等用户选 `options` 之一，按 `inject_on` 注入 | `question`, `options`, `inject_on` |

`step.when` 枚举：`start`（处理前，建单/查 git）、`main`（主体提示，可多个）、`end`（回复后复查）。

> 设计取舍：把「检查 git 是否干净」抽象成一行 shell + 0/1 判定，正好对应你举的例子——
> 命令输出 1 表示要触发下面的提示词，提示词让 AI 清理 git 仓库（有用且完整就提交，没用删掉）。

---

## 4. 内置工作流（初版 4 个，全部用配置文件实现）

| id        | 名称   | icon | 改代码？ | 先查 git | 建单 | 后查 git | 可推断 |
|-----------|--------|------|----------|----------|------|----------|--------|
| `suggest` | 建议   | 💡   | 是       | 是       | 是   | 是       | 是     |
| `defect`  | 缺陷   | 🐞   | 是       | 是       | 是   | 是       | 是     |
| `resume`  | 继续   | ⏯    | 视情况   | **否**   | 否   | 是       | 否（默认手动）|
| `chat`    | 聊天   | 💬   | 否       | 否       | 否   | 否       | 是     |

**`resume`（继续）的特殊流程**：
- `auto_infer: false`，默认只能手动选（因为它本就是「接上中断的任务」）。
- 不设 `git_clean_before`（不先查 git，因为上轮可能中途停，git 改动不完整是正常的）。
- 第一步是 `ask`：列出最近未完成/失败的任务让用户选「对哪个问题单继续」，选完后把该任务上下文注入。
- 仍保留 `git_clean_after`（结束了还是要干净）。

> 实现状态：一期已落地「真正挂起/恢复」——worker 在 ask 步通过 `threading.Event` 阻塞，
> 前端弹选择卡，`POST /api/ai-chat/tasks/<id>/answer` 写入答案并唤醒（非简化写进对话版）。

> 「建议 / 缺陷」流程几乎一样（都改代码 + 建单 + 查 git），区别只在 `main_task` 的提示措辞与
> `infer_hint` 的分类边界。后续若需合并可再调，初版先分两个保持清晰。

---

## 5. 后端框架设计（代码固定部分）

`WorkflowEngine`（新增于 chat 模块或独立 `workflow_engine.py`）：

```python
class WorkflowEngine:
    def __init__(self, dir_): self.dir = dir_; self.cache = None
    def load_workflows(self) -> dict[str, Workflow]: ...      # 读 yaml，带缓存，文件变更热重载
    def infer_workflow(self, message: str, history: list) -> str | None:
        # 仅对 auto_infer=true 的工作流，调一次轻量 CodeBuddy 分类，返回 id
        # 技术不可行（无 token/超时）时返回 None，由前端回落到上次选择或默认 chat
    def compile(self, wf: Workflow, answers: dict) -> str:
        # 把 steps 中 kind=llm 的 prompt 与 on_expect_prompt（已命中）拼成系统提示段
    def run_shell_step(self, step) -> bool:
        # subprocess 跑 step.cmd，取末行，返回是否命中 expect
```

与现有 `CodeBuddyChatManager` 的衔接：

- `enqueue(message, user_id, workflow_id=None, manual=False)`：新增工作流参数。
  - `workflow_id` 由前端带（用户手动选或前端缓存的自动推断结果）。
  - 若前端没带：worker 处理时调用 `infer_workflow()` 推断；推断失败回落 `chat`。
- 任务 `extra` 增加 `workflow_id` / `workflow_name` / `manual`，SSE `queued` 事件携带，
  前端把「当前工作流徽标」显示出来。
- `shell` 步骤：在 worker 真正调 CodeBuddy **前**（`start` 步）与 **后**（`end` 步）各跑一遍，
  命中 `expect` 时把 `on_expect_prompt` 并入系统提示，让模型在当轮对话里顺手处理。
- `ask` 步骤：通过 SSE 下发 `ask` 事件（含 question/options），前端弹选择；用户选完
  `POST /api/ai-chat/tasks/<id>/answer` 回填，worker 继续。这要求 FIFO worker 支持「挂起/恢复」，
  初版可简化为：把 `ask` 这一步的提示直接以「请回复 建单/跳过」形式写进对话，等用户下一句——
  完整挂起留作二期（见第 8 节）。

> 注意：现有 `analyze_intent` 每次发消息都调一次 CodeBuddy，**实时推断同样有这成本**。
> 故 `infer_workflow` 只在「用户未手动设且前端未带 id」时触发；一旦用户手动选过，
> 前端后续请求都带 `workflow_id` + `manual=true`，后端不再推断（满足「设置后不自动推断」）。

---

## 6. 前端设计（醒目按钮 + 设置面板）

`panel.html`（iframe 内）改动：

1. **顶部新增工作流栏**（紧贴标题栏下方，整行高亮，颜色取 `wf.color`）：
   ```
   [ 🐞 缺陷 ▾ ]   自动推断：●开    （点击 ▾ 展开选择面板）
   ```
   - 没选时显示中性态：`[ 选择工作流 ▾ ]`（灰色虚线框，更醒目提醒用户选）。
   - 选中后整行底色 = `wf.color` 淡色，图标+名称高亮。

2. **点击展开「工作流选择面板」**（浮层）：
   - 列出 `GET /api/ai-chat/workflows` 返回的全部工作流卡片（图标+名称+描述）。
   - 每张卡片可点；点完写入 `state.workflowId` + `state.manual=true`，按钮文字更新，面板收起。
   - 面板内含「自动推断」开关：开=发送时不带 workflow_id（让后端推断）；
     关=强制用已选的工作流（即使后端推断也按手动的来）。
   - 用户一旦手动点选某卡片，自动把开关置为「关」并标记 `manual=true`
     （满足「用户设置后不自动推断」）。

3. **发送逻辑**：
   ```js
   const payload = { message: v };
   if (state.autoInfer && !state.manual) { /* 不带 workflow_id，后端推断 */ }
   else { payload.workflow_id = state.workflowId; payload.manual = true; }
   ```
   首次进入若 `state.workflowId` 为空且自动推断开，则前端也不带 id，交给后端推断；
   推断结果通过 `queued` 事件的 `extra.workflow_id` 回显到按钮上。

4. **步骤可视化（可选增强）**：`queued`/`phase` 事件携带 `workflow_id`，
   在阶段气泡顶部加一行「工作流：缺陷」标签，让用户看清当前走的是哪条流程。

新增后端接口：
- `GET /api/ai-chat/workflows` → 返回全部工作流元信息（id/name/icon/color/description/auto_infer），
  供前端渲染选择面板（不需要登录态之外的特殊权限，复用 `@login_required`）。

---

## 7. 与现有规则的衔接（重要，避免破坏既有约束）

工作流配置里的 git 提示词必须复用项目既定规则（来自 workspace rules）：

- 提交用**文件方式**写 UTF-8 消息：`git commit -F _m.txt`，提交后 `git log -1 --format=%s` 复核。
- 一个独立功能一次 git；禁提反馈中心/单号；自动助手身份只用于回留言，git author 保持开发者原身份。
- 临时脚本/截图不提交；代码禁硬编码绝对路径。

这些规则写进 `on_expect_prompt` / `main_task` 的提示词即可，框架本身不感知。

---

## 8. 落地顺序与分期

**一期（本方案范围，已全部实现）**：
1. 后端 `WorkflowEngine` + 4 个 yaml 配置 + `enqueue` 加参 + `GET /api/ai-chat/workflows`。
2. 前端醒目按钮 + 选择面板 + 自动推断开关 + 发送带参。
3. `shell` 步骤前后置执行；`llm` 步骤注入。`ask` 步骤**一期即做真正挂起/恢复**
   （worker 通过 `threading.Event` 阻塞，前端弹选择卡，`POST .../answer` 唤醒）。
4. 保留 `_classify_intent` 关键词确定性推断作为 `infer_workflow` 兜底（无需每轮调模型）。

**二期（可选增强）**：
- 工作流配置 UI 化（在面板内直接编辑 yaml 并热重载）。
- 推断接模型分类（cb_classify 回调） + 置信度，低置信时前端弹「推荐：缺陷，确认？」。
- 同 `resume` 把 `prev_issue` 真实回填到反馈单续写上下文。

---

## 9. 风险评估

- **推断成本**：实时推断每轮多一次 CodeBuddy 调用，同旧的 `analyze_intent` 成本，可接受；
  用户手动选后完全免除。
- **shell 步骤安全**：`cmd` 来自本地配置文件（开发者可控），非用户输入，风险低；
  仍建议白名单目录 + 超时（如 30s）+ 仅允许 `git` 等少数命令（可在引擎层加 `allowed_prefixes`）。
- **iframe 缓存**：`get_panel` 已设 `no-store`，面板改动即时生效；配置 yaml 走后端接口，热重载。
- **向后兼容**：旧任务无 `workflow_id` 时回落 `chat`，历史记录不受影响。

---

## 10. 待确认点（已确认）

1. 「建议 / 缺陷」**保持两个**（分类边界清晰）。✅ 已实现（suggest.yaml / defect.yaml）。
2. `resume`（继续）**默认手动、不推断**。✅ 已实现（auto_infer=false）。
3. `ask` 步骤**一期即做真正挂起/恢复**（worker 阻塞 + 前端选择卡 + answer 接口唤醒）。✅ 已实现。
4. 配置文件放 `extensions/<plugin_id>/workflows/`。✅ 已实现。

## 11. 实现记录（一期落地）

- 后端框架：`src/extensions_host/workflow_engine.py`（加载 yaml / 关键词推断 / 编译 prompt / 执行 shell 步）。
- 配置：`extensions/<plugin_id>/workflows/{defect,suggest,resume,chat}.yaml`。
- chat 模块：`enqueue` 增 `workflow_id`/`manual`；`_process` 改为配置驱动；新增 `list_workflows`、
  `_resolve_workflow`、`_run_ask_step`（挂起）、`answer_task`（唤醒）、`_git_has_new_commit`、`_recent_unfinished_tasks`；
  tasks 表新增 `extra` 列（存 workflow 元数据）。
- `routes.py`：入队接口透传 workflow；新增 `GET /api/<chat-route>/workflows`、
  `POST /api/<chat-route>/tasks/<id>/answer`。
- 前端 `panel.html`：顶部「工作流选择」醒目按钮 + 选择浮层 + 自动推断开关；发送带参；
  SSE `workflow` 回显、`ask` 弹选择卡。

> 验证：引擎加载/编译/ shell 步已通过 Python 冒烟测试；前端 UI 用 playwright 截图核对按钮与浮层布局。
