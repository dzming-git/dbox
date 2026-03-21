# DPlayer 工具模块说明

## 模块列表

### 1. system_optimizer.py - 系统网络优化模块

自动优化系统网络配置，解决局域网访问偶现失败问题。

#### 功能

- 自动配置Windows防火墙规则
- 优化TCP连接池设置
- 启用TCP保活机制
- 刷新DNS缓存
- 优化Python Socket配置

#### 使用方法

**自动调用（推荐）**

所有微服务启动时会自动调用，无需手动操作：

```python
# app.py / admin_app.py / thumbnail_service.py 中已集成
from utils.system_optimizer import optimize_system

# 服务启动时自动执行
optimize_system(ports=[PORT], service_names=['服务名'])
```

**手动调用**

```python
from utils.system_optimizer import optimize_system, optimize_socket

# 执行系统级优化
results = optimize_system(
    ports=[80, 8080, 5001],
    service_names=['主应用', '管理后台', '缩略图服务']
)

# 优化Socket配置
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock = optimize_socket(sock)
```

#### 优化效果

- ✅ 防火墙规则自动配置
- ✅ TCP端口范围扩展（1025-65537）
- ✅ TIME_WAIT超时减少（240秒→30秒）
- ✅ TCP保活机制启用
- ✅ Socket连接稳定性提升
- ✅ 局域网访问成功率提升

#### 权限要求

- **管理员权限**：防火墙配置、TCP注册表设置
- **普通权限**：Socket优化、DNS缓存刷新

如果未以管理员权限启动，日志会显示警告：
```
[警告] 未以管理员权限运行，部分优化可能失败
```

---

### 2. network_optimize.py - Flask网络优化模块

优化Flask应用的WebSocket连接配置。

#### 功能

- 重写Flask的Socket创建方法
- 自动应用TCP保活、地址重用、缓冲区优化
- 适用于所有Flask应用

#### 使用方法

**自动集成**

```python
# 在Flask应用创建后调用
from flask import Flask
from utils.network_optimize import optimize_flask_app

app = Flask(__name__)

# 应用网络优化
try:
    optimize_flask_app(app)
    print('[*] 网络连接优化已启用')
except Exception as e:
    print(f'[警告] 网络优化失败: {e}')

# 启动应用
app.run(host='0.0.0.0', port=8080)
```

#### 优化内容

- TCP保活机制（60秒后开始，每10秒检测）
- 地址重用（解决TIME_WAIT问题）
- 禁用Nagle算法（减少延迟）
- 优化缓冲区大小（64KB）

---

## 开发者指南

### 为新服务添加系统优化

如果创建了新的微服务，建议添加系统优化：

```python
from flask import Flask
from utils.network_optimize import optimize_flask_app
from utils.system_optimizer import optimize_system

# 创建Flask应用
app = Flask(__name__)

# 应用Flask网络优化
try:
    optimize_flask_app(app)
    logger.info('网络连接优化已启用')
except Exception as e:
    logger.warning(f'网络优化失败: {e}')

# 在启动时执行系统优化
if __name__ == '__main__':
    # 执行系统级优化
    logger.info("执行系统网络优化...")
    try:
        optimize_system(
            ports=[SERVICE_PORT],
            service_names=['服务名称']
        )
    except Exception as e:
        logger.warning(f"系统优化失败: {e}")

    # 启动服务
    app.run(host='0.0.0.0', port=SERVICE_PORT)
```

### 自定义优化参数

```python
from utils.system_optimizer import SystemOptimizer

# 创建优化器实例
optimizer = SystemOptimizer()

# 单独执行各项优化
optimizer.optimize_firewall(80, '我的服务')
optimizer.optimize_tcp_pool()
optimizer.enable_tcp_keepalive()
optimizer.flush_dns_cache()

# 优化自定义Socket
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock = optimizer.optimize_socket(sock)
```

### 查看优化结果

```python
from utils.system_optimizer import optimize_system

results = optimize_system(
    ports=[80, 8080],
    service_names=['服务1', '服务2']
)

# 检查结果
print(f'防火墙: {results["firewall"]}')
print(f'TCP连接池: {results["tcp_pool"]}')
print(f'TCP保活: {results["tcp_keepalive"]}')
print(f'DNS缓存: {results["dns_cache"]}')
```

---

## 常见问题

### Q1: 需要手动调用吗？

**A:** 不需要。所有微服务（app.py、admin_app.py、thumbnail_service.py）已集成，启动时会自动执行。

### Q2: 优化会影响性能吗？

**A:** 影响极小：
- 系统级优化：仅启动时执行一次（毫秒级）
- Socket优化：每次连接建立时应用（微秒级）
- 总体：提升连接稳定性和并发能力

### Q3: 需要管理员权限吗？

**A:** 部分功能需要：
- 防火墙配置：需要管理员权限
- TCP注册表：需要管理员权限
- Socket优化、DNS刷新：不需要管理员权限

如果没有管理员权限，服务仍可正常运行，但防火墙和TCP优化会被跳过。

### Q4: 优化会重复执行吗？

**A:** 系统级优化每次启动都会执行，但：
- 防火墙规则：已存在则跳过
- TCP设置：覆盖已有配置
- DNS缓存：每次都刷新
- Socket优化：每个连接都应用

### Q5: Linux系统支持吗？

**A:** 基本支持：
- Socket优化：完全支持
- DNS刷新：完全支持
- 防火墙/TCP：需要适配（当前主要针对Windows）

---

## 相关文档

- [系统优化文档](../docs/SYSTEM_OPTIMIZATION.md) - 详细的优化说明和效果验证
- [网络故障排除](../docs/NETWORK_TROUBLESHOOTING.md) - 网络问题排查指南
- [修复脚本](../scripts/fix_network_issues.bat) - 手动修复工具
- [诊断脚本](../scripts/diagnose_network.bat) - 网络诊断工具

---

## 更新日志

- 2025-03-14: 创建system_optimizer.py，集成自动优化功能
- 2025-03-14: 所有微服务启动时自动执行系统优化
- 2025-03-14: 创建network_optimize.py，优化Flask连接
