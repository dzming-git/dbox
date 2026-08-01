# DPlayer 架构约定

本文档记录项目在多次重构后沉淀的架构约定，供后续维护者遵循，防止架构债回潮。

## 1. 后端运行时依赖注入（runtime 单例）

历史问题：后端 `backend/*_helpers.py` 一度通过 `import main as runtime` 在运行时读取
`app_config`、`db`、`bus` 等，导致 helper 强耦合入口模块、无法独立测试。

现状：所有运行时资源通过 `backend.runtime` 的单例 `runtime` 注入。

- `backend/runtime.py` 定义 `_Runtime` 与全局实例 `runtime`，字段包括
  `db / app / app_config / thumbnail_bus / resource_bus / svc_mgr_bus /
  history_bus / collection_bus / search_bus`。
- helper 模块在**文件顶部** `from backend.runtime import runtime`，运行时通过
  `runtime.app_config`、`runtime.db` 读取，不再 `import main`。
- `main.py` 在初始化完成后调用 `runtime.init(...)` 注入上述字段。

**约定**：新增 helper 模块严禁 `import main`，一律从 `backend.runtime` 取运行时资源。

## 2. 蓝图注册集中化

`main.py` 的 `app.register_blueprint(...)` 调用已全部收敛到 `backend/blueprints.py`：

- `register_core_blueprints(app)`：注册在 main 初始化后即可安全导入的蓝图。
- `register_domain_blueprints(app)`：注册从 main 拆出的领域蓝图，保持**延迟局部
  import**（函数内 import），避免 main 导入期循环依赖。

**约定**：新增蓝图注册请加到 `backend/blueprints.py` 对应函数，不要在 `main.py`
散落 `register_blueprint`。

## 3. 前端 API 分层

`src/webui/src/api/` 按域拆分：

- `client.ts`：axios 实例 + token 注入 / 401 刷新拦截器，导出 `api`（通用实例）、
  `API_BASE`、`axios`。
- `video.ts / tag.ts / library.ts / gallery.ts / system.ts / post.ts /
  resource.ts / text.ts / thumbnail.ts / config.ts / collectionSet.ts /
  watchLater.ts`：各域 API 对象。
- `index.ts`：聚合 re-export，**仅提供命名导出**，不提供默认导出。

**约定**：
- 未归入具体域、需裸调路径的端点统一用 `import { api } from '../api'`（命名导入），
  禁止使用默认导入 `import api from '../api'`。
- 新增端点优先归入对应域文件；通用后台管理类端点可放在 `system.ts` 或对应域。

## 4. 前端状态（Pinia store）按域拆分

`src/webui/src/stores/` 按业务域拆分 store：

- `videoStore`：视频列表/详情/进度。
- `tagStore`：标签状态（从 videoStore 独立拆分，避免状态分叉）。
- `galleryStore` / `watchLaterStore` / `userStore`：各自域。

**约定**：store 之间不得重复持有同一份状态。跨域共享状态（如标签）由归属 store
持有，其他 store 通过 computed 引用或方法委托，禁止各自 `ref` 一份。

## 5. 测试与 CI

- 后端：`tests/` 下 unittest，覆盖 helper 纯函数、runtime 注入不变量、DB 集成。
- 前端：`src/webui/test/` 下 vitest（api 层 + store 层，mock axios）。
- CI（`.github/workflows/tests.yml`）同时跑后端 unittest、前端 `vue-tsc` 类型检查
  与 `vitest`，并验证 `import main` 成功且路由数稳定（防导入期回归）。

**约定**：任何解耦/拆分改动必须同步补充对应测试，并确认 CI 全绿。
