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
| 0.1 验证规范 | ✅ 完成 | 主仓 `f10065b` | `docs/development/x-verification-rules.md`：两条铁律（串行/并发分别测、热重载窗口不算数）+ 两个网的使用时机 + 写断言的三条经验 |
| 0.2 e2e 脚手架 | ✅ 完成 | 主仓 `af90e73` | `scripts/x_e2e_lib.js` |
| 1.1 键清单 | ✅ 完成 | 主仓 `ba1e67b` | 20 键 + 6 localStorage；**`cache` 已查清＝无任何读写方的遗留死数据**（仅作视图名与 SQLite 文件名出现）；**新发现 `feed:stars:items` 此前未登记**（后端用变量 `key` 间接引用，人工清点必漏，靠守卫扫描才抓到） |
| 1.2 键声明表 | ✅ 完成 | 主仓 `ba1e67b` / X 仓 `2b3caa1` | **落地形式有调整**：未新建 `ui/x_keys.js` 运行时文件（避免新增资源路由与加载风险），改为 `extensions/x/x_keys.json` + panel.html 内联块，由守卫保证两者一致、`--fix` 自动同步（行尾不敏感） |
| 1.3 `pullProduced` 机制 | ✅ 完成 | 主仓 `ba1e67b` / X 仓 `2b3caa1` | `setProducedKeys`/`pullProduced` 落地；三处调用点（重搜 done / 打开搜索页 / 用户页）已改用；`producedKeys` 由注册表派生 |
| 1.4 guard（键部分） | ✅ 完成 | 主仓 `ba1e67b` | `scripts/x_guard.js` 五项检查（A 内联一致 / B 字面量登记 / C 派生非硬编码 / D 产出键必有取回点 / E localStorage）；**突变测试验证**：移除用户页取回 → D 立即报 `feed:user:*` 并退出码 1 |
| 2.1 契约测试 | ✅ 完成 | 主仓 `65f80b9` | 守卫补 F/G/H 三项：F 哈希契约（把前端 `kwKey` 与后端 `_kw_key` 抽出来喂同一批 fixture **真跑**比对）、G writers 声明与代码写点一致、H 服务端真产出 ⊆ 注册表 + 重键定向可取回（需本机 dev 服务，不可达自动跳过，`--offline` 强制跳过）。首跑即抓出 1 处真 bug + 6 个未登记键 |
| 2.2 黄金路径 | ✅ 完成（两处测法缺陷已修） | 主仓 `af90e73` / `b7f69fd` / `38ba5d3` | 五条用例齐。修掉两处「有网却不出结果」的测法缺陷：① **锚点用例此前一直 skip**——根因是滚动方式判断反了（desktop 上下文下滚轮作用不到面板，默认移动视口才会滚），且用固定 sleep 会撞上加载期的「锚点冻结窗口」；改为在主上下文滚动、并**滚到产品真的记下锚点为止**，用例既真跑又稳定（实测差 0.00~1.00px）。② 产出键取回用例偶发假红：面板自身会回写 `feed:tweets:items`，而 `pullKeys` 的合并写入会跳过仍处于「待推送」状态的键——测前先 `push()` flush 再取、并允许重试。另补内容卡非空壳断言。**留白**：用户页用例仍未覆盖（hash 路由格式未定），已在文件头声明 |
| 2.3 接入方式 | ✅ 完成 | 主仓 `f10065b` | `scripts/x_check.bat`（一键守卫+冒烟）+ `scripts/README.md` 写明依赖与用法；README 文档索引已补入口 |
| 3.1 `kwKey` 单一源 | ✅ 完成（形式调整） | 主仓 `65f80b9` / X 仓 `d411864` | 沿用 1.2 的落地形式（不新增运行时资源文件），改为守卫 F 对两侧实现真跑比对；**并因此抓到真 bug**：emoji 处前后端哈希分叉（前端按 UTF-16 代码单元、后端按 Unicode 码位）→ 后端已改为按代码单元遍历。实证：修前 2/20 例不一致，修后 20/20 一致 |
| 3.2 推文权威源 | ✅ 完成（并**实测出遗留缺口**） | X 仓 `a0737f8` / 主仓 `b7f69fd`、`38ba5d3` | 声明 `feed:tweets:items` 为内容权威源（登记表 + 面板代码块）；写清三份存储的边界（另有 `search:kw:<hash>`＝每词分页快照、服务端 `ns='search'` sqlite＝HTTP 响应级缓存）；面板侧仅留两处受控写入，各自标注「派生层修复/补全」并写明触发条件与红线；冒烟新增断言并**量出缺口**：**关注流的内容走服务端按天缓存 `feed:main:<day>`（`/timeline?date=`），渲染时直接消费、不经过 XTWEETS**——实测打开关注流后 660 张内容卡只有 ~19 张能在 XTWEETS 查到。也就是说「唯一内容源」目前只对搜索/收藏/详情/用户页成立，关注流是第二条载体；收敛属 4.2/4.4（已在登记表与面板代码块标注，避免被当成已解决） |
| 3.3 游标收敛 | ✅ 完成（结论：**不做合并**） | X 仓 `a0737f8` | 甄别：全仓 5 处「游标」里 4 处是各视图持有的**不透明服务端令牌**，用法一律 `= d.next_cursor \|\| null` 原样赋值，没有可收敛的算法——强行抽成「大值前进/空值保持」的 helper 反而会改语义。真正「只前进」只有 `feed:main:cursor` 一处，由 state 层 `strategy=max` 承担。锚点三层合并风险高于收益，改为把各自用途写进登记表消除「重复实现」误判 |
| 4.1 状态门面 | 待办 | | 见下方「为什么 4.x 留到下一轮」 |
| 4.2 feed/锚点 | 待办 | | 同上；不过 4.2 的前提（锚点用例真能跑）本轮已具备 |
| 4.3 视图/路由 | 待办 | | 同上 |
| 4.4 搜索存储 | 待办 | | 同上 |
| 5 方向性依赖 | ✅ 完成 | 主仓 `5b9d7ef` / X 仓 `ca8ddec` | `_bg_state_put/_get` 不再自建 HTTP：宿主 SDK 的 `host.state.get/put` 支持显式 `auth/device`（有请求上下文就取请求头），插件走同一入口，SDK 过旧时回退旧实现；`bm:list`/`like:list` 的 `writers` 声明本就在登记表，本轮把「声明 vs 代码写点」的断言补进守卫（G），并据此修正 `feed:stars:items` 的错误声明 |
| 6 防复发 | ✅ 完成 | 主仓 `f10065b` / `d3bb521` | `tests/test_x_contracts.py`（纯 Python，5 项）+ CI 接入（backend job 增 Node，跑 `node scripts/x_guard.js --offline`）+ `commit-convention.md` 第 7 节：涉及持久化键/前后端契约的改动必须跑守卫并在提交信息里贴结果 |

### 为什么 4.x 留到下一轮（不假装完成）

4.1~4.4 是「在 9300 行的 `panel.html` 里开缝」：搬移 ≈116 个模块级可变变量、把锚点/渲染
解耦、重排视图与路由、抽 `SearchStore`。计划自己定的纪律是**每条缝做完即提交并跑 `x_smoke`**，
而这一步的收益/风险比取决于「网到底可不可信」——本轮的主要收获恰好是把这条前提补齐：

- 锚点用例（4.2 验收所依赖的那条）此前一直 skip，本轮才第一次真正跑起来并通过；
- 「内容唯一权威源」断言（3.2 验收所依赖）本轮才加上。

也就是说：**网的可用性这一轮才达标**。在这个点上立刻开始大范围搬移，等于在刚通电的
网下做高空作业——本轮的选择是先把网做可信、把边界写死（3.1/3.2/3.3/5/6），
4.x 按「一次一条缝、每条缝跑一次冒烟」的节奏单独排一轮。

---

## 附录 B：全仓排查「绕开已有数据、重新抓取/重算」的结果（2026-09-26）

起因：下载器修好一例（媒体元数据绕开缓存，提交 `c20fdc1`）后，系统性排查同类。按影响排序：

| # | 位置 | 问题 | 可用什么 | 等级 | 性质 |
|---|---|---|---|---|---|
| 1 | `run.py:3368 download_video` + `run.py:3299 download_fmp4_stream` | 视频路径**无任何本地字节复用**（对比 `download_image` 有 `_cache_hit_path`，`run.py:3201`） | 同款 `_cache_hit_path` + `_CACHE_LRU_DIR` | 中 | 与已修例同源（媒体字节轴） |
| 2 | `run.py:3444 download_document` | 文档附件不查缓存 | 同上 | 低 | 浪费 |
| 3 | `panel.html:3874/3963` 书签/喜欢 | 缓存优先判定**只看成员表** `bm:list`/`like:list`；成员表缺失但 `XTWEETS` 已有内容时仍走网络分支 | 加一层 XTWEETS 判定 | 中 | 绕开已有数据 |
| 4 | `server.py:3108 /me` | 每次联网打 X，却不读自己刚写入的 `users:<rest_id>`（3128） | `host.state.get('users:<rest_id>')` | 低-中 | 浪费 |
| 5 | `search:kw:*` / `feed:tweets:items` / server sqlite `ns='search'` | 同一条推文**存 3 份**，三处都写 | 归入阶段 3.2 定权威源 | 中 | 重复缓存 |
| 6 | `toMembership`(panel:5437)↔`_membership`(server:1705)；`mergeTweet`(panel:5234)↔`_merge_tweet`(server:2527)；`_iso_order`(server:1585)↔ panel 用 `timeline_at`(5476/5285)；媒体 shape(run.py:1961 ↔ panel 缓存) | 前后端**重复归一化**（kwKey 之外还有 4 处） | 归入阶段 3.1/3.2 | 中 | 漂移风险 |

**"有标记但不被信任"的甄别**：`_force_arg`（`server.py:163/2314`）**正确区分**了用户刷新与首次进入 ✓；`/media?force=1`、`openTweetDetail` 补全属**有意** ✓。**嫌疑**：`panel.html:1815 acquireMaster`（由 `loadBrowse:6713` 调用）每次进入关注流都强制对账 pull（注释称"刻意使用本设备"，但与用户刷新未在同一入口区分）——**属推测，待证**。

**第 1 项的前置验证（未完成，勿直接动手）**：按 `server.py:3198` 注释，媒体缓存按 **md5(原始 URL)** 落盘。实测该视频直链 md5=`275d556395cb62170b78caf843378cd6`，在 `data\plugins\x\media_cache\lru` 与 `data\plugins\x-downloader\media_cache\lru` **均无匹配**，且这两个目录**文件数为 0**；但 `data\plugins\x\cache\media` 尚未检查 → **结论未定**。动手前必须先确认：① 真实媒体缓存目录与命名约定；② 预览是否根本不缓存视频字节（若是，则第 1 项应改为"让预览也缓存视频字节"，而不是"下载时复用"）。

## 附录 B-2：上述各项的处置结果（2026-09-26 第二轮）

| # | 结论 | 证据 / 落点 |
|---|---|---|
| 1 | ✅ 已修（并补齐「两形态都查」） | **前置验证先做完**：① 真实缓存目录与命名约定＝`<data>/plugins/<插件>/cache/media/<md5(原始URL)><ext>`（`server.py` 的 `host.cache('media', key_hash='md5')`；本轮误查的 `media_cache/lru` 是空的遗留目录，开发机 `data/plugins/x/cache/media` 里只有 `.cache_index.json`，因为**开发机缓存是空的**，生产机（ProgramData 下同路径）才有 118 个 `.mp4`、最大 168MB）；② 预览**确实会**缓存视频整套字节（按用户请求的那个 URL 落盘，mp4 直链形态），所以第 1 项就是「下载时复用」，不需改成「让预览也缓存」。落点：X 仓 `e593636`（视频按 m3u8 / mp4 两种键一起查、缓存键归一化与 `/media` 对齐、下载地址为空时退回 mp4）+ 文档 —— 原 `ed3fc71` 只查一种键，在 url 填 m3u8 的来源上永远查不中 |
| 2 | ✅ 已修 | 同提交 `e593636`：文档附件补上同款「缓存即下载」（此前完全没查）。实测：伪造缓存分区后视频/文档/直链三条入口均本地复制、不出网 |
| 3 | ❌ **前提不成立，不做** | XTWEETS 里的推文记录**没有任何成员标记**（`mergeTweet` 只补 `tweet_id`；服务端 `_merge_tweet` 同样只归一 id），所以「成员表缺失但 XTWEETS 有内容」时**无法判断哪些缓存是书签**，判定逻辑不可能靠 XTWEETS 补一层。且此时走网络分支是**必须**的、代价也已很小：`GET /bookmarks` 在后端就是缓存优先（`_cached('list','bookmarks',…)`，未过期/非 force 不打 X），面板侧也已「翻到整页都是已知内容就停」。结论：此项作废，避免后续再照着做一遍无用功 |
| 4 | ✅ 已修 | X 仓 `abc571e`：`/me` 先读自己写的 `users:<rest_id>`（跨设备 UserState 键），命中即返回；`force=1`（用户在资料卡点刷新）才回源，且前端把 force 透传下去。字段抽成 `_ME_FIELDS` 保证两条返回路径形状一致 |
| 5 | ✅ 归入 3.2，边界已定并**量出遗留缺口** | 见进度表 3.2：`feed:tweets:items`（内容）／`search:kw:<hash>`（每词分页快照）／服务端 `ns='search'` sqlite（HTTP 响应级缓存，不是内容存储）三者层次已写进登记表与代码块。同时实测确认「关注流渲染直接消费服务端按天缓存 `feed:main:<day>`，不进 XTWEETS」（660 张内容卡仅 ~19 张命中 XTWEETS）——本项并非「三份都写同一内容」，而是「两条渲染路径各取一份」，收敛与 4.2/4.4 合并处理 |
| 6 | ✅ 归入 3.1/3.2 | `kwKey ↔ _kw_key` 已由守卫 F 真跑比对（并修掉 emoji 分叉）；其余 `toMembership/_membership`、`mergeTweet/_merge_tweet`、`_iso_order` vs `timeline_at` 属「成员表/内容归一化」两侧各一份，本轮先把**内容权威源**与其边界写死（3.2），剩余三处的收敛依赖 4.x 开缝，已在 3.2 的登记表里点名，避免再现误判 |

**「有标记但不被信任」的甄别结果**：
- `_force_arg`（用户刷新 vs 首次进入）、`/media?force=1`、`openTweetDetail` 补全 —— 维持「有意且正确」。
- `panel.html:1815 acquireMaster` —— **甄别为有意且正确，不改**。证据：① 全仓只有一个调用点
  （`switchView('browse')` → `openBrowse()` → `loadBrowse(true)`），翻页/滚动路径
  （`loadBrowse(false)`）不经过它，**没有绑在 scroll 上**；② 它内含的「强制对账 pull」是 SDK
  文档写明的接管前置条件（先 pull 拉下服务端真相再写租约，否则本机陈旧快照会覆盖另一台设备
  刚同步的位置——那是有记录的事故形态），也就是「刻意使用本机」的定义本身；
  ③ 「与用户刷新未区分」不成立：内容是否重爬是 `force` 这条轴，主控接管是另一条轴，
  两者本就不该共用一个入口。代价是一次 pull+push（重键已排除），换取跨设备续读的正确性，值得。
  （本条为代码级甄别，未做运行时计数对比。）

---

## 附录 A：本计划的立足事实（避免重复考古）

- 本次 session 的性能工作链：`2571ms → 369ms`（首屏内容）→ 服务端取内容再降到几十毫秒；提交 `12cd43e`、`c4d851a`、`67e6946`、`f94ccca`、`c0c71c8`、`d483240`、`9e64f8c`、`f7e33f1`、`f743caa`、`789490b`。
- `heavyKeys` 机制：后端 `merge_read(exclude_keys=)`、SDK `setHeavyKeys/pullKeys`、插件 `setHeavyKeys` 三处；**它就是阶段 1 要"收口"的第一号对象**。
- 本机 dev 环境：`8080 ← python src/web/main.py`（系统 Python）、`8093 ← 扩展宿主`、`5173 ← vite`（HMR）；改 `extensions/` 下文件触发宿主热重载。
- **状态服务与插件不在同一进程**：UserState 归主服务（8080），插件后端跑在扩展宿主（8093）里，
  所以阶段 5 所说「改为进程内直调、去掉 HTTP 自调用」**不可能字面实现**——跨进程这一跳去不掉。
  能去掉的是**插件自己再手写一遍 HTTP 与鉴权头**（那条才是真正会分叉的第二实现）。故阶段 5 的
  落地形式是：把「身份从哪来」收进宿主 SDK 的 `host.state`（支持显式 `auth/device`），插件只调它。
- 重启命令（NSSM，服务键见 `scripts/service_manager.py` 的 `SERVICES`）：
  `python scripts/service_manager.py restart web`（主应用 API，8080）、`restart extensions`
  （扩展宿主，8093——**改了 `src/extensions_host/*` 必须重启它才会生效**）、`restart thumbnail`、
  `restart webui`（Vite，5173）。
