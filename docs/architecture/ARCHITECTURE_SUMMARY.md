# DPlayer 2.0 架构优化方案总结

## 推荐架构

```
Dplayer2.0/
├── src/                    # 【源码目录】所有源码（前后端）
│   ├── web/               # Web 后端服务
│   │   ├── main.py        # 服务入口
│   │   ├── api/           # API 蓝图
│   │   ├── core/          # 数据模型
│   │   ├── backend/       # 后端工具
│   │   ├── utils/         # 工具函数
│   │   └── README.md      # 服务说明
│   ├── thumbnail/         # 缩略图服务
│   │   ├── main.py
│   │   ├── thumbnail_service.py
│   │   └── README.md
│   ├── webui/             # WebUI 前端服务（Vue3）
│   │   ├── src/          # Vue3 源码
│   │   ├── public/
│   │   ├── package.json
│   │   ├── vite.config.js
│   │   └── README.md
│   ├── libweb/            # 【共享库】Web 共享库
│   ├── middleware/        # 【共享中间件】所有服务共享
│   └── utils/             # 【共享工具】所有服务共享
│
├── docs/                  # 【文档目录】所有文档
│   ├── architecture/      # 架构文档
│   ├── api/              # API 文档
│   ├── development/      # 开发文档
│   └── user-guide/       # 用户指南
│
├── configs/               # 【配置目录】所有配置
│   ├── web/              # Web 服务配置
│   ├── thumbnail/        # 缩略图服务配置
│   └── services/         # NSSM 服务配置
│
├── data/                  # 【数据目录】运行时数据（不提交）
│   ├── databases/        # 数据库文件
│   ├── logs/             # 日志文件
│   └── uploads/          # 上传文件
│
├── static/                # 【静态资源】前端构建产物
│   └── dist/
│
├── scripts/               # 【脚本目录】开发/部署脚本
│   ├── install.py
│   ├── uninstall.py
│   ├── dev_start.bat
│   ├── dev_stop.bat
│   └── init_root.py
│
├── tests/                 # 【测试目录】测试代码
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── venv/                 # 【虚拟环境】Python 虚拟环境（不提交）
│
├── .gitignore            # Git 忽略规则
├── README.md             # 项目说明
├── LICENSE               # 许可证
└── CHANGELOG.md          # 变更日志
```

---

## 核心特点

### 1. 代码文档分离
- ✅ `src/` 存放所有源码（前端+后端）
- ✅ `docs/` 存放所有文档
- ✅ 代码和文档完全独立，互不干扰

### 2. 服务独立
- ✅ `src/web/` - Web 后端服务独立
- ✅ `src/thumbnail/` - 缩略图服务独立
- ✅ `src/webui/` - WebUI 前端服务独立
- ✅ 每个服务有独立的入口、配置、日志
- ✅ 服务之间通过 `src/libweb/`、`src/middleware/`、`src/utils/` 共享代码

### 3. 统一源码目录
- ✅ 所有源码都在 `src/` 目录下
- ✅ 前后端源码集中管理
- ✅ 共享库直接在 `src/` 下（如 `src/libweb/`）
- ✅ 源码位置清晰，易于查找

### 4. 清晰分层
```
Dplayer2.0/
├── src/          后端源码
├── docs/         文档
├── configs/      配置
├── data/         运行时数据
├── static/       静态资源
├── scripts/      脚本
├── tests/        测试
├── frontend/     前端源码
└── venv/         虚拟环境
```

---

## 目录说明

| 目录 | 说明 | 是否提交到 Git |
|------|------|--------------|
| `src/` | 所有源码（前端+后端） | ✅ 是 |
| `docs/` | 所有文档 | ✅ 是 |
| `configs/` | 配置文件 | ⚠️ 部分是（示例文件） |
| `data/` | 运行时数据（数据库、日志、上传） | ❌ 否 |
| `static/` | 前端构建产物 | ⚠️ 部分是（生产构建） |
| `scripts/` | 开发/部署脚本 | ✅ 是 |
| `tests/` | 测试代码 | ✅ 是 |
| `venv/` | Python 虚拟环境 | ❌ 否 |

---

## 迁移步骤

### 第一阶段：创建新目录
```bash
mkdir -p src/{web,thumbnail,webui,libweb,middleware,utils}
mkdir -p docs/{architecture,api,development,user-guide}
mkdir -p configs/{web,thumbnail,services}
mkdir -p data/{databases,logs,uploads}
mkdir -p tests/{unit,integration,e2e}
```

### 第二阶段：移动文件
```bash
# 移动 Web 后端服务
mv dplayer-src/web.py src/web/main.py
mv msa-web/* src/web/

# 移动缩略图服务
mv dplayer-src/thumbnail_service.py src/thumbnail/main.py
mv msa-thumb/* src/thumbnail/

# 移动 WebUI 前端服务
mv frontend/* src/webui/

# 移动共享库（直接放到 src/ 下）
mv libs/* src/

# 移动配置
mv dplayer-src/config/* configs/web/
mv services/dplayer-*.json configs/services/

# 移动数据
mv instance data/databases
mv logs data/logs
mv uploads data/uploads

# 移动文档
mv TODO.md docs/development/TODO.md
```

### 第三阶段：更新导入路径
```python
# 修改 src/web/main.py，添加 src/ 到 sys.path
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

# 更新导入语句
from web.core.models import ...
from shared.libs.libweb import ...
```

### 第四阶段：更新服务配置
```bash
# 更新 NSSM 服务配置
nssm set dplayer-web AppDirectory "C:\Users\<用户>\<工作目录>\Dplayer2.0"
nssm set dplayer-web AppParameters "C:\Users\<用户>\<工作目录>\Dplayer2.0\src\web\main.py"
```

### 第五阶段：测试验证
```bash
# 启动后端服务验证
python src/web/main.py --dev
python src/thumbnail/main.py --dev

# 启动前端服务验证
cd src/webui
npm install
npm run dev

# 测试 API
curl http://localhost:8080/health
```

---

## 优势

✅ **代码文档分离**：源码和文档完全独立
✅ **服务独立**：每个服务都是独立模块
✅ **统一源码目录**：所有源码（前端+后端）在 `src/` 下
✅ **清晰分层**：各目录职责明确
✅ **易于扩展**：新增服务只需在 `src/` 下创建新目录
✅ **便于协作**：前后端开发人员独立工作
✅ **便于部署**：每个服务可以独立部署

---

## .gitignore

```gitignore
# 虚拟环境
venv/
__pycache__/
*.pyc
*.pyo
*.pyd

# 运行时数据（data/ 目录）
data/databases/*.db
data/logs/*.log
data/uploads/*
!data/uploads/.gitkeep

# 配置文件（敏感信息）
configs/*/config.json
!configs/*/config.json.example

# 前端构建产物和依赖
static/dist/
src/webui/node_modules/
src/webui/dist/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# 操作系统
.DS_Store
Thumbs.db
desktop.ini
```
