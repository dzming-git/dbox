# Dbox

视频播放器后端服务 - 纯API架构

## 项目结构

```
dbox/
├── config/
│   └── config.json          # 配置文件
├── instance/
│   └── dbox.db           # SQLite数据库
├── libs/                    # 共享库
├── logs/                    # 日志目录
├── msa-web/                # Web服务核心代码
│   ├── api/                 # API蓝图
│   ├── backend/             # 后端工具
│   ├── core/                # 核心模型
│   └── utils/               # 工具函数
├── msa-thumb/              # 缩略图服务代码
├── services/                # 服务配置
│   ├── dbox-web.json     # Web服务NSSM配置
│   └── dbox-thumbnail.json # 缩略图服务NSSM配置
│   # 注：原 service_manager.py 已移除（无引用且已失效）；
│   # 服务启停请用 scripts/service_manager.py CLI 或 service-ops 扩展插件。
├── static/
│   └── thumbnails/          # 缩略图存储
├── web.py                   # Web服务入口
└── thumbnail_service.py     # 缩略图服务入口（已废弃，使用 configs/services/thumbnaild.py）
```

## 服务

### Web服务 (端口: 8080)
- 视频管理 API
- 标签管理 API
- 用户认证 API
- 配置管理 API

### 缩略图服务（通过 ServiceBus 总线）
- 缩略图生成
- 缩略图查询
- 任务队列管理

## 安装服务

```bash
# 安装Web服务
nssm install dbox-web "C:\Python311\python.exe" "C:\Users\<用户>\<工作目录>\dbox\web.py"
nssm set dbox-web AppDirectory "C:\Users\<用户>\<工作目录>\dbox"
nssm set dbox-web DisplayName "Dbox Web服务"
nssm set dbox-web Start SERVICE_AUTO_START

# 安装缩略图服务（通过 ServiceBus 总线）
nssm install dbox-thumbnail "C:\Python311\python.exe" "C:\Users\<用户>\<工作目录>\dbox\configs\services\thumbnaild.py"
nssm set dbox-thumbnail AppDirectory "C:\Users\<用户>\<工作目录>\dbox"
nssm set dbox-thumbnail DisplayName "Dbox 缩略图服务"
nssm set dbox-thumbnail Start SERVICE_AUTO_START

# 安装服务总线代理
nssm install dbox-bus "C:\Python311\python.exe" "C:\Users\<用户>\<工作目录>\dbox\configs\services\busbroker.py"
nssm set dbox-bus AppDirectory "C:\Users\<用户>\<工作目录>\dbox"
nssm set dbox-bus DisplayName "Dbox 服务总线"
nssm set dbox-bus Start SERVICE_AUTO_START

# 启动服务
nssm start dbox-web
nssm start dbox-thumbnail
```

## API测试

```bash
# 健康检查
curl http://localhost:8080/health

# 获取视频列表
curl http://localhost:8080/api/videos

# 获取标签列表
curl http://localhost:8080/api/tags

# 获取配置
curl http://localhost:8080/api/config
```

## HTTPS / TLS 配置（反馈 202608090002）

默认仅提供明文 HTTP。可在用户配置文件（`web_config.json`，位于系统数据区
`config/` 目录，默认 `C:\ProgramData\Dbox\config\web_config.json`）中启用 HTTPS：

```json
"tls": {
    "enabled": true,            // 是否启用 HTTPS
    "cert_file": "",            // 证书路径（留空则自动生成自签名证书）
    "key_file": "",             // 私钥路径
    "port": 8443,               // HTTPS 监听端口
    "disable_http": false      // 为 true 时仅监听 HTTPS、禁用明文 HTTP
}
```

行为说明：
- `enabled=false`（默认）：行为与之前完全一致，仅明文 HTTP。
- `enabled=true` 且未提供证书：首次启动自动生成自签名证书
  （`dbox-selfsigned.crt` / `dbox-selfsigned.key`，默认 10 年，CN=localhost），
  之后可在 `cert_file`/`key_file` 指定受信任证书替换。
- `disable_http=false`（默认）：同时提供 HTTPS(`tls.port`) 与明文 HTTP(`ports.web`)，便于平滑过渡。
- `disable_http=true`：仅监听 HTTPS，彻底禁用明文 HTTP（呼应「禁用 http，使用 https」）。

> 注意：TLS 在 `app.run` 启动时读取，修改 `tls` 配置后需重启 `dbox-web` 服务生效；
> `GET /api/config` 会返回当前完整配置（含 `tls` 段），`PUT /api/config` 可持久化修改。
> 证书加载失败会安全回退到明文 HTTP，避免服务无法启动。

