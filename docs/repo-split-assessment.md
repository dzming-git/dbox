# dbox 微服务拆分独立 Git 仓库：价值评估与组织方案

> 评估日期：2026-09-01
> 评估对象：`c:\Users\<用户>\<工作目录>\Claw\dbox`
> 结论先行：**不建议按服务边界全量拆分**；建议维持「核心 monorepo + 插件独立仓」的现状，并把共享库显式化为内部 SDK。若确需拆分，应按「变更频率」而非「服务数量」切分，目标 3~4 个仓库而非 15 个。

---

## 一、现状盘点

### 1.1 运行中的服务（15 个 Windows 服务，均 Automatic/Running）

| 服务名 | 对应代码 | 规模 |
|---|---|---|
| dbox-bus | src/servicebus | 9 py |
| dbox-collectiond | src/collection | 4 py |
| dbox-downloader | src/downloader | 1 py |
| dbox-extensions | src/extensions_host | 11 py + 1 js |
| dbox-historyd | src/history | 4 py |
| dbox-resource | src/resource | 6 py |
| dbox-scheduler | scripts/poll_scheduler.py | — |
| dbox-searchd | src/search | 4 py |
| dbox-servicemgr | src/servicebus/service_mgr_adapter.py | — |
| dbox-systemd | src/system | 4 py |
| dbox-thumbnail | src/thumbnail | 2 py |
| dbox-userd | src/user | 4 py |
| dbox-watchdog | src/servicebus/watchdog_adapter.py | — |
| dbox-web | src/web（8080） | **61 py** |
| dbox-webui | src/webui（5173） | **95 js/ts/vue** |

### 1.2 架构形态：已是标准微服务

各业务服务呈现高度一致的结构（`main.py` + `bus_adapter.py` + `models.py`），且为独立进程：

```python
# src/collection/main.py
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)          # ← 靠 sys.path 注入共享库

from servicebus.service_base import DEFAULT_HOST, DEFAULT_RPC_PORT, DEFAULT_PUB_PORT
```

- **进程隔离**：每个服务 `python src/<svc>/main.py` 独立启动
- **总线通信**：BusRouter 15555(RPC) / 15556(PUB)，服务间不直接 import
- **独立数据模型**：各有 `models.py`

### 1.3 共享库与耦合度（关键数据）

共享库：`servicebus`、`shared`（credential_vault / jwt_util / manifest / unified_tasks）、`liblog`

**引用统计：44 处**，分布如下：

- 各微服务入口与适配器：约 12 处
- **web 后端：20+ 处**（`api/*.py`、`*_helpers.py`、`auth_service.py` 等深度依赖）
- servicebus / liblog 自身：6 处

即：**服务间通过总线解耦，但对共享库是强源码依赖**，且 web 后端是最大依赖方。

### 1.4 现有仓库分布

```
dbox/.git                    ← 主仓（含上述全部核心代码）
dbox/extensions/codebuddy/.git  ← 独立插件仓
dbox/extensions/ehentai/.git
dbox/extensions/git-manager/.git
dbox/extensions/pixiv/.git
dbox/extensions/x/.git
```

插件已按「独立演进单元」拆出，这是**合理的既有先例**。

---

## 二、价值评估

### 2.1 支持拆分的因素

| 因素 | 说明 |
|---|---|
| 服务边界清晰 | 每个服务有明确 `main/adapter/models`，天然可独立成仓 |
| 运行时解耦 | 已进程隔离 + 总线通信，无跨服务直接调用 |
| 先例可循 | 插件独立仓已跑通，证明模式可行 |
| 独立版本化 | 各服务可独立打 tag、独立回滚 |
| 权限隔离 | 若未来有多人协作，可按仓授权 |

### 2.2 反对拆分的因素（权重更高）

| 因素 | 说明 | 影响 |
|---|---|---|
| **共享库强耦合** | 44 处引用，且 web 后端深度依赖；当前靠 `sys.path` 注入，拆仓后必须改为包依赖 | 高 |
| **单体规模极小** | 15 个服务里 12 个只有 1~6 个 py 文件，独立成仓收益 < 子模块/版本管理成本 | 高 |
| **跨仓改动频繁** | 本次会话一天内就同时改了框架 `state.js`、插件 `panel.html`/`run.py`、宿主 Vue 组件——跨仓会显著增加提交与联调成本 | 高 |
| **协作规模不匹配** | 当前单人开发，仓库数量带来的协作收益≈0，但管理成本线性增长 | 中 |
| **构建/部署耦合** | 15 个服务共用 `venv`、`requirements.txt`、NSSM 安装脚本；拆仓后依赖同步易漂移 | 中 |

### 2.3 量化对比

| 方案 | 仓库数 | 预估收益 | 预估成本 |
|---|---|---|---|
| 全量按服务拆分 | 15+ | 低（多数服务 1~6 文件） | **极高**（15 套 CI、15 份依赖、跨仓重构痛苦） |
| 按变更频率拆（推荐） | 3~4 | 中高（隔离改动最频繁的 WebUI） | 中（可控） |
| 维持现状 + 显式化 SDK | 1 + N 插件 | 中（已享受插件独立性） | **最低** |

**核心判断**：耦合的关键不在「服务之间」（已解耦），而在「服务与共享库之间」（强耦合）。按服务边界拆仓库并不能消除真正的耦合，只是把耦合从「同仓内编译期」转移成「跨仓版本依赖」——成本更高、反馈更慢。

---

## 三、推荐方案（结论）

### 方案 A（推荐）：维持 monorepo 核心 + 插件独立仓

1. **核心保持单仓**（web / webui / 各微服务 / servicebus / shared / liblog / extensions_host）。
   - 理由：它们共享同一套依赖、同一次发布节奏，且改动常跨越边界。
2. **插件维持独立仓**（现状），因为插件具备真正的独立演进单元特征：
   - 有独立 manifest、独立后端、独立 UI
   - 可单独安装/卸载
   - 已配置独立 remote（`dbox-ext-<id>`）
3. **把共享库显式化为「内部 SDK」**（这是本方案的关键增量）：
   - 明确 `src/shared`、`src/liblog`、`src/servicebus` 为公共 API，其他模块只能通过它们暴露的接口访问
   - 在 `src/shared/README.md` 写明边界与兼容策略
   - 对 `servicebus` 的协议（`protocol.py`）变更要求向后兼容（服务是独立进程，滚动升级时新旧版本会短暂共存）

### 方案 B（若确需拆分）：按变更频率切 3~4 个仓

```
dbox-core/        ← src/web + src/{collection,downloader,history,search,system,user,resource,thumbnail}
                     + src/{servicebus,shared,liblog} + scripts + configs
dbox-webui/       ← src/webui（前端，改动最频繁、独立构建）
dbox-ext-host/    ← src/extensions_host（框架侧，需与前端面板联调，可暂留 core）
extensions/*/     ← 各插件独立仓（维持现状）
```

- **不要**把 15 个服务拆成 15 个仓：多数服务只有 1~6 个文件，收益为负。
- `webui` 是最值得先独立的一块：改动频率高、构建链路独立（npm/vite）、与后端仅通过 HTTP 契约耦合。

---

## 四、若执行拆分：组织与治理方案

### 4.1 共享库处置（决定成败）

三种方式，按推荐度排序：

1. **发布为内部 pip 包（推荐）**
   - 将 `servicebus` / `shared` / `liblog` 抽出为 `dbox-sdk` 包，带独立版本号
   - 各服务仓 `requirements.txt` 中固定版本：`dbox-sdk==1.4.0`
   - 本地开发用 `pip install -e ../dbox-sdk`
   - 优点：依赖明确、可锁定；缺点：sdk 改动需发版，联调略慢

2. **Git Submodule**
   - 各仓以 `libs/dbox-sdk` 子模块引入
   - 优点：改动即时可见；缺点：子模块易处于 detached HEAD，新人极易踩坑

3. **聚合仓（meta repo）+ 稀疏检出**
   - 一个 meta 仓用 submodule 聚合全部；开发用 `sparse-checkout` 只拉需要的部分
   - 适合仓库很多时，当前规模不必

### 4.2 目录与命名规范

- 仓库命名统一前缀：`dbox-core`、`dbox-webui`、`dbox-ext-host`、`dbox-ext-<id>`
- 每个仓根目录须有：`README.md`（职责、启动方式、依赖）、`VERSION`、`requirements.txt`（或 `package.json`）
- 插件仓维持现有 `manifest.json` 声明式契约（零入侵红线不变）

### 4.3 版本与分支

- 主分支统一 `master`（插件仓现状；x 仓另有 `main`，建议统一为 `master` 避免混淆）
- 语义化版本：`MAJOR`（协议不兼容）/ `MINOR`（新增）/ `PATCH`（修复）
- `servicebus` 的 `protocol.py` 属 **MAJOR 敏感**：总线协议变更需全服务同步升级，必须走 MAJOR 并在部署脚本里强制版本校验

### 4.4 提交与协作约定

沿用现有红线并补充：
- 清理临时文件 → `git add <具体文件>`（不用 `-A`）→ 中文 UTF-8 提交信息 → 默认不 push
- **跨仓改动**：提交信息用统一前缀标记（如 `[bus-protocol]`），便于追溯同一次变更涉及的多个仓
- 一次逻辑变更若跨多仓，必须在描述中列出全部相关提交号

### 4.5 CI/CD 与部署

- 当前部署依赖 NSSM + 共享 `venv` + `scripts/install.py`
- 拆分后每个仓需能独立产出可部署物；建议：
  - 各仓产出到统一的 `dist/` 或版本号目录
  - `scripts/install.py` 改为从各仓产物装配，而非从源码树直接取
  - 保留一键全量构建脚本（meta 仓或独立 `dbox-deploy` 仓）

### 4.6 迁移路径（若选方案 B）

1. 先抽 `dbox-sdk`（不动调用方，仅把目录移出并以 pip 包形式装回），验证 44 处引用全部走包导入
2. 再拆 `dbox-webui`（纯前端，风险最低，可独立构建验证）
3. 最后视情况拆 `dbox-ext-host`
4. 每一步都保持 15 个 NSSM 服务可从新结构正常启动
5. 全程保留主仓历史：用 `git filter-repo`/`git subtree split` 保留文件历史，避免丢 blame

---

## 五、决策检查表

在决定拆分前，请确认以下问题的答案：

- [ ] 是否有**多人/多团队**协作，且不同人负责不同服务？（若否，拆分收益大幅降低）
- [ ] 各服务是否**独立发布**？（当前 15 个服务共享 venv 与安装脚本，实为整体发布 → 倾向不拆）
- [ ] 能否接受共享库改动需要**发版 + 更新各仓依赖**？（44 处引用的现实成本）
- [ ] 是否有 CI 能支撑多仓构建与版本校验？（当前未见 CI 配置）

**若上述多数为「否」，建议采用方案 A**：维持 monorepo，把精力投入到「共享库边界显式化」与「总线协议兼容性治理」上——这两项才是当前架构真正的风险点，且成本远低于拆仓。

---

## 附录：本次评估的实测数据来源

- 服务清单：`Get-Service | Where-Object { $_.Name -like "*dbox*" }` → 15 个服务
- 仓库分布：`Get-ChildItem -Recurse -Directory -Filter ".git"` → 主仓 1 + 插件仓 5
- 代码规模：按目录统计 `*.py` 与 `*.js/ts/vue` 数量
- 耦合度：`^\s*(from|import)\s+(servicebus|shared|liblog)\b` → 44 处匹配
- 架构形态：`src/collection/main.py` 的启动方式与端口（15555/15556）
