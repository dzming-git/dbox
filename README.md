# DBox

<div align="center">

![D Logo](docs/logo-d-b.svg)

</div>

> 个人本地媒体资源管理平台（视频 / 图集 / 帖子 / 文本）后端 + Web 前端的一站式管理系统。
> 支持资源入库、缩略图生成、标签/收藏/点赞、资源库（扫描本地目录）、合集/播放列表、图集阅读、用户登录、外部脚本扩展以及服务监控管理后台。

- 版本：`2.0.0`（见 `VERSION`）
- 平台：Windows（绿色免安装 / NSSM 服务两种部署）
- 语言：Python（后端）+ Vue 3 + TypeScript（前端）

---

## 目录

- [核心特性](#核心特性)
- [技术栈](#技术栈)
- [系统架构](#系统架构)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [外部脚本引擎](#外部脚本引擎)
- [API 概览](#api-概览)
- [管理后台](#管理后台)
- [开发指南](#开发指南)
- [脚本与运维](#脚本与运维)
- [常见问题](#常见问题)
- [文档与参考](#文档与参考)

---

## 核心特性

- **视频媒体库**：自动扫描本地目录入库，支持 mp4 / mkv / avi / mov / wmv / flv / webm / m4v 等格式；按内容指纹生成唯一哈希（与文件名/路径解耦），自动去重。
- **缩略图服务**：独立缩略图服务（通过 ServiceBus 总线通信），异步生成并缓存静态海报（`.jpg`）+ 悬停预览雪碧图（`.sprite.jpg`）+ 预览坐标索引（`.vtt`），鼠标悬停即可平滑轮播/seek 视频预览，彻底替代旧版 GIF 动图（无闪烁、最省带宽）。
- **资源库（Library）**：可注册多个本地目录作为资源库，支持递归扫描、定时扫描、文件夹监控（Watchdog）自动入库。
- **标签 / 合集 / 播放列表**：自由打标签、建立合集与播放列表，便于分类与连续观看。
- **用户体系**：登录鉴权，支持收藏 / 点赞 / 踩，数据绑定账号跨设备一致；游客以随机 session 兜底。
- **观看历史与进度**：记录观看历史与播放进度，刷新后可续播。
- **搜索与推荐**：关键词搜索、联想词、相关推荐。
- **漫画支持**：独立漫画模块，支持漫画列表、分页阅读与封面预览。
- **外部脚本引擎**：以 `manifest.json` 声明参数、以标准输入/输出 + HTTP 拉取式交互扩展功能（如下载器、转码、批量处理），参数类型丰富（任意输入 / 单选 / 多选 / 资源库选择 / Cookie 选择 / 可手填下拉）。
- **管理后台**：服务状态监控、启停/重启、进程信息、运行日志，以及外部脚本任务的运行/交互/取消。
- **双部署模式**：绿色免安装（看门狗热重载）与 Windows 服务（NSSM）常驻运行。

---

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11+，Flask（纯 API），SQLite，ZMQ（ServiceBus 总线），Watchdog |
| 前端 | Vue 3，TypeScript，Vite，Pinia，Vue Router，Axios |
| 缩略图 | 独立进程，通过 ServiceBus 收发任务 |
| 部署 | 绿色子进程启动器（launcher.py）/ NSSM 注册为 Windows 服务 |

---

## 系统架构

系统由若干后端微服务 + 前端 + 服务总线组成，启动器（或 NSSM）会一并拉起：

| 组件 | 端口 | 说明 |
|------|------|------|
| Web 后端 | `8080` | 主 API 服务（视频/标签/用户/外部脚本/管理接口） |
| 前端（开发） | `5173` | Vite 开发服务器，反向代理 `/api`、`/thumbnail`、`/local_video` 等到 `8080` |
| 缩略图服务 | `5001` | 缩略图生成服务，经 ServiceBus 通信 |
| 服务总线 | `15555` / `15556` | ZMQ RPC / Pub-Sub 端口（进程内通信） |

> 生产模式下前端构建产物位于 `static/dist/`，由 Web 后端直接托管，无需单独的前端端口。
> 管理 / 监控相关接口随 Web 服务（8080）暴露。

---

## 目录结构

```
Dbox2.0/
├── configs/            # 配置（web / services / thumbnail）
│   ├── web/config.json        # Web 服务主配置（端口、扫描目录、格式…）
│   └── services/              # NSSM 服务配置（JSON）
├── data/               # 运行时数据（不提交 Git）
│   ├── databases/              # SQLite 数据库
│   ├── libraries/              # 资源库数据库
│   ├── logs/                   # 运行日志
│   ├── uploads/                # 上传文件
│   └── thumbnails/             # 缩略图缓存
├── docs/               # 文档（架构 / 开发）
├── extensions/         # 扩展（外部脚本 example：extensions/scripts/）
├── scripts/            # 部署 / 运维 / 迁移脚本
├── src/                # 全部源码
│   ├── web/                    # Web 后端（Flask）
│   │   ├── main.py             # 服务入口
│   │   ├── api/                # API 蓝图（视频/标签/用户/脚本/系统…）
│   │   ├── backend/            # 后端工具（审计、回收站、漫画…）
│   │   ├── core/               # 数据模型
│   │   ├── script_engine/      # 外部脚本引擎
│   │   └── utils/              # 工具函数
│   ├── thumbnail/              # 缩略图服务
│   ├── servicebus/             # ZMQ 服务总线
│   └── webui/                  # 前端（Vue 3）
│       ├── src/                # 前端源码（views / api / components / store）
│       └── vite.config.ts
├── static/             # 前端构建产物（生产）
├── start.bat / stop.bat# 绿色启动 / 停止（封装 launcher.py）
├── start_dev.bat       # 开发模式启动（前端 5173）
├── tests/              # 测试代码
└── VERSION
```

---

## 快速开始

### 方式一：绿色免安装（推荐，本地开发/演示）

无需管理员、不写注册表、不依赖 NSSM，整个目录可随文件夹搬迁。

1. 准备 Python 虚拟环境并安装后端依赖（Flask、pyzmq、watchdog 等）：
   ```bat
   python -m venv venv
   venv\Scripts\pip install flask pyzmq watchdog psutil
   ```
2. 安装前端依赖：
   ```bat
   cd src\webui
   npm install
   cd ..\..
   ```
3. 启动全部服务（会拉起前端 Vite + 各后端微服务，带看门狗热重载）：
   ```bat
   start.bat          # 或：python scripts/launcher.py
   ```
4. 浏览器访问：
   - 前端界面：`http://localhost:5173`（开发）或构建后由 `http://localhost:8080` 直接托管
   - 健康检查：`http://localhost:8080/health`

停止：`stop.bat`（或 `python scripts/launcher.py --stop`）。

### 方式二：Windows 服务（NSSM，生产常驻）

需管理员权限并预先安装 [NSSM](https://nssm.cc/)。

```bat
python scripts/install.py --prod        # 注册并启动服务
python scripts/install.py --dev         # 开发模式注册
python scripts/install.py --uninstall   # 卸载全部服务
```

服务管理：
```bat
python scripts/service_manager.py status        # 查看状态
python scripts/service_manager.py restart web   # 重启 web 服务
python scripts/service_manager.py restart-all   # 重启全部
```

---

## 配置说明

运行时配置与数据库已从项目目录分离到**系统数据区**，不纳入 git 版本控制：

- **Windows**：`%LOCALAPPDATA%/Dbox/`（如 `C:\Users\<你>\AppData\Local\Dbox\config\web_config.json`）
- **Linux/macOS**：`~/.local/share/Dbox/`

目录结构：
```
<系统数据区>/
├── config/           # 运行时配置（代码首次启动自动生成）
│   ├── web_config.json        # 主配置
│   └── thumbnail_config.json  # 缩略图配置
└── data/             # 运行时数据（数据库、缩略图、上传等）
    ├── databases/    # SQLite 库（dbox.db / tasks.db / script_jobs.db ...）
    ├── thumbnails/
    └── ...
```

可通过环境变量覆盖默认位置（运维/多实例场景）：
- `DBOX_USER_CONFIG_DIR`：用户配置根目录
- `DBOX_DATA_DIR`：用户数据根目录
- `DBOX_SYSTEM_DATA`：平台系统数据区根（决定上面两者的默认位置）

> **首次启动自动初始化**：若系统数据区不存在配置文件，后端会用默认值（不含任何个人路径）自动生成 `web_config.json`。`scan_directories` 默认空，需在界面中添加你的扫描目录。
> 从旧版本迁移：若项目根 `data/` 下已有数据，首次启动会自动将其移动到系统数据区，不丢失历史数据。

主配置 `web_config.json` 关键字段：

| 字段 | 说明 |
|------|------|
| `ports.web` | Web 后端端口（默认 `8080`） |
| `scan_directories` | 资源库扫描目录列表（路径、是否递归、是否启用） |
| `library_watch_enabled` | 文件夹实时监控 |
| `auto_scan_on_startup` | 启动时自动扫描 |
| `scan_interval_minutes` | 定时扫描间隔 |
| `supported_formats` / `video_formats` | 支持的视频后缀 |
| `auto_start` | 是否自动启动 |

> 视频唯一标识采用「内容指纹哈希」：`sha256(文件大小 + 头部 4MB + 尾部 4MB)`，与文件名/路径解耦；可安全搬迁文件而不丢失元数据。

---

## 外部脚本引擎

外部脚本（位于 `extensions/scripts/<name>/`）通过一套约定与系统交互，无需修改核心代码即可扩展功能。

**脚本结构**
```
extensions/scripts/<name>/
├── manifest.json     # 声明参数、入口、说明
└── run.py            # 脚本主体
```

**参数声明（manifest.json）**
支持由脚本自定义的参数类型：

| type | 说明 |
|------|------|
| `string` | 任意文本输入 |
| `enum` | 单选项（预设） |
| `multi_enum` | 多选项（可 `allow_custom` 自定义追加） |
| `enum_editable` | 下拉预设 + 手填（combobox） |
| `bool` | 开关 |
| `library_select` | 框架注入的资源库（由系统提供可选项） |
| `cookie_select` | Cookie 选择（由系统 Cookie 保管提供） |

必填项通过 `required: true` 声明；可设 `default`。

**运行契约**
- 脚本经 **stdin** 以 JSON 读取参数（含框架注入的资源库路径 / Cookie）。
- 脚本经 **stdout 逐行** 上报状态：`progress`（进度）、`log`（日志）、`result`（结果）、`notify`（入库通知）、`await_input`（请求用户交互）。
- 分阶段交互采用 **HTTP 拉取式**（与 `notify` 对称）：脚本 stdout 上报 `await_input` → 后端置 `awaiting_input` 态 → 脚本长轮询 `GET /api/scripts/jobs/<id>/input`（带令牌）等待 → 管理员在界面 `POST /api/scripts/jobs/<id>/respond` 提交选择后唤醒脚本继续。

**任务管理**
管理后台可查看脚本任务列表、进度、日志，并支持取消运行中的任务；交互式任务会在界面弹出选择卡片（单选 / 多选 / 文本输入）。

---

## API 概览

后端为纯 API 服务，主要蓝图（`src/web/backend/api/`）：

| 模块 | 路径前缀 | 说明 |
|------|----------|------|
| 视频 | `/api/videos`、`/api/video/<hash>` | 列表、详情、本地播放、点赞/收藏状态 |
| 标签 | `/api/tags` | 标签增删改查 |
| 用户 / 鉴权 | `/api/auth`、`/api/login`、`/api/users` | 登录、注册、用户信息 |
| 交互 | `/api/favorites`、`/api/video/<hash>` | 收藏列表、点赞/踩（绑定账号） |
| 资源库 | `/api/libraries` | 资源库注册、扫描 |
| 合集 / 播放列表 | `/api/collections`、`/api/playlists` | 分类与连播 |
| 搜索 | `/api/search`、`/api/suggestions` | 搜索与联想 |
| 漫画 | `/api/comics` | 漫画列表与分页 |
| 缩略图 | `/thumbnail/<hash>` | 缩略图访问 |
| 外部脚本 | `/api/scripts/...` | 脚本发现、运行、交互、任务 |
| 系统 / 管理 | `/api/system/...` | 服务状态、同步、配置、日志 |

健康检查：`GET /health`。

---

## 管理后台

管理后台（前端 `Admin` 视图，随 Web 服务暴露）提供：

- **服务监控**：各微服务运行状态、端口、进程信息、CPU，后台定时刷新（带缓存）。
- **启停 / 重启**：对注册的服务进行启动、停止、重启（管理后台自身仅允许重启，不允许关闭自己）。
- **运行日志**：查看各服务运行日志。
- **外部脚本**：运行脚本、填写参数、查看进度与日志、处理交互式输入、取消任务。
- **配置**：查看 / 调整部分运行配置。

---

## 开发指南

**后端**
```bat
set DBOX_DEV_MODE=1
python src\web\main.py
```

**前端（Vite 开发服务器，5173，热更新）**
```bat
cd src\webui
npm install
npm run dev
```
前端 `vite.config.ts` 已将 `/api`、`/thumbnail`、`/local_video`、`/comic-*` 代理到 `http://127.0.0.1:8080`。

**构建前端（生产）**
```bat
cd src\webui
npm run build        # 输出到 ../static/dist
```

**测试**
```bat
python -m pytest tests/       # 后端测试
cd src\webui && npm run lint  # 前端 lint
```

---

## 脚本与运维

`scripts/` 目录包含部署、运维与数据迁移脚本（详见 `scripts/README.md`）：

- `launcher.py` — 绿色启动器（看门狗热重载 + 崩溃自愈）
- `install.py` / `uninstall.py` — NSSM 服务注册 / 卸载
- `service_manager.py` — 服务管理 CLI（status / start / stop / restart）
- `dev_sync.py` — 源码 → 运行目录同步
- `clean_temp_files.py` — 临时文件清理
- `init_root.py` — 初始化 / 重置 root 账号
- `restore_users.py` / `restore_libraries.py` / `migrate_unify_index.py` / `analyze_lib_dbs.py` — 数据恢复与迁移

---

## 常见问题

- **前端访问 8080 还是 5173？** 开发模式用 `5173`（Vite HMR）；生产构建后由 Web 服务 `8080` 直接托管。
- **视频搬家后元数据会丢吗？** 不会。视频以内容指纹哈希为唯一标识，与路径解耦。
- **改了后端代码没生效？** 绿色模式看门狗会自动热重载；若仍不生效，确认没有遗留旧进程占用 8080（可 `taskkill` 旧 PID 后重启）。
- **端口冲突？** 特权端口（如 80）需管理员权限；默认使用非特权端口 `8080`。可用 `scripts/firewall_manager.bat` 管理防火墙入站规则。

---

## 文档与参考

- 后端服务说明：`src/web/README.md`
- 脚本与运维：`scripts/README.md`
- 架构与重构计划：`docs/architecture/`（ARCHITECTURE_SUMMARY、SERVICE_BUS、REFACTOR_PLAN）
- 待办事项：`docs/development/TODO.md`、`TODO.md`

---

*本 README 由项目汇总整理。具体实现以源码及上述文档为准。*
