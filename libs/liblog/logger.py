# -*- coding: utf-8 -*-
"""
统一日志接口库 - Dplayer日志系统

提供线程安全的日志记录功能，支持四种日志分类：
- 维护日志 (maintenance)
- 运行日志 (runtime)
- 调试日志 (debug)
- 操作日志 (operation)

特性：
- 字符过滤：禁止中文和换行符，写入前自动转换
- 线程安全：使用线程锁和队列确保并发安全
- 异步写入：缓冲机制提升性能
- 格式统一：时间戳|等级|应用模块|内容
"""

import os
import re
import threading
import queue
import time
from datetime import datetime
from typing import Optional
from logging import handlers

# ========== 配置 ==========
LOG_BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')

# 日志分类
LOG_CATEGORIES = {
    'maintenance': 'maintenance.log',   # 维护日志
    'runtime': 'runtime.log',           # 运行日志
    'debug': 'debug.log',               # 调试日志
    'operation': 'operation.log'        # 操作日志
}

# 日志等级（从高到低）
LOG_LEVELS = ['FATAL', 'ERROR', 'WARN', 'INFO', 'DEBUG']

# 允许的字符集：字母、数字、常见特殊字符
ALLOWED_CHARS_PATTERN = re.compile(r'[A-Za-z0-9\s\-_.:/@()\[\]&=+*,;%#!$`~<>?\\^|]')

# 中文字符范围
CHINESE_PATTERN = re.compile(r'[\u4e00-\u9fff]')

# 拼音映射表（常用中文词汇转拼音）
PINYIN_MAP = {
    '用户': 'yonghu', '登录': 'denglu', '登出': 'dengchu', '注册': 'zhuce',
    '管理': 'guanli', '后台': 'houtai', '系统': 'xitong', '错误': 'cuowu',
    '警告': 'jinggao', '信息': 'xinxi', '成功': 'chenggong', '失败': 'shibai',
    '启动': 'qidong', '停止': 'tingzhi', '重启': 'chongqi', '更新': 'gengxin',
    '删除': 'shanchu', '添加': 'tianjia', '修改': 'xiugai', '查询': 'chaxun',
    '视频': 'shipin', '缩略图': 'suolueetu', '播放': 'bofang', '上传': 'shangchuan',
    '下载': 'xiazai', '配置': 'peizhi', '服务': 'fuwu', '端口': 'duankou',
    '连接': 'lianjie', '超时': 'chaoshi', '请求': 'qingqiu', '响应': 'xiangying',
    '数据库': 'shujuku', '缓存': 'huancun', '线程': 'xiancheng', '进程': 'jincheng',
    '日志': 'rizhi', '操作': 'caozuo', '维护': 'weihu', '调试': 'tiaoshi',
    '运行': 'yunxing', '时间': 'shijian', '日期': 'riqi', '文件': 'wenjian',
    '目录': 'mulu', '路径': 'lujing', '权限': 'quanxian', '认证': 'renzheng',
    '验证': 'yanzheng', '接口': 'jiekou', '模块': 'mokuai', '功能': 'gongneng',
    '测试': 'ceshi', '开发': 'kaifa', '版本': 'banben', '更新': 'gengxin',
    '修复': 'xiufu', '优化': 'youhua', '性能': 'xingneng', '内存': 'neicun',
    'CPU': 'CPU', '硬盘': 'yingpan', '网络': 'wangluo', '磁盘': 'cipan',
    '任务': 'renwu', '计划': 'jihua', '定时': 'dingshi', '自动': 'zidong',
    '手动': 'shoudong', '立即': 'liji', '完成': 'wancheng', '异常': 'yichang',
    '正常': 'zhengchang', '无效': 'wuxiao', '有效': 'youxiao', '必须': 'bixu',
    '可选': 'kexuan', '禁止': 'jinzhi', '允许': 'yunxu', '默认': 'morenzhi',
}


def chinese_to_pinyin(text: str) -> str:
    """将中文转换为拼音全拼"""
    result = []
    i = 0
    while i < len(text):
        char = text[i]
        # 匹配中文字符
        if '\u4e00' <= char <= '\u9fff':
            # 尝试匹配双字词
            if i + 1 < len(text):
                two_char = text[i:i+2]
                if two_char in PINYIN_MAP:
                    result.append(PINYIN_MAP[two_char])
                    i += 2
                    continue
            # 匹配单字
            if char in PINYIN_MAP:
                result.append(PINYIN_MAP[char])
            else:
                # 未找到的字符用占位符
                result.append('char')
        else:
            result.append(char)
        i += 1
    return ''.join(result)


def filter_content(content: str) -> str:
    """
    过滤内容中的非法字符
    - 替换换行符为空格
    - 转换中文字符为拼音
    - 移除其他非法字符
    """
    if not content:
        return ''
    
    # 1. 替换换行符为空格
    content = content.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
    
    # 2. 转换中文字符为拼音
    content = chinese_to_pinyin(content)
    
    # 3. 移除不允许的字符（保留允许的）
    filtered = ''
    for char in content:
        if ALLOWED_CHARS_PATTERN.match(char):
            filtered += char
        else:
            filtered += '?'  # 用占位符替换
    
    # 4. 合并连续空格
    filtered = re.sub(r'\s+', ' ', filtered).strip()
    
    return filtered


def format_log_message(timestamp: str, level: str, module: str, content: str) -> str:
    """
    格式化日志消息
    格式: [时间戳] | [等级] | [应用模块] | [内容]
    """
    return f"[{timestamp}] | [{level}] | [{module}] | [{content}]"


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
                # 从队列获取消息（带超时）
                try:
                    msg = self.queue.get(timeout=self.flush_interval)
                    self.buffer.append(msg)
                except queue.Empty:
                    pass
                
                # 缓冲区满或超时则写入
                if len(self.buffer) >= self.buffer_size:
                    self._flush()
                    
            except Exception as e:
                # 忽略写入错误，避免影响主程序
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
            # 队列满，尝试直接写入
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
    """统一日志管理器"""
    
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
            'maintenance': 'DEBUG',
            'runtime': 'DEBUG',
            'debug': 'DEBUG',
            'operation': 'DEBUG'  # 操作日志不区分等级
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
        if category == 'operation':
            return True  # 操作日志不区分等级
        
        category_level = self._category_levels.get(category, 'DEBUG')
        return LOG_LEVELS.index(level) <= LOG_LEVELS.index(category_level)
    
    def log(self, category: str, level: str, module: str, content: str, source_ip: str = None):
        """
        记录日志 - 主接口
        
        参数:
            category: 日志分类 (maintenance|runtime|debug|operation)
            level: 日志等级 (FATAL|ERROR|WARN|INFO|DEBUG)，操作日志忽略此参数
            module: 应用模块标识
            content: 日志内容
            source_ip: 来源IP，仅操作日志有效
        
        返回:
            bool: 是否成功记录
        """
        # 验证参数
        if category not in LOG_CATEGORIES:
            category = 'runtime'  # 默认归类为运行日志
        
        if level not in LOG_LEVELS:
            level = 'INFO'
        
        # 过滤内容
        module = filter_content(module)
        content = filter_content(content)
        
        # 格式化时间戳
        timestamp = get_timestamp()
        
        # 构造日志消息
        if category == 'operation':
            # 操作日志格式: [时间戳] | [来源IP] | [应用模块] | [操作内容]
            ip = filter_content(source_ip or 'unknown')
            message = f"[{timestamp}] | [{ip}] | [{module}] | [{content}]"
        else:
            # 维护/运行/调试日志格式: [时间戳] | [等级] | [应用模块] | [内容]
            message = f"[{timestamp}] | [{level}] | [{module}] | [{content}]"
        
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


# ========== 便捷接口函数 ==========
# 全局日志管理器实例
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


def log(category: str, level: str, module: str, content: str, source_ip: str = None) -> bool:
    """
    统一日志接口 - 简洁调用入口
    
    参数:
        category: 日志分类 (maintenance|runtime|debug|operation)
        level: 日志等级 (FATAL|ERROR|WARN|INFO|DEBUG)，操作日志忽略此参数
        module: 应用模块标识
        content: 日志内容
        source_ip: 来源IP，仅操作日志有效
    
    返回:
        bool: 是否成功记录
    
    示例:
        # 维护日志 - 错误
        log('maintenance', 'ERROR', 'app', 'Service stopped unexpectedly')
        
        # 运行日志 - 通知
        log('runtime', 'INFO', 'system', 'Application started successfully')
        
        # 调试日志
        log('debug', 'DEBUG', 'database', 'Query executed in 0.05s')
        
        # 操作日志
        log('operation', '', 'admin', 'User login', '203.0.113.7')
    """
    return get_logger().log(category, level, module, content, source_ip)


# 便捷方法
def log_maintenance(level: str, module: str, content: str):
    """记录维护日志"""
    return log('maintenance', level, module, content)


def log_runtime(level: str, module: str, content: str):
    """记录运行日志"""
    return log('runtime', level, module, content)


def log_debug(level: str, module: str, content: str):
    """记录调试日志"""
    return log('debug', level, module, content)


def log_operation(module: str, content: str, source_ip: str = None):
    """记录操作日志"""
    return log('operation', '', module, content, source_ip)


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
    
    # 测试字符过滤
    print("\n[1] 字符过滤测试:")
    test_cases = [
        "用户登录成功",
        "系统启动\n换行测试",
        "Error: 连接失败(超时应)",
        "Mixed中文English123"
    ]
    for case in test_cases:
        result = filter_content(case)
        print(f"  原始: {case}")
        print(f"  过滤: {result}")
        print()
    
    # 测试日志记录
    print("\n[2] 日志记录测试:")
    
    # 维护日志 - 错误
    log('maintenance', 'ERROR', 'app', 'Service stopped unexpectedly')
    print("  维护日志-错误: OK")
    
    # 运行日志 - 通知
    log('runtime', 'INFO', 'system', 'Application started successfully')
    print("  运行日志-通知: OK")
    
    # 调试日志 - 调试
    log('debug', 'DEBUG', 'database', 'Query executed in 0.05s')
    print("  调试日志-调试: OK")
    
    # 操作日志
    log('operation', '', 'admin', 'User login', '203.0.113.7')
    print("  操作日志: OK")
    
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
