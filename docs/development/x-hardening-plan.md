# X 插件加固计划：从「改很多遍」到「一次改对」

> 起因：2026-09-24 复盘。近期多个 bug（打开慢、徽标时机、重搜完成无变化、新设备搜索页为空…）都要反复改多轮才收敛。
> 结论：**方向没错，缺的是"护栏"**——没有契约声明、没有测试网、没有模块边界，导致每次改动的爆炸半径不可知。

---

## 0. 这份计划要达成什么

### 0.1 问题定义

不是"代码写错了"，而是三件事同时缺失：

1. **契约没有落点**：哪些持久化键、什么策略、谁产出、何时该取回——全凭约定俗成，散落在 9335 行里。
2. **验证是手工的**：改完只能手写一次性脚本验一条路径，其余路径靠用户上报。
3. **边界不存在**：一个文件、357 个函数、116 个模块级可变变量，任何函数都能改任何状态。

### 0.2 判定标准（可执行）

计划完成时，下面这条命令必须存在且能拦住同类问题：

```bash
node scripts/x_guard.js      # 键漂移 / 键名一致性 / 重键取回覆盖 —— 秒级，无副作用
node scripts/x_smoke.js      # 黄金路径端到端（真服务 + 无头浏览器）—— 分钟级
```

**验收口径**：此后任何键相关或前后端契约相关的改动，跑 `x_guard` 就能立刻知道有没有断链；跑 `x_smoke` 就知道核心流程有没有坏。**"改 5 遍"必须变成"改 1 遍 + 跑 1 次"。**

### 0.3 明确不做（避免范围失控）

- **不重写** panel.html，不做组件化/框架迁移；
- **不改** 后端存储格式、不迁移数据；
- **不动** 已经稳定工作的业务逻辑（只搬位置、只加声明）。

---

## 1. 事实基线（2026-09-24 取证）

| 指标 | 实测 |
|---|---|
| `extensions/x/ui/panel.html` | **9335 行**、顶层函数 **≈357**、模块级可变变量 **≈116**、`innerHTML =` **145 处** |
| `extensions/x/backend/server.py` | 3408 行、**39** 个 `@bp.route` |
| `extensions/x/backend/run.py` | 3837 行 |
| `extensions/x/backend/cache_store.py` | 298 行 |
| 持久化键 | ≈20 个 XSTATE 键 + 6 个 localStorage 键，**无集中声明** |
| 针对 X 的自动化测试 | **0**（仅 `backend/_smoketest.py` 99 行，只覆盖下载器） |

**已实证的三类结构性问题**

1. **同概念多实现**：关键词 key 的哈希写了两遍 —— 前端 `panel.html:6702 kwKey` 与后端 `server.py:2486-2498 _kw_key`，仅靠注释声明"与前端一致"；推文内容存在 3+ 份（前端 `panel.html:5064 XTWEETS` 单缓存、后端 sqlite、后端后台直接写 `feed:tweets:items`，外加 localStorage 镜像 `panel.html:5184`）。
2. **键名会漂移**：框架用 `'feed:'+'main'+':items'` 拼（`src/extensions_host/static/state.js:423-430`），插件与后端硬编码字面量（`panel.html:1455`、`server.py:1592/1620/1735/2231`）。
3. **一个键两个写者**：`bm:list` 前端写 `panel.html:3647`、后端写 `server.py:1773`；`like:list` 同理（`3727` / `1793`）。

**本次 session 的回归实证（最重要的一条）**

`heavyKeys`（排除大缓存的性能优化）本身正确，却静默打断了 **4 个调用点**共同依赖的隐式契约"这些键 pull 得到"，且以三种不相干的表象分三次暴露：重搜完成无变化（`panel.html:7814`）→ 新设备搜索页为空（`panel.html:7899`）→ 换设备用户页读旧缓存（`panel.html:8754`）。**这正是"契约缺失 + 无测试网"的教科书表现。**

---

## 2. 阶段总览

| 阶段 | 内容 | 依赖 | 预估 | 风险 |
|---|---|---|---|---|
| **0** | 护栏先行：验证规范 + 端到端脚手架 | — | 0.5 天 | 极低 |
| **1** | 键注册表 + 取回策略集中化 | 0 | 1 天 | 低（纯声明 + 收口） |
| **2** | 最小测试网（契约测试 + 黄金路径） | 0、1 | 1 天 | 低 |
| **3** | 消除重复实现（kwKey、推文内容、游标/锚点） | 2 | 1 天 | 中（触及算法，但有网） |
| **4** | 在 panel.html 开缝（状态门面 → feed/锚点 → 视图 → 搜索） | 2 | 2~3 天 | 中（纯搬移 + 冻结） |
| **5** | 修方向性依赖（后台线程自调 HTTP） | 2 | 0.5 天 | 中 |
| **6** | 防复发（CI 守卫 + 提交约定） | 1、2 | 0.5 天 | 极低 |

**顺序理由**：0/1/2 是"安全网"，必须先有；3/4/5 是"结构整治"，有了网才敢动；6 是把它固化下来。

---

## 3. 每步详细说明

### 阶段 0：护栏先行

#### 0.1 固化验证规范

**改什么**：在 `docs/development/` 下新增 `x-verification-rules.md`（或并入本档附录），写清两条铁律（本次 session 血泪换来）：

- **必须分别测「单独串行」与「页面并发」**：三处服务端开销在串行测试里全都隐形（都 12ms），一并发就 150ms+，现象酷似"端点算法慢"。
- **改 `extensions/` 下文件会触发扩展宿主热重载**：重载窗口内请求 502/503、耗时 2s+，**测速前必须等稳定**（本次因此误判过一次）。

**验收**：规则文档存在，且 `x_smoke.js` 内部实现遵守（见 0.2 的 `waitStable()`）。

#### 0.2 固化端到端脚手架

**改什么**：新增 `scripts/x_e2e_lib.js`，把本次反复手写的样板固化为库：

- 登录取 token：`POST /api/v2/auth/login`（`{username:'root', password:'<初始密码>'}`）→ `data.access_token`；
- 浏览器上下文注入：`localStorage.token / refresh_token / user`；`ignoreHTTPSErrors`、移动视口 `390×844`、`isMobile/hasTouch`；
- playwright 复用：`require('C:/Users/<用户>/AppData/Roaming/npm/node_modules/@playwright/cli/node_modules/playwright-core')`，`channel:'msedge'`, `headless:true`；
- **frame 定位**：轮询所有 frame，等 `typeof XSTATE !== 'undefined' && XSTATE.pullKeys`（面板就绪），而不是 `waitForTimeout` 猜；
- **`waitStable()`**：等最近一次请求结束 ≥300ms 且无重载迹象，再开始计时（对抗热重载窗口）；
- 资源拦截：`resourceType()==='font'` → abort。

**验收**：`node -e "require('./scripts/x_e2e_lib.js').smoke()"` 能打印一次关注流打开的首屏时间与锚点差值。

**风险**：极低（新文件，不改产品代码）。

---

### 阶段 1：键注册表 + 取回策略集中化

> 目标：把"哪些键、什么策略、谁产出、何时取回"变成**一处声明**，让 `heavyKeys` 那类改动不可能再静默断链。

#### 1.1 生成键清单（本计划的附录产物）

**做法**：用三条 grep 枚举，人工确认后登记：

```bash
grep -n "XSTATE\.\(get\|set\)(" extensions/x/ui/panel.html
grep -nE "const [A-Z][A-Z0-9_]*_KEY = " extensions/x/ui/panel.html
grep -n "host\.state\.\(get\|put\)(\|_bg_state_put(" extensions/x/backend/server.py
```

**当前已确认的清单（草稿，需补 `cache` 键的归属）**：

| 键 | 策略 | 写者（file:line） | 主要读者 | 重键 | 取回方式 |
|---|---|---|---|---|---|
| `feed:main:items` | union_by_id | `server.py:1620,1735` | 首屏/`FEED.main` | **是** | 产出后 `pullKeys` |
| `feed:tweets:items` | union_by_id | `server.py:1735,2611`、`panel.html:5064` | 卡片渲染 | **是** | 产出后 `pullKeys` |
| `feed:user:<uid>` | union_by_id | `server.py:2798` | `panel.html:8829` | **是** | 用户页 `pullKeys`（已修 `8759`） |
| `feed:main:cursor` | max | `server.py:1658,2281` | `panel.html:2297` | 否 | 普通 pull |
| `feed:main:anchor` | lww（框架） | 前端 | `panel.html:6460` | 否 | 普通 pull |
| `feed:main:read_at` | max（框架） | 前端 | 已读边界 | 否 | 普通 pull |
| `feed:search:<k>:anchor` | lww（框架） | 前端 | `panel.html:7861` | 否 | 普通 pull |
| `search:kw:<k>` | lww | `server.py:2616` | 融合流 | **是** | 重搜 done / `restoreSearch` |
| `search:kwlist` | lww | 前端 | 词清单 `6679` | 否 | 普通 pull |
| `search:filter` | lww | 前端 | 筛选 `6689` | 否 | 普通 pull |
| `search:presets` | lww | 前端 | 方案 `8044` | 否 | 普通 pull |
| `search:last` | lww（遗留） | 迁移 `7565` | 一次性 | 否 | 无需 |
| `bm:list` | lww | 前端 `3647` + **后端 `1773`** | 收藏页 | 否 | 普通 pull |
| `like:list` | lww | 前端 `3727` + **后端 `1793`** | 喜欢页 | 否 | 普通 pull |
| `history:list` | lww | 前端 `9008` | 历史页 | 否 | 普通 pull |
| `users:<uid>` | lww | `server.py:2805,3101` | `panel.html:8838` | 否 | 普通 pull |
| `user_id_of:<name>` | lww | 前端 `8809` | `panel.html:8826` | 否 | 普通 pull |
| `active_view` | lww | 前端 | `3326,3379` | 否 | 普通 pull |
| `cache` | 待确认 | 待确认 | 待确认 | **是** | **待确认 → 必须查清** |
| `x_br_anchor_v1` 等 6 个 | localStorage | 前端 | 本机 | — | 不同步 |

localStorage 6 个：`xd_job`、`xd_rk`（`1437-1438`）、`x_browse_mirror_v1`（`5184`）、`x_br_anchor_v1`（`5360`）、`x:tw:ts:v1`（`8471`）、`xsearch_rk`（`7777`）。

**验收**：清单里每一行都有 file:line 证据；`cache` 键的写者/读者查清并补上；**重键一栏与 `panel.html:1450-1456` 的 `setHeavyKeys` 列表逐一对应**。

#### 1.2 落地声明文件

**改什么**：新增 `extensions/x/ui/x_keys.js`（浏览器可直接 `<script>` 引入，node 可 `require`）：

```js
// 唯一声明处：键名、策略、是否重键、谁产出（'server' 表示后台任务产出，
// 意味着「本地要拿到它就必须显式取回」）。
const X_KEYS = {
  MAIN_ITEMS:   { k: 'feed:main:items',        strategy: 'union_by_id', heavy: true,  producer: 'server' },
  TWEETS_ITEMS: { k: 'feed:tweets:items',      strategy: 'union_by_id', heavy: true,  producer: 'server' },
  USER_TL:      { k: 'feed:user:',             strategy: 'union_by_id', heavy: true,  producer: 'server', prefix: true },
  SEARCH_KW:    { k: 'search:kw:',             strategy: 'lww',         heavy: true,  producer: 'server', prefix: true },
  // …其余按 1.1 清单补齐（非重键 producer='client'）
};
function xHeavyKeys() { /* 由 heavy:true 派生，替换 1450-1456 的硬编码数组 */ }
function xProducedKeys() { /* producer==='server' 且 heavy → 产出后必须取回 */ }
```

**改动点（全部是"收口"，不改行为）**：

| 位置 | 改成 |
|---|---|
| `panel.html:1450-1456` | `XSTATE.setHeavyKeys(xHeavyKeys())` |
| `panel.html:6679/6689/8044/8471/5184/5360/7777/1437-1438` | 引用 `X_KEYS.*`（或保留常量但值来自 `X_KEYS`） |
| `panel.html:6702 kwKey` 与 `server.py:2486-2498 _kw_key` | 见阶段 3.1（本阶段先只登记，不动算法） |
| `server.py` 各处字面量 | 后端也读同一份清单（导出 JSON 供 Python 读取，见阶段 2.1） |

**验收**：`panel.html` / `server.py` 里不再出现新的键字面量；行为完全不变（跑 `x_smoke` 全绿）。

#### 1.3 把"产出后取回"变成机制，而不是记性

**改什么**：在 SDK 侧加一个语义化封装（`src/extensions_host/static/state.js`，紧邻现有 `pullKeys`）：

```js
// 产出型键的取回：服务端后台任务完成后调用。缺省取回「producer==='server' 且 heavy」
// 的全部键；也可显式传 keys。
SDK.pullProduced = function (keys) { … SDK.pullKeys(keys || SDK.producedKeys) … };
```

同时给 SDK 增加 `SDK.setProducedKeys(list)`（与 `setHeavyKeys` 对称）。

**三个调用点统一改写成一次调用**：

| 位置 | 现在 | 改成 |
|---|---|---|
| `panel.html:7814-7830`（重搜 done） | `pull()` + `pullKeys(search:kw:*)` | `await XSTATE.pullProduced()` |
| `panel.html:7899-7920`（打开搜索页） | `pull()` + `pullKeys(各词)` | 保留 `pull()` + `pullProduced()` |
| `panel.html:8754-8760`（用户页） | `pull()` + `pullKeys(feed:user:<uid>)` | `pull()` + `pullProduced(['feed:user:'+uid])` |

**验收**：三处逻辑一致；新增一个产出型键时，**只需在 `x_keys.js` 加一行**，取回自动生效（并用单测证明：往 `producedKeys` 里加一个假键，`pullProduced` 确实把它取回）。

#### 1.4 守卫脚本（第一半）

**改什么**：新增 `scripts/x_guard.js`，实现三条检查：

1. **键漂移**：`panel.html`/`server.py` 中出现的键字面量 ⊆ `x_keys.js` 清单；框架侧 `state.js:423-430` 的拼装方式与清单一致。
2. **重键覆盖**：`setHeavyKeys` 的列表 == 清单里 `heavy:true` 的集合（防止两边改一处漏一处）。
3. **产出键必被取回**：`producer==='server' && heavy` 的键，代码里必须存在对应 `pullProduced`/`pullKeys` 调用点（grep 断言）。

**验收**：故意把 `heavyKeys` 里加一个不存在的键 → `x_guard` 报错退出码非 0；恢复 → 通过。

---

### 阶段 2：最小测试网

#### 2.1 契约测试（秒级，`scripts/x_guard.js` 第二半）

- **哈希一致**：`kwKey`（前端）与 `_kw_key`（后端）对同一批关键词结果一致。**前提**是阶段 3.1 把 `kwKey` 抽成独立文件 `extensions/x/ui/kwkey.js`，node 可直接 `require`；Python 侧断言自己的 `_kw_key` 与 `fixtures` 一致。
- **服务端真产出 ⊆ 注册表**：真打一次 `GET /api/user-state/x`（全量，不带 exclude），断言返回的键名都登记过——**这条能直接抓到"代码里用了一个没登记的键"**。
- **重键可真取回**：对每个重键，断言 `GET ?keys=<k>` 能返回它（服务端侧），且前端存在调用点（1.4 已覆盖）。

**验收**：`node scripts/x_guard.js` 在 3 秒内跑完，覆盖上述三条。

#### 2.2 黄金路径（分钟级，`scripts/x_smoke.js`）

用 0.2 的脚手架实现 5 条断言：

| 路径 | 断言 |
|---|---|
| 打开关注流（`#/home`） | 首屏内容出现；**锚点精确**（`aTop` 与保存值差 < 1px）；占位文案只在内容前出现 |
| 锚点定位 | 深锚点（保存 `-576` 级别）仍精确落位 |
| 重搜完成 | 触发后轮询到 done，**本地 `search:kw:*` 键数 == 关键词数**（本 session 回归的直接防线） |
| 新上下文搜索页 | 全新浏览器上下文打开 `#/search`：关键词缓存**从 0 变 N**（防"新设备为空"） |
| 用户页 | `feed:user:<uid>` 取回、卡片渲染出内容 |

**验收**：五条全绿；人为把某处 `pullKeys` 注释掉 → 对应用例失败（证明它真的在防）。

#### 2.3 接入方式

**改什么**：在 `README.md`/`docs/development/` 注明运行方式；可选加 `scripts/x_check.bat` 一键跑 `guard` + `smoke`。

**风险**：`x_smoke` 依赖本机真实服务（8080/5173/8093）+ 真实 X Cookie，属"开发机专用"；`x_guard` 无依赖，可进 CI。

---

### 阶段 3：消除重复实现

> 前提：阶段 2 的网已可用。每一步都先让 `x_smoke` 变绿作为基线，改完再跑。

#### 3.1 `kwKey` 单一实现（最高优先）

**改什么**：
1. 新建 `extensions/x/ui/kwkey.js`，内容 = 现在 `panel.html:6702 kwKey` 的实现（保持算法一字不改）；
2. `panel.html` 改为 `<script src="/ext-sdk/kwkey.js">`（或扩展静态资源路由，与 `panel.html` 同源加载）并删除内联实现；
3. Python 侧 `server.py:2486-2498 _kw_key` 保留（后端后台线程需要），但**接入契约测试**：`fixtures` 里 20 个代表性关键词（中文/emoji/长串/大写/空格）双方结果一致。

**验收**：`x_guard` 的哈希一致性检查通过；把 `kwkey.js` 里改一个字符 → `x_guard` 失败。

#### 3.2 推文内容定一个权威源

**改什么**：现状是 3 份（前端 `XTWEETS@5064`、后端 sqlite、后端后台写 `feed:tweets:items@server:2611`）+ localStorage 镜像 `5184`。

- 声明**服务端 `feed:tweets:items` 为权威**（它本就是 `union_by_id`）；
- `XTWEETS` 明确为**派生视图**（只读 + 本地镜像），`scrubTweetsCache@5082`/`tweetCachePutDetail@5152` 的启发式清洗逻辑标注为"派生层修复"并在文档写清触发条件（`panel.html:5060-5077` 自述此处历史分叉就是 bug 根因）；
- **不做**数据迁移，只加注释与边界声明 + 一条断言：`x_smoke` 里比较"卡片渲染条数 == 本地缓存条数（允许差 1 页）"。

**验收**：`x_smoke` 通过；`scrubTweetsCache` 的清理只在派生层发生（代码审查确认不写回服务端）。

#### 3.3 游标与锚点收敛

**改什么**：现状游标 5 套（`feed:main:cursor`、搜索 `cursorTop/cursorLatest`、`srchCursor@6674`、`brCursor@4023`、`userCursor@8778`），锚点 3 层（框架 `feed:*:anchor`、本地 `x_br_anchor_v1@5360`、搜索 `feed:search:<k>:anchor@7861`）。

- 抽一个 `Cursor` 小工具（大值前进 / 空值保持），5 处逐一替换，**行为逐字节对齐**（先用 `x_smoke` 固化行为再替换）；
- 锚点三层**合并不做**（跨设备语义不同，合并风险高），只在 `x_keys.js` 与文档里写明"三层各自用途"，消除"这是重复实现"的误判。

**验收**：`x_smoke` 全绿；`brCursor`/`srchCursor` 的赋值点从 N 处降到 1 处。

---

### 阶段 4：在 `panel.html` 开缝

> 原则：**只搬移 + 只冻结，不改逻辑**。每条缝做完即提交、跑 `x_smoke`。顺序按"收益/风险"排。

#### 4.1 状态门面（收益最大，先行）

**问题**：≈116 个模块级可变变量，任何函数都能直接改。
**改什么**：
1. 建立 `XStore`（或复用 `XSTATE` 包装）作为唯一访问口：命名的 getter/setter，禁止业务代码直接碰裸变量；
2. 把**常量**（`VIEW_ROUTES@3033`、`KW_LIST_KEY@6679` 等）`Object.freeze`，消灭"别人把它改了"的可能；
3. 逐个把高频可变变量（`_rows@4156`、`_browseItems@4157`、`_dayCounts@4164`、`_rowByKey@4167`、`brDayIndex@6322`、`srchKwList@6682`、`srchAllItems@6677`）改成经 `XStore` 访问；**先不改名**，降低 diff 噪音。

**验收**：`x_smoke` 全绿；`grep -c "^  let \|^  var "` 数量下降；新增一个断言脚本（`x_guard` 第 4 条）：禁止在 `XStore` 定义之外赋值这些变量。

#### 4.2 feed + 锚点引擎

**问题**：定位/锚点逻辑散在 `pickAnchor@5391`、`anchorTo@5449`、`BR_ANCHOR_KEY@5360`、`saveSearchPos@7861` 等多处，且与渲染纠缠。
**改什么**：把这组函数归拢到一个区块（`// ===== feed engine =====` 包裹），对外只暴露 `feedEngine.open/restore/save`；`renderRowsDOM@4439` 只消费它的输出。

**验收**：`x_smoke` 的"锚点精确"两条用例通过（这是最有价值的回归网）；该区块对外引用数下降。

#### 4.3 视图 / 路由

**问题**：`switchView@3221` + `VIEW_ROUTES@3033` + `bootRoute@3337` 三者缠在一起，路由恢复还依赖 `active_view` 键。
**改什么**：收敛为"路由表 → 视图"单向；`bootRoute` 只做一次解析，`switchView` 只做切换；订阅点集中。

**验收**：`x_smoke` 的"打开关注流/搜索页/用户页"三条通过；URL 同步回归（本次 session 已有可复用的验证脚本模式）。

#### 4.4 搜索存储

**问题**：`loadKwCache@7509`、`rebuildMerged`、`renderSrchProduct`、`srchKwList@6682`、`srchAllItems@6677` 交织，且直接依赖重键取回时序（本次回归就死在这里）。
**改什么**：抽 `SearchStore`：`keywords() / load(k) / merge() / onProduced()`，把"产出后取回"收敛为 `onProduced()` 一处。

**验收**：`x_smoke` 的"重搜完成"与"新上下文搜索页"两条通过。

---

### 阶段 5：修方向性依赖

**问题**：`server.py:2512 _bg_state_put` 让后台线程**调自己的 HTTP API** 写状态（鉴权/超时脆弱）；且后端 `1773/1793` 与前端 `3647/3727` 同时写 `bm:list`/`like:list`。

**改什么**：
1. `_bg_state_put` 改为**进程内直调**状态服务（与 `host.state.put` 同路径），去掉 HTTP 自调用；
2. `bm:list`/`like:list` 定为**前端追加 + 后端合并**的单一语义，并在 `x_keys.js` 注明 `writers: ['client','server']`，避免两边用不同策略互相覆盖（本次已见 `_merge_membership` 与前端 `uni` 合并两套）。

**验收**：`x_guard` 断言"`writers` 含 server 的键，其策略在后端与前端声明一致"；`x_smoke` 收藏/喜欢两条通过。

---

### 阶段 6：防复发

**改什么**：
1. `x_guard` 进 CI（`tests/` 已有 pytest，可加一个 `test_x_contracts.py` 调 python 侧检查）；
2. 在 `docs/development/commit-convention.md` 补一条：**涉及持久化键或前后端契约的改动，必须跑 `x_guard` 并在提交信息里贴结果**；
3. 把本档的"键注册表"设为**唯一权威**，新增键必须先登记。

**验收**：一次真实改动走完整流程，`x_guard` 拦下（或通过）的证据留在提交信息里。

---

## 4. 风险与回滚

| 阶段 | 主要风险 | 回滚 |
|---|---|---|
| 1 | 收口时误改键名 → 状态串台 | 纯字面量替换，`git revert` 即可；先跑 `x_smoke` 基线 |
| 2 | `x_smoke` 依赖真实服务/Cookie，易假红 | 断言只取"内容出现 + 键数"这类粗粒度信号，失败信息打印请求时序 |
| 3.1 | 抽 `kwkey.js` 改动加载方式 → 面板起不来 | 保留内联副本一个提交周期，两者都跑一致性测试后再删内联 |
| 3.2 | 权威源声明与既有清洗逻辑冲突 | 只加声明不改行为；清洗逻辑留在派生层 |
| 4 | 大范围搬移引入回归 | 每缝一次提交；名字先不改；随时 `git revert` 单缝 |
| 5 | 后台写状态路径变更 | 先加开关（新旧并存一个周期），对比两者写入结果一致后切换 |

**通用保险**：每条缝/每步之后都必须跑 `x_smoke`；任何一步不能让 `x_smoke` 变红。

---

## 5. 进度跟踪

| 步骤 | 状态 | 提交 | 备注 |
|---|---|---|---|
| 0.1 验证规范 | 待办 | | |
| 0.2 e2e 脚手架 | 待办 | | 本次 session 已有可用原型可复用 |
| 1.1 键清单 | 待办 | | 草稿见 1.1，`cache` 键待查 |
| 1.2 `x_keys.js` | 待办 | | |
| 1.3 `pullProduced` 机制 | 待办 | | `pullKeys` 已在 `f743caa` 落地，可直接包 |
| 1.4 guard（键部分） | 待办 | | |
| 2.1 契约测试 | 待办 | | |
| 2.2 黄金路径 | 待办 | | 5 条 |
| 2.3 接入方式 | 待办 | | |
| 3.1 `kwKey` 单一源 | 待办 | | **优先** |
| 3.2 推文权威源 | 待办 | | |
| 3.3 游标收敛 | 待办 | | |
| 4.1 状态门面 | 待办 | | |
| 4.2 feed/锚点 | 待办 | | |
| 4.3 视图/路由 | 待办 | | |
| 4.4 搜索存储 | 待办 | | |
| 5 方向性依赖 | 待办 | | |
| 6 防复发 | 待办 | | |

---

## 附录 A：本计划的立足事实（避免重复考古）

- 本次 session 的性能工作链：`2571ms → 369ms`（首屏内容）→ 服务端取内容再降到几十毫秒；提交 `12cd43e`、`c4d851a`、`67e6946`、`f94ccca`、`c0c71c8`、`d483240`、`9e64f8c`、`f7e33f1`、`f743caa`、`789490b`。
- `heavyKeys` 机制：后端 `merge_read(exclude_keys=)`、SDK `setHeavyKeys/pullKeys`、插件 `setHeavyKeys` 三处；**它就是阶段 1 要"收口"的第一号对象**。
- 本机 dev 环境：`8080 ← python src/web/main.py`（系统 Python）、`8093 ← 扩展宿主`、`5173 ← vite`（HMR）；改 `extensions/` 下文件触发宿主热重载。
