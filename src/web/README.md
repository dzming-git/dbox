# Dbox

视频播放器后端服务 - 纯API架构

## 项目结构

```
Dplayer2.0/
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
│   ├── service_manager.py   # 服务管理器
│   ├── dbox-web.json     # Web服务NSSM配置
│   └── dbox-thumbnail.json # 缩略图服务NSSM配置
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
nssm install dbox-web "C:\Python311\python.exe" "C:\Users\<用户>\<工作目录>\Dplayer2.0\web.py"
nssm set dbox-web AppDirectory "C:\Users\<用户>\<工作目录>\Dplayer2.0"
nssm set dbox-web DisplayName "Dbox Web服务"
nssm set dbox-web Start SERVICE_AUTO_START

# 安装缩略图服务（通过 ServiceBus 总线）
nssm install dbox-thumbnail "C:\Python311\python.exe" "C:\Users\<用户>\<工作目录>\Dplayer2.0\configs\services\thumbnaild.py"
nssm set dbox-thumbnail AppDirectory "C:\Users\<用户>\<工作目录>\Dplayer2.0"
nssm set dbox-thumbnail DisplayName "Dbox 缩略图服务"
nssm set dbox-thumbnail Start SERVICE_AUTO_START

# 安装服务总线代理
nssm install dbox-bus "C:\Python311\python.exe" "C:\Users\<用户>\<工作目录>\Dplayer2.0\configs\services\busbroker.py"
nssm set dbox-bus AppDirectory "C:\Users\<用户>\<工作目录>\Dplayer2.0"
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
