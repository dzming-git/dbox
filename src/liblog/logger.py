# -*- coding: utf-8 -*-
"""
统一日志接口库 - Dplayer日志系统

提供线程安全的日志记录功能，支持四种日志分类：
- 维护日志 (maintenance): 关键操作、状态变更（禁止刷屏）
- 运行日志 (runtime): 流水账（任务创建、日常记录）
- 调试日志 (debug): 开发调试信息
- 操作日志 (operation): 用户操作记录

特性：
- module 自动获取：无需手动传入调用者标识
- 线程安全：使用线程锁和队列确保并发安全
- 异步写入：缓冲机制提升性能
- 格式统一：时间 | 等级 | 模块 | 内容
"""

import os
import re
import threading
import queue
import time
from datetime import datetime
from typing import Optional

# ========== 配置 ==========
# 日志根目录：通过环境变量或默认路径配置
LOG_BASE_DIR = os.environ.get(
    'DPLAYER_LOG_DIR',
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'logs')
)

# 日志分类
LOG_CATEGORIES = {
    'maintenance': 'maintenance.log',   # 维护日志：关键操作、状态变更
    'runtime': 'runtime.log',           # 运行日志：流水账
    'debug': 'debug.log',               # 调试日志：开发调试
    'operation': 'operation.log'        # 操作日志：用户操作
}

# 日志等级（从高到低）
LOG_LEVELS = ['FATAL', 'ERROR', 'WARN', 'INFO', 'DEBUG']


def filter_content(content: str) -> str:
    """
    过滤日志内容中的非法字符
    - 替换换行符为空格
    - 移除控制字符
    """
    if not content:
        return ''

    # 替换换行符为空格
    content = content.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')

    # 移除控制字符（保留常见可打印字符）
    content = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', content)

    # 合并连续空格
    content = re.sub(r'\s+', ' ', content).strip()

    return content


def get_timestamp() -> str:
    """获取当前时间戳"""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# ========== 日志写入器 ==========
class AsyncLogWriter:
    """异步日志写入器 - 使用队列缓冲"""
    
    def __init__(self, log_file: str, buffer_size: int = 100, flush_interval: float = 1.0):
        self.log_file = log_file
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval
        
        # 确保日志目录存在
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        # 消息队列
        self.queue = queue.Queue(maxsize=1000)
        
        # 线程锁
        self.lock = threading.Lock()
        
        # 缓冲区
        self.buffer = []
        
        # 后台写入线程
        self.running = True
        self.writer_thread = threading.Thread(target=self._write_loop, daemon=True)
        self.writer_thread.start()
    
    def _write_loop(self):
        """后台写入循环"""
        while self.running:
            try:
                try:
                    msg = self.queue.get(timeout=self.flush_interval)
                    self.buffer.append(msg)
                except queue.Empty:
                    pass
                
                if len(self.buffer) >= self.buffer_size:
                    self._flush()
            except Exception:
                pass
    
    def _flush(self):
        """刷新缓冲区到文件"""
        if not self.buffer:
            return
        
        with self.lock:
            if not self.buffer:
                return
            
            try:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    for msg in self.buffer:
                        f.write(msg + '\n')
                self.buffer.clear()
            except Exception:
                pass
    
    def write(self, message: str):
        """写入日志消息"""
        try:
            self.queue.put(message, timeout=1)
        except queue.Full:
            with self.lock:
                try:
                    with open(self.log_file, 'a', encoding='utf-8') as f:
                        f.write(message + '\n')
                except Exception:
                    pass
    
    def flush(self):
        """强制刷新缓冲区"""
        self._flush()
    
    def stop(self):
        """停止写入器"""
        self.running = False
        self.writer_thread.join(timeout=2)
        self._flush()


# ========== 全局日志管理器 ==========
class UnifiedLogger:
    """统一日志管理器（单例）"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        self._writers = {}
        self._writers_lock = threading.Lock()
        self._category_levels = {
            'maintenance': 'INFO',   # 维护日志默认 INFO 级别
            'runtime': 'DEBUG',      # 运行日志默认 DEBUG（记录所有流水）
            'debug': 'DEBUG',        # 调试日志默认 DEBUG
            'operation': 'INFO'      # 操作日志默认 INFO
        }
        
        # 初始化日志写入器
        for category, filename in LOG_CATEGORIES.items():
            log_path = os.path.join(LOG_BASE_DIR, filename)
            self._writers[category] = AsyncLogWriter(log_path)
    
    def set_level(self, category: str, level: str):
        """设置日志等级"""
        if category in self._category_levels and level in LOG_LEVELS:
            self._category_levels[category] = level
    
    def _should_log(self, category: str, level: str) -> bool:
        """判断是否应该记录该日志"""
        category_level = self._category_levels.get(category, 'DEBUG')
        return LOG_LEVELS.index(level) <= LOG_LEVELS.index(category_level)
    
    def log(self, category: str, level: str, service: Optional[str], content: str, source_ip: str = None):
        """
        记录日志 - 主接口
        
        参数:
            category: 日志分类 (maintenance|runtime|debug|operation)
            level: 日志等级 (FATAL|ERROR|WARN|INFO|DEBUG)
            service: 服务名（如 'dplayer-web'，为 None 时自动获取或使用注册的服务名）
            content: 日志内容
            source_ip: 来源IP，仅操作日志有效
        
        返回:
            bool: 是否成功记录
        """
        # 验证参数
        if category not in LOG_CATEGORIES:
            category = 'runtime'
        
        if level not in LOG_LEVELS:
            level = 'INFO'
        
        # 自动获取服务名：优先使用传入的 service，其次注册表
        if service is None:
            service = get_registered_service()
        if service is None:
            service = 'unknown'
        
        # 过滤内容
        service = filter_content(service)
        content = filter_content(content)
        
        # 格式化时间戳
        timestamp = get_timestamp()
        
        # 构造日志消息
        if category == 'operation':
            # 操作日志格式: [时间戳] | [来源IP] | [服务] | [内容]
            ip = filter_content(source_ip or 'unknown')
            message = f"[{timestamp}] | [{ip}] | [{service}] | [{content}]"
        else:
            # 其他日志格式: [时间戳] | [等级] | [服务] | [内容]
            message = f"[{timestamp}] | [{level}] | [{service}] | [{content}]"
        
        # 检查日志等级
        if not self._should_log(category, level):
            return False
        
        # 写入日志
        writer = self._writers.get(category)
        if writer:
            writer.write(message)
            return True
        
        return False
    
    def flush(self):
        """刷新所有缓冲区"""
        for writer in self._writers.values():
            writer.flush()
    
    def stop(self):
        """停止所有写入器"""
        for writer in self._writers.values():
            writer.stop()
        self._writers.clear()


# ========== 服务日志注册表 ==========
# 全局服务名注册表（进程级别）
_service_registry: dict = {}


def register_service(name: str) -> str:
    """
    注册当前进程的服务名（供日志使用）
    
    Args:
        name: 服务名，如 'dplayer-web', 'dplayer-thumbnail' 等
        
    Returns:
        注册的服务名
    """
    _service_registry['current_service'] = name
    return name


def get_registered_service() -> str | None:
    """获取当前进程注册的服务名"""
    return _service_registry.get('current_service')


# ========== ServiceLogger 工厂 ==========
class ServiceLogger:
    """
    绑定服务名的日志器（推荐方式）
    
    在服务入口创建一次，后续调用自动带上服务标识。
    支持日志聚合视图，可按服务名筛选日志（类似 journalctl -u）。
    
    用法:
        # 方式一：自动获取服务名（需要在进程启动时调用 register_service）
        from liblog import get_service_logger
        log = get_service_logger()
        log.maintenance('INFO', '服务启动成功')
        
        # 方式二：显式指定服务名
        log = get_service_logger('dplayer-web')
        log.maintenance('INFO', '服务启动成功')
    """
    
    def __init__(self, service_name: str = None):
        # 如果未指定服务名，尝试从注册表获取
        self._service = service_name or get_registered_service() or 'unknown'
    
    def _call(self, category: str, level: str, content: str, **kwargs):
        return get_logger().log(category, level, self._service, content, **kwargs)
    
    def maintenance(self, level: str, content: str):
        """维护日志：关键操作、状态变更"""
        return self._call('maintenance', level, content)
    
    def runtime(self, level: str, content: str):
        """运行日志：流水账"""
        return self._call('runtime', level, content)
    
    def debug(self, level: str, content: str):
        """调试日志：开发调试"""
        return self._call('debug', level, content)
    
    def operation(self, content: str, source_ip: str = None):
        """操作日志：用户操作"""
        return self._call('operation', '', content, source_ip=source_ip)
    
    def info(self, category: str, content: str):
        """INFO 级别日志"""
        return self._call(category, 'INFO', content)
    
    def error(self, category: str, content: str):
        """ERROR 级别日志"""
        return self._call(category, 'ERROR', content)
    
    def warn(self, category: str, content: str):
        """WARN 级别日志"""
        return self._call(category, 'WARN', content)


def get_service_logger(service_name: str = None) -> ServiceLogger:
    """
    创建绑定服务名的日志器（推荐方式）
    
    Args:
        service_name: 服务名，如 'dplayer-web'。如果为 None，自动使用注册的服务名。
        
    用法:
        from liblog import get_service_logger, register_service
        
        # 方式一：在服务入口注册服务名（推荐）
        register_service('dplayer-web')
        log = get_service_logger()  # 自动使用 'dplayer-web'
        
        # 方式二：直接指定服务名
        log = get_service_logger('dplayer-thumbnail')
    """
    if service_name is None:
        service_name = get_registered_service() or 'unknown'
    return ServiceLogger(service_name)


# ========== 便捷接口函数 ==========
_logger = None
_logger_lock = threading.Lock()


def get_logger() -> UnifiedLogger:
    """获取全局日志管理器实例"""
    global _logger
    if _logger is None:
        with _logger_lock:
            if _logger is None:
                _logger = UnifiedLogger()
    return _logger





def log(category: str, level: str, module: Optional[str] = None, content: str = '', source_ip: str = None) -> bool:
    """
    统一日志接口 - 简洁调用入口
    
    参数:
        category: 日志分类 (maintenance|runtime|debug|operation)
        level: 日志等级 (FATAL|ERROR|WARN|INFO|DEBUG)
        module: 应用模块标识（为 None 时自动获取）
        content: 日志内容
        source_ip: 来源IP，仅操作日志有效
    
    返回:
        bool: 是否成功记录
    
    示例:
        # module 自动获取
        log('maintenance', 'ERROR', None, '服务意外停止')
        
        # 手动指定 module
        log('runtime', 'INFO', 'thumbnail', '缩略图任务创建: hash=abc123')
        
        # 操作日志
        log('operation', '', None, '用户登录', '203.0.113.7')
    """
    return get_logger().log(category, level, module, content, source_ip)


# 便捷方法
def log_maintenance(level: str, content: str, module: Optional[str] = None):
    """维护日志：关键操作、状态变更"""
    return log('maintenance', level, module, content)


def log_runtime(level: str, content: str, module: Optional[str] = None):
    """运行日志：流水账"""
    return log('runtime', level, module, content)


def log_debug(level: str, content: str, module: Optional[str] = None):
    """调试日志：开发调试"""
    return log('debug', level, module, content)


def log_operation(content: str, module: Optional[str] = None, source_ip: str = None):
    """操作日志：用户操作"""
    return log('operation', '', module, content, source_ip=source_ip)


# ========== 程序退出时清理 ==========
import atexit

def _cleanup():
    """程序退出时清理资源"""
    try:
        get_logger().flush()
        get_logger().stop()
    except Exception:
        pass

atexit.register(_cleanup)


# ========== 测试 ==========
if __name__ == '__main__':
    print("=" * 60)
    print("统一日志接口库测试")
    print("=" * 60)

    # 测试 ServiceLogger 工厂
    print("\n[1] ServiceLogger 测试:")
    register_service('test-service')
    slog = get_service_logger()
    print(f"  ServiceLogger.service = {slog._service}")

    # 测试各类日志
    print("\n[2] 日志记录测试:")

    slog.maintenance('INFO', '服务启动成功')
    print("  维护日志: OK")

    slog.runtime('INFO', '缩略图任务创建: hash=test123')
    print("  运行日志: OK")

    slog.debug('DEBUG', '查询参数: page=1, size=20')
    print("  调试日志: OK")

    slog.operation('用户登录', '203.0.113.7')
    print("  操作日志: OK")

    # 测试便捷函数
    log_maintenance('INFO', '便捷函数测试 - 维护日志')
    log_runtime('INFO', '便捷函数测试 - 运行日志')
    log_debug('DEBUG', '便捷函数测试 - 调试日志')
    log_operation('便捷函数测试 - 操作日志')
    print("  便捷函数: OK")

    # 等待写入
    time.sleep(1)
    get_logger().flush()

    print("\n[3] 日志文件输出:")
    for category, filename in LOG_CATEGORIES.items():
        path = os.path.join(LOG_BASE_DIR, filename)
        print(f"  {category}: {path}")
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                print(f"    行数: {len(lines)}")
                if lines:
                    print(f"    最后一行: {lines[-1].strip()}")

    print("\n测试完成!")
