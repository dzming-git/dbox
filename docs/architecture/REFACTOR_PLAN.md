# DPlayer 2.0 项目架构优化方案

## 目标

1. **代码文档分离**：源码和文档分开管理
2. **服务独立**：每个服务占一个独立文件夹
3. **统一源码目录**：所有服务放在统一的源码目录中
4. **清晰分层**：便于开发、维护和部署

---

## 当前架构问题

```
Dplayer2.0/
├── dplayer-src/          # 启动入口混杂在根目录
│   ├── web.py
│   ├── thumbnail_service.py
│   ├── config/           # 配置文件分散
│   ├── instance/         # 数据库分散
│   ├── logs/            # 日志分散
│   └── static/          # 静态文件分散
├── msa-web/            # 核心模块独立
├── msa-thumb/          # 缩略图模块独立
├── frontend/           # 前端独立
├── scripts/           # 脚本独立
├── services/          # 服务配置独立
├── static/            # 前端静态文件
├── logs/              # 日志文件
├── instance/          # 数据库文件
├── libs/             # 共享库
├── venv/             # 虚拟环境
└── TODO.md           # 文档在根目录
```

**问题**：
- ❌ 启动入口和核心模块分离不清晰
- ❌ 配置、数据库、日志分散在多个目录
- ❌ 文档和代码混在一起
- ❌ 后端模块独立性不强，依赖关系不明显

---

## 推荐架构方案

### 方案一：标准微服务架构（推荐）

```
Dplayer2.0/
│
├── src/                        # 【源码目录】所有后端服务源码
│   │
│   ├── web/                    # Web 后端服务
│   │   ├── main.py             # 服务入口
│   │   ├── api/                # API 蓝图
│   │   ├── core/               # 数据模型
│   │   ├── backend/            # 后端工具
│   │   ├── utils/              # 工具函数
│   │   └── README.md          # 服务说明
│   │
│   ├── thumbnail/              # 缩略图服务
│   │   ├── main.py
│   │   ├── thumbnail_service.py
│   │   └── README.md
│   │
│   └── shared/                # 【共享模块】所有服务共享
│       ├── libs/              # 共享库
│       │   └── libweb/
│       ├── middleware/         # 中间件
│       └── utils/            # 工具函数
│
├── docs/                      # 【文档目录】所有文档
│   ├── architecture/          # 架构文档
│   │   ├── design.md
│   │   └── deployment.md
│   ├── api/                  # API 文档
│   │   ├── web-api.md
│   │   └── thumbnail-api.md
│   ├── development/          # 开发文档
│   │   ├── setup.md
│   │   ├── debugging.md
│   │   └── testing.md
│   ├── user-guide/           # 用户指南
│   │   └── user-manual.md
│   └── CHANGELOG.md          # 变更日志
│
├── configs/                   # 【配置目录】所有配置
│   ├── web/
│   │   ├── config.json
│   │   └── nginx.conf
│   ├── thumbnail/
│   │   └── config.json
│   └── services/
│       ├── dplayer-web.json
│       └── dplayer-thumbnail.json
│
├── data/                      # 【数据目录】运行时数据（不提交）
│   ├── databases/
│   │   └── dplayer.db
│   ├── logs/
│   │   ├── web.log
│   │   ├── thumbnail.log
│   │   └── webui.log
│   └── uploads/
│
├── static/                    # 【静态资源】前端构建产物
│   └── dist/
│       ├── index.html
│       └── assets/
│
├── scripts/                   # 【脚本目录】开发/部署脚本
│   ├── install.py
│   ├── uninstall.py
│   ├── dev_start.bat
│   ├── dev_stop.bat
│   ├── init_root.py
│   └── clean_temp_files.py
│
├── tests/                     # 【测试目录】测试代码
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── frontend/                  # 【前端源码】Vue3 项目
│   ├── src/
│   ├── public/
│   ├── package.json
│   └── vite.config.js
│
├── venv/                      # 【虚拟环境】Python 虚拟环境（不提交）
│
├── .gitignore                 # Git 忽略规则
├── README.md                  # 项目说明
├── LICENSE                    # 许可证
└── TODO.md                   # 待办事项（可选，或移到 docs/）
```

---

## 架构优势

### 1. 清晰分层
```
┌─────────────────────────────────────────┐
│           Dplayer2.0/                │
├─────────────────────────────────────────┤
│ src/              源码（核心代码）   │
│ docs/             文档（独立管理）    │
│ configs/          配置（集中管理）    │
│ data/             数据（运行时）      │
│ static/           资源（构建产物）    │
│ scripts/          脚本（工具）       │
│ tests/            测试（质量保证）    │
│ frontend/         前端（源码）       │
│ venv/             环境（不提交）      │
└─────────────────────────────────────────┘
```

### 2. 服务独立
每个服务都是一个独立的模块：
```
src/
├── web/              # Web 后端服务（独立启动、独立配置、独立日志）
├── thumbnail/        # 缩略图服务（独立启动、独立配置、独立日志）
└── shared/           # 共享模块（被所有服务引用）
```

### 3. 共享模块
所有服务共享的代码统一管理：
```
src/shared/
├── libs/           # 共享库（如 libweb）
├── middleware/     # 共享中间件（认证、日志、CORS）
└── utils/         # 共享工具函数
```

### 4. 文档独立
所有文档集中管理，方便查阅：
```
docs/
├── architecture/   架构文档
├── api/           API 文档
├── development/   开发文档
└── user-guide/    用户指南
```

### 5. 配置集中
所有配置文件统一管理：
```
configs/
├── web/           Web 服务配置
├── thumbnail/     缩略图服务配置
└── services/      NSSM 服务配置
```

### 6. 数据隔离
运行时数据集中管理，不提交到 Git：
```
data/
├── databases/     数据库文件
├── logs/          日志文件
└── uploads/       上传文件
```

---

## 迁移步骤

### 第一阶段：创建新目录结构
```bash
# 创建目录
mkdir -p src/{web,thumbnail,shared/{libs,middleware,utils}}
mkdir -p docs/{architecture,api,development,user-guide}
mkdir -p configs/{web,thumbnail,services}
mkdir -p data/{databases,logs,uploads}
mkdir -p tests/{unit,integration,e2e}
```

### 第二阶段：移动文件
```bash
# 移动 Web 服务
mv dplayer-src/web.py src/web/main.py
mv msa-web/* src/web/

# 移动缩略图服务
mv dplayer-src/thumbnail_service.py src/thumbnail/main.py
mv msa-thumb/* src/thumbnail/

# 移动共享库
mv libs/* src/shared/libs/

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
# 修改 src/web/main.py
# 统一添加 src/ 到 sys.path
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

# 从 from core.models import ...
# 改为 from web.core.models import ...
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
# 启动服务验证
python src/web/main.py --dev
python src/thumbnail/main.py --dev

# 测试 API
curl http://localhost:8080/health
```

---

## .gitignore 更新

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

# 配置文件（可选，根据需求）
configs/*/config.json
!configs/*/config.json.example

# 前端构建产物
static/dist/
frontend/node_modules/
frontend/dist/

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

---

## 优点总结

✅ **清晰分层**：源码、文档、配置、数据、静态文件各司其职
✅ **服务独立**：每个服务都是独立模块，易于维护和扩展
✅ **文档独立**：文档集中管理，便于查阅和更新
✅ **配置集中**：配置文件统一管理，便于部署和切换环境
✅ **数据隔离**：运行时数据不提交到 Git，避免污染代码库
✅ **易于扩展**：新增服务只需在 `src/services/` 下创建新目录
✅ **便于协作**：前端和后端开发人员可以独立工作
✅ **便于部署**：每个服务可以独立部署和扩展

---

## 备选方案

### 方案二：简化的扁平架构

如果项目规模较小，可以考虑更简化的扁平架构：

```
Dplayer2.0/
├── src/               # 所有后端源码
│   ├── web/         # Web 后端
│   ├── thumbnail/   # 缩略图服务
│   └── shared/      # 共享模块
├── docs/            # 文档
├── configs/         # 配置
├── data/            # 数据
└── frontend/        # 前端
```

优点：结构更简单，适合小型项目
缺点：服务独立性稍弱

---

## 建议

**推荐使用方案一（标准微服务架构）**，理由：
1. ✅ 项目已有多个服务，适合微服务架构
2. ✅ 未来可能新增更多服务，扩展性强
3. ✅ 团队协作更清晰，职责分明
4. ✅ 便于后续部署到容器或云平台

---

## 实施建议

1. **分阶段迁移**：不要一次性移动所有文件，逐步验证每个阶段
2. **保留旧结构**：先在新结构下运行测试，确认无误后再删除旧目录
3. **更新文档**：同步更新部署文档和开发文档
4. **版本控制**：每个阶段提交一次，便于回滚
