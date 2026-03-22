#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DPlayer 开发同步工具

功能：
  1. 开发阶段将源码目录的变更自动同步到运行目录
  2. 支持单向同步（源码 → 运行目录）
  3. 支持持续监控模式（文件变更自动同步）
  4. 支持 --dry-run 参数预览同步内容
  5. 支持 --once 参数执行一次全量同步

用法：
  python scripts/dev_sync.py                    # 执行一次全量同步
  python scripts/dev_sync.py --watch            # 持续监控模式
  python scripts/dev_sync.py --dry-run          # 预览将要同步的文件
  python scripts/dev_sync.py --once             # 执行一次全量同步（等同于无参数）
  python scripts/dev_sync.py --source <path>    # 指定源码目录
  python scripts/dev_sync.py --dest <path>      # 指定运行目录
"""

import os
import sys
import time
import shutil
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Set, Optional

# 需要安装: pip install watchdog
HAS_WATCHDOG = False
Observer = None
FileSystemEventHandler = None

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    pass

# ============================================================
# 配置
# ============================================================

# 默认运行目录
DEFAULT_DEST = r'C:\DPlayer\runtime'

# 源码目录（本脚本上一级）
SOURCE_DIR = Path(__file__).parent.parent.resolve()

# 忽略同步的路径规则
IGNORE_PATTERNS = {
    '__pycache__', '.git', '.venv', 'venv', 'node_modules',
    'instance', 'logs', 'uploads', '.pytest_cache',
    'playwright-report', 'test-results', '.mypy_cache',
    'runtime_backup_*',  # 备份目录
}

# 忽略的文件扩展名
IGNORE_EXTENSIONS = {'.pyc', '.pyo', '.log', '.tmp', '.swp', '.pid'}

# 同步日志文件
SYNC_LOG_FILE = 'logs/dev_sync.log'

# ============================================================
# 日志配置
# ============================================================

def setup_logging(log_dir: Path):
    """设置同步日志"""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / 'dev_sync.log'
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger('dev_sync')


# ============================================================
# 工具函数
# ============================================================

def should_ignore(rel_path: str) -> bool:
    """判断路径是否应该被忽略"""
    parts = Path(rel_path).parts
    for part in parts:
        # 检查是否匹配忽略模式
        for pattern in IGNORE_PATTERNS:
            if pattern.endswith('*'):
                if part.startswith(pattern[:-1]):
                    return True
            elif part == pattern:
                return True
    
    ext = Path(rel_path).suffix.lower()
    if ext in IGNORE_EXTENSIONS:
        return True
    
    return False


def get_sync_state_file(runtime_dir: Path) -> Path:
    """获取同步状态文件路径"""
    return runtime_dir / '.sync_state.json'


def load_sync_state(runtime_dir: Path) -> dict:
    """加载上次同步状态"""
    state_file = get_sync_state_file(runtime_dir)
    if state_file.exists():
        try:
            import json
            return json.loads(state_file.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {'last_sync': None, 'synced_files': {}}


def save_sync_state(runtime_dir: Path, state: dict):
    """保存同步状态"""
    state_file = get_sync_state_file(runtime_dir)
    try:
        import json
        state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as e:
        logging.getLogger('dev_sync').warning(f'保存同步状态失败: {e}')


def sync_file(src_file: Path, dst_file: Path, dry_run: bool = False) -> bool:
    """
    同步单个文件，返回是否实际执行了同步
    """
    if not src_file.exists():
        return False
    
    # 检查是否需要同步（内容或时间不同）
    if dst_file.exists():
        src_mtime = src_file.stat().st_mtime
        dst_mtime = dst_file.stat().st_mtime
        src_size = src_file.stat().st_size
        dst_size = dst_file.stat().st_size
        
        # 时间差小于1秒且大小相同，认为无需同步
        if abs(src_mtime - dst_mtime) < 1 and src_size == dst_size:
            return False
    
    if dry_run:
        print(f'  [dry-run] 将同步: {src_file} -> {dst_file}')
        return True
    
    # 执行同步
    dst_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src_file), str(dst_file))
    
    ts = datetime.now().strftime('%H:%M:%S')
    rel_path = src_file.relative_to(src_file.parent.parent) if src_file.parent.parent else src_file.name
    print(f'  [{ts}] 已同步: {rel_path}')
    
    return True


def delete_file(dst_file: Path, dry_run: bool = False) -> bool:
    """删除运行目录中的文件（当源码中已删除时）"""
    if not dst_file.exists():
        return False
    
    if dry_run:
        print(f'  [dry-run] 将删除: {dst_file}')
        return True
    
    try:
        dst_file.unlink()
        ts = datetime.now().strftime('%H:%M:%S')
        print(f'  [{ts}] 已删除: {dst_file.name}')
        return True
    except Exception as e:
        print(f'  [ERROR] 删除失败 {dst_file}: {e}')
        return False


# ============================================================
# 全量同步
# ============================================================

def full_sync(source_dir: Path, runtime_dir: Path, dry_run: bool = False, 
              delete_orphans: bool = False) -> dict:
    """
    执行全量同步
    
    Args:
        source_dir: 源码目录
        runtime_dir: 运行目录
        dry_run: 是否只预览不执行
        delete_orphans: 是否删除运行目录中源码已不存在的文件
    
    Returns:
        同步统计信息
    """
    log = logging.getLogger('dev_sync')
    log.info(f'开始全量同步: {source_dir} -> {runtime_dir}')
    
    stats = {
        'synced': 0,
        'skipped': 0,
        'deleted': 0,
        'errors': 0,
        'start_time': datetime.now().isoformat()
    }
    
    # 收集源码目录所有文件
    source_files: Set[Path] = set()
    for src_file in source_dir.rglob('*'):
        if src_file.is_dir():
            continue
        try:
            rel = src_file.relative_to(source_dir)
            if should_ignore(str(rel)):
                continue
            source_files.add(rel)
        except ValueError:
            continue
    
    log.info(f'发现 {len(source_files)} 个待同步文件')
    
    # 同步文件
    for rel in source_files:
        src_file = source_dir / rel
        dst_file = runtime_dir / rel
        
        try:
            if sync_file(src_file, dst_file, dry_run):
                stats['synced'] += 1
            else:
                stats['skipped'] += 1
        except Exception as e:
            log.error(f'同步失败 {rel}: {e}')
            stats['errors'] += 1
    
    # 可选：删除运行目录中源码已不存在的文件
    if delete_orphans:
        log.info('检查并删除孤儿文件...')
        for dst_file in runtime_dir.rglob('*'):
            if dst_file.is_dir():
                continue
            try:
                rel = dst_file.relative_to(runtime_dir)
                if should_ignore(str(rel)):
                    continue
                if rel not in source_files:
                    if delete_file(dst_file, dry_run):
                        stats['deleted'] += 1
            except ValueError:
                continue
    
    stats['end_time'] = datetime.now().isoformat()
    
    # 保存同步状态
    if not dry_run:
        state = load_sync_state(runtime_dir)
        state['last_sync'] = stats['end_time']
        state['synced_count'] = stats['synced']
        save_sync_state(runtime_dir, state)
    
    log.info(f'同步完成: 同步 {stats["synced"]} 个, 跳过 {stats["skipped"]} 个, '
             f'删除 {stats["deleted"]} 个, 错误 {stats["errors"]} 个')
    
    return stats


# ============================================================
# 监控模式
# ============================================================

if HAS_WATCHDOG and FileSystemEventHandler:
    class SyncHandler(FileSystemEventHandler):
        """文件系统事件处理器"""
        
        def __init__(self, source_dir: Path, runtime_dir: Path, log: logging.Logger):
            self.source_dir = source_dir
            self.runtime_dir = runtime_dir
            self.log = log
            self._last_sync_time = 0
            self._sync_delay = 0.5  # 防抖延迟（秒）
        
        def on_modified(self, event):
            if event.is_directory:
                return
            self._handle(event.src_path, 'modified')
        
        def on_created(self, event):
            if event.is_directory:
                return
            self._handle(event.src_path, 'created')
        
        def on_deleted(self, event):
            if event.is_directory:
                return
            # 文件删除不自动处理，避免误删
            self.log.debug(f'文件删除（不自动同步）: {event.src_path}')
        
        def _handle(self, src_path: str, event_type: str):
            """处理文件变更事件"""
            src_file = Path(src_path)
            
            try:
                rel = src_file.relative_to(self.source_dir)
            except ValueError:
                return
            
            if should_ignore(str(rel)):
                return
            
            # 防抖处理
            current_time = time.time()
            if current_time - self._last_sync_time < self._sync_delay:
                return
            self._last_sync_time = current_time
            
            # 执行同步
            dst_file = self.runtime_dir / rel
            try:
                if sync_file(src_file, dst_file):
                    self.log.info(f'自动同步 [{event_type}]: {rel}')
            except Exception as e:
                self.log.error(f'自动同步失败 {rel}: {e}')
else:
    SyncHandler = None


def watch_mode(source_dir: Path, runtime_dir: Path):
    """持续监控模式"""
    if not HAS_WATCHDOG:
        print('[ERROR] 监控模式需要 watchdog，请先执行: pip install watchdog')
        sys.exit(1)
    
    log = setup_logging(runtime_dir / 'logs')
    
    print('=' * 60)
    print('  DPlayer 开发同步工具 - 监控模式')
    print('=' * 60)
    print(f'  源码目录: {source_dir}')
    print(f'  运行目录: {runtime_dir}')
    print('  按 Ctrl+C 停止监控')
    print('=' * 60)
    
    # 先做一次全量同步
    log.info('执行初始全量同步...')
    full_sync(source_dir, runtime_dir)
    
    # 启动监控
    handler = SyncHandler(source_dir, runtime_dir, log)
    observer = Observer()
    observer.schedule(handler, str(source_dir), recursive=True)
    observer.start()
    
    log.info('监控已启动')
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print('\n停止监控...')
        observer.stop()
    
    observer.join()
    log.info('监控已停止')


# ============================================================
# 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='DPlayer 开发同步工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/dev_sync.py                    执行一次全量同步
  python scripts/dev_sync.py --watch            持续监控模式
  python scripts/dev_sync.py --dry-run          预览将要同步的文件
  python scripts/dev_sync.py --source <path>    指定源码目录
  python scripts/dev_sync.py --dest <path>      指定运行目录
        """
    )
    parser.add_argument(
        '--source', default=None,
        help='源码目录（默认：脚本所在目录的上一级）'
    )
    parser.add_argument(
        '--dest', default=DEFAULT_DEST,
        help=f'运行目录路径（默认: {DEFAULT_DEST}）'
    )
    parser.add_argument(
        '--watch', action='store_true',
        help='持续监控模式（文件变更自动同步）'
    )
    parser.add_argument(
        '--once', action='store_true',
        help='执行一次全量同步后退出（默认行为）'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='只显示将要同步的文件，不实际执行'
    )
    parser.add_argument(
        '--delete-orphans', action='store_true',
        help='删除运行目录中源码已不存在的文件（谨慎使用）'
    )
    args = parser.parse_args()
    
    source_dir = Path(args.source).resolve() if args.source else SOURCE_DIR
    runtime_dir = Path(args.dest).resolve()
    
    # 验证目录
    if not source_dir.exists():
        print(f'[ERROR] 源码目录不存在: {source_dir}')
        sys.exit(1)
    
    if args.watch:
        watch_mode(source_dir, runtime_dir)
    else:
        # 全量同步模式
        log = setup_logging(runtime_dir / 'logs' if runtime_dir.exists() else source_dir / 'logs')
        
        print('=' * 60)
        print('  DPlayer 开发同步工具')
        print('=' * 60)
        print(f'  源码目录: {source_dir}')
        print(f'  运行目录: {runtime_dir}')
        if args.dry_run:
            print('  模式: 预览模式 (dry-run)')
        print('=' * 60)
        
        stats = full_sync(source_dir, runtime_dir, 
                         dry_run=args.dry_run, 
                         delete_orphans=args.delete_orphans)
        
        print('\n' + '=' * 60)
        print('  同步统计:')
        print(f'    已同步: {stats["synced"]} 个文件')
        print(f'    已跳过: {stats["skipped"]} 个文件')
        print(f'    已删除: {stats["deleted"]} 个文件')
        print(f'    错误:   {stats["errors"]} 个')
        print('=' * 60)


if __name__ == '__main__':
    main()
