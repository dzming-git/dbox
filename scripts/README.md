# Dplayer 脚本目录说明

本目录下的脚本体分为三类：**部署启动**、**运维/工具**、**数据恢复与迁移**。
所有脚本均基于项目根目录推导路径，可直接随文件夹移动，无需固定安装位置。

---

## 一、两种部署模式

| 模式 | 适用场景 | 依赖 | 入口 |
|------|----------|------|------|
| **绿色免安装**（推荐） | 本地开发、演示、随便搬目录 | 无需管理员、不写注册表、不依赖 NSSM | `start.bat` / `stop.bat`（项目根目录），底层为 `launcher.py` |
| **Windows 服务（NSSM）** | 生产环境常驻运行 | 需管理员 + 安装 NSSM | `install.py` → `uninstall.py` / `service_manager.py` |

> 绿色模式用后台子进程拉起全部 11 个服务，看门狗监控源码改动后自动热重载对应服务（前端 Vite 自带 HMR）。NSSM 模式把服务注册成 Windows 服务，移动目录需先用 `install.py --uninstall` 再重新安装。

---

## 二、部署启动脚本

### `launcher.py` — 绿色启动器（核心）
后台子进程拉起所有服务，带看门狗热重载与崩溃自愈。
```bash
python scripts/launcher.py            # 启动全部服务
python scripts/launcher.py --stop     # 停止全部服务
python scripts/launcher.py --status   # 仅检查路径/venv/端口，不启动
```
> 项目根目录的 `start.bat` / `stop.bat` 即是对它的封装，双击即可用。

### `install.py` — 注册 NSSM 服务（生产）
```bash
python scripts/install.py --dev        # 开发模式（热加载，设 DPLAYER_DEV_MODE=1）
python scripts/install.py --prod       # 生产模式（设 DPLAYER_SERVICE_MODE=1）
python scripts/install.py --update     # 更新服务配置
python scripts/install.py --uninstall  # 卸载所有服务
python scripts/install.py --services web --dev   # 只安装指定服务
```

### `uninstall.py` — 卸载 NSSM 服务
```bash
python scripts/uninstall.py              # 仅移除服务注册
python scripts/uninstall.py --purge      # 额外删除运行目录（--force 跳过确认）
python scripts/uninstall.py --services web   # 只卸载 web 服务
```

### `service_manager.py` — NSSM 服务管理 CLI
```bash
python scripts/service_manager.py status            # 查看所有服务状态
python scripts/service_manager.py restart web       # 重启 web 服务
python scripts/service_manager.py restart-all       # 重启所有服务
# 子命令：status / start / stop / restart / start-all / stop-all / restart-all
```

---

## 三、运维 / 工具脚本

### `dev_sync.py` — 开发同步工具（源码 → 运行目录）
被后台「同步」接口（`src/web/api/system_api.py`）调用。支持单向全量同步与持续监控。
```bash
python scripts/dev_sync.py            # 执行一次全量同步
python scripts/dev_sync.py --watch    # 持续监控模式
python scripts/dev_sync.py --dry-run  # 预览将要同步的文件
python scripts/dev_sync.py --source <路径> --dest <路径>
```

### `clean_temp_files.py` — 临时文件清理
扫描并把临时脚本/文档/截图移入归档目录（默认不真删，先预览）。
```bash
python scripts/clean_temp_files.py              # 预览模式
python scripts/clean_temp_files.py --execute    # 执行清理
python scripts/clean_temp_files.py --deep       # 深度清理（更多类型）
```

### `firewall_manager.bat` — 防火墙端口管理（需管理员）
```bat
firewall_manager.bat 8080            # 添加 8080 端口入站规则
firewall_manager.bat 8080 remove     # 删除规则
firewall_manager.bat 8080 list       # 查看规则
```

## 四、数据恢复与迁移脚本

### `init_root.py` — 初始化 / 重置 root 账号
```bash
python scripts/init_root.py
```

### `restore_users.py` — 从视频库 DB 恢复丢失用户到主库
扫描 `data/libraries/*.db`，将缺失用户去重后写入 `data/databases/dplayer.db`。

### `restore_libraries.py` — 修正视频库注册
按文件名 `{库名}_{时间戳}.db` 推断真实库名并修正主库中的库注册记录。

### `migrate_unify_index.py` — 统一双索引源迁移（2026-07-12）
备份 `resource.db` 并清理已废弃的 `resource_items` 表，校验 web 索引完整性。
```bash
python scripts/migrate_unify_index.py   # 迁移前建议先停掉 resourced 服务
```

### `analyze_lib_dbs.py` — 库 DB 诊断（只读）
列出每个库 DB 文件中的库记录与视频数量，帮助排查文件→库名映射问题。直接运行即可。

---

## 五、已清理的临时 / 冗余文件

为满足「目录精简、便于搬迁」目标，已删除以下一次性测试、硬编码路径或功能重复的脚本：

- `_test_path.py` — 一次性路径测试（含硬编码绝对路径）
- `test_simple.bat` — 防火墙临时测试
- `check_lib_mapping.py` — 冗余诊断（硬编码路径，功能与 `analyze_lib_dbs.py` 重复）
- `restart_webui.py` / `restart_webui.bat` — 启停 webui，已被 `service_manager.py restart webui` 覆盖
- `dev_start.bat` / `dev_stop.bat` — 开发启停，已被 `launcher.py` + 根目录 `start.bat`/`stop.bat` 覆盖
- `init_library_db.py` — 过时脚本（硬编码旧 `instance/dplayer.db` 路径，项目已改用 `data/databases`）
- `migrate_videos_to_main_db.py` — 一次性、硬编码特定库名的内容迁移
