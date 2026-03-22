#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DPlayer - 临时文件清理脚本

功能：
  1. 清理临时脚本文件（.tmp.py, test_*.py, debug_*.py 等）
  2. 清理临时 Markdown 文档（*.tmp.md, temp_*.md 等）
  3. 清理工具截图（screenshot_*.png, *.tmp.png 等）
  4. 移动到归档目录而非直接删除，避免误删

用法：
  python scripts/clean_temp_files.py              # 预览模式（只显示将要移动的文件）
  python scripts/clean_temp_files.py --execute    # 执行清理
  python scripts/clean_temp_files.py --deep       # 深度清理（包含更多临时文件类型）
"""

import os
import sys
import shutil
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Tuple

# ============================================================
# 配置
# ============================================================

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# 归档目录（相对项目根目录）
ARCHIVE_DIR = PROJECT_ROOT / '.archive' / 'temp_files'

# 默认临时文件模式（相对路径匹配）
DEFAULT_TEMP_PATTERNS = [
    # 临时脚本
    '*.tmp.py',
    'test_*.py',
    'debug_*.py',
    'temp_*.py',
    'tmp_*.py',
    'check_*.py',
    'demo_*.py',
    
    # 临时 Markdown
    '*.tmp.md',
    'temp_*.md',
    'tmp_*.md',
    'draft_*.md',
    
    # 临时图片
    '*.tmp.png',
    '*.tmp.jpg',
    'screenshot_*.png',
    'screenshot_*.jpg',
    'temp_*.png',
    'temp_*.jpg',
    
    # 其他临时文件
    '*.tmp',
    '*.bak',
    '*.swp',
    '*~',
]

# 深度清理模式：包含更多临时文件
DEEP_CLEAN_PATTERNS = [
    # 包含默认模式
    *DEFAULT_TEMP_PATTERNS,
    
    # 深度清理额外模式
    'old_*.py',
    'backup_*.py',
    'test_backup_*',
    '*.old',
    '*.backup',
    'untitled_*',
]

# 排除目录（不扫描这些目录）
EXCLUDE_DIRS = {
    '__pycache__', '.git', '.venv', 'venv', 'node_modules',
    '.pytest_cache', '.mypy_cache', '.archive', 'logs',
}

# 排除文件（即使是临时文件也不清理）
EXCLUDE_FILES = {
    '__init__.py',
    'conftest.py',
}


# ============================================================
# 工具函数
# ============================================================

def should_exclude_path(path: Path) -> bool:
    """判断路径是否应被排除"""
    # 检查目录
    for part in path.parts:
        if part in EXCLUDE_DIRS:
            return True
    
    # 检查文件名
    if path.name in EXCLUDE_FILES:
        return True
    
    return False


def match_patterns(filename: str, patterns: List[str]) -> bool:
    """检查文件名是否匹配任意模式"""
    from fnmatch import fnmatch
    for pattern in patterns:
        if fnmatch(filename, pattern):
            return True
    return False


def find_temp_files(root_dir: Path, patterns: List[str]) -> List[Tuple[Path, str]]:
    """
    扫描目录查找临时文件。
    返回：[(文件路径, 匹配的模式), ...]
    """
    temp_files = []
    
    for item in root_dir.rglob('*'):
        if not item.is_file():
            continue
        
        if should_exclude_path(item):
            continue
        
        if match_patterns(item.name, patterns):
            # 找到匹配的模式
            matched_pattern = next(
                (p for p in patterns if match_patterns(item.name, [p])),
                'unknown'
            )
            temp_files.append((item, matched_pattern))
    
    return temp_files


def get_file_size_str(size_bytes: int) -> str:
    """将文件大小转换为可读字符串"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def move_to_archive(file_path: Path, archive_dir: Path, dry_run: bool = True) -> bool:
    """
    移动文件到归档目录。
    
    Args:
        file_path: 文件路径
        archive_dir: 归档目录
        dry_run: 是否为预览模式
    
    Returns:
        是否成功
    """
    # 计算相对路径
    try:
        rel_path = file_path.relative_to(PROJECT_ROOT)
    except ValueError:
        rel_path = file_path.name
    
    # 归档目标路径
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    archive_name = f"{timestamp}_{rel_path.name}"
    archive_path = archive_dir / rel_path.parent / archive_name
    
    if dry_run:
        print(f"  [DRY-RUN] Would move: {rel_path}")
        print(f"            To: {archive_path.relative_to(PROJECT_ROOT)}")
        return True
    
    # 创建归档目录
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 移动文件
    try:
        shutil.move(str(file_path), str(archive_path))
        print(f"  [OK] Moved: {rel_path}")
        print(f"       To: {archive_path.relative_to(PROJECT_ROOT)}")
        return True
    except Exception as e:
        print(f"  [FAIL] Failed to move {rel_path}: {e}")
        return False


# ============================================================
# 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='DPlayer 临时文件清理脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/clean_temp_files.py              # 预览模式（只显示将要移动的文件）
  python scripts/clean_temp_files.py --execute    # 执行清理
  python scripts/clean_temp_files.py --deep       # 深度清理（包含更多临时文件类型）
  python scripts/clean_temp_files.py --execute --deep  # 执行深度清理
        """
    )
    parser.add_argument(
        '--execute', action='store_true',
        help='执行清理（默认为预览模式）'
    )
    parser.add_argument(
        '--deep', action='store_true',
        help='深度清理（包含更多临时文件类型）'
    )
    args = parser.parse_args()
    
    dry_run = not args.execute
    patterns = DEEP_CLEAN_PATTERNS if args.deep else DEFAULT_TEMP_PATTERNS
    
    print("=" * 70)
    print("  DPlayer - 临时文件清理脚本")
    print("=" * 70)
    print(f"  项目目录: {PROJECT_ROOT}")
    print(f"  归档目录: {ARCHIVE_DIR}")
    print(f"  清理模式: {'深度清理' if args.deep else '标准清理'}")
    print(f"  执行模式: {'预览模式（不实际移动文件）' if dry_run else '执行清理'}")
    print("=" * 70)
    print()
    
    # 查找临时文件
    print("[1/3] 扫描临时文件...")
    temp_files = find_temp_files(PROJECT_ROOT, patterns)
    
    if not temp_files:
        print("  未找到临时文件")
        print()
        print("=" * 70)
        print("  清理完成：无需清理的文件")
        print("=" * 70)
        return 0
    
    # 按类型分组统计
    print(f"\n[2/3] 找到 {len(temp_files)} 个临时文件：")
    print()
    
    # 按扩展名分组
    ext_groups = {}
    for file_path, pattern in temp_files:
        ext = file_path.suffix.lower() or 'no_ext'
        if ext not in ext_groups:
            ext_groups[ext] = []
        ext_groups[ext].append((file_path, pattern))
    
    # 显示统计
    total_size = 0
    for ext, files in sorted(ext_groups.items()):
        group_size = sum(f.stat().st_size for f, _ in files if f.exists())
        total_size += group_size
        print(f"  {ext:10s} {len(files):3d} 个文件  ({get_file_size_str(group_size)})")
        for file_path, pattern in files[:5]:  # 只显示前5个
            try:
                rel_path = file_path.relative_to(PROJECT_ROOT)
                print(f"    - {rel_path}")
            except ValueError:
                print(f"    - {file_path}")
        if len(files) > 5:
            print(f"    ... 还有 {len(files) - 5} 个文件")
        print()
    
    print("-" * 70)
    print(f"  总计: {len(temp_files)} 个文件, 大小: {get_file_size_str(total_size)}")
    print("-" * 70)
    print()
    
    # 移动文件
    print("[3/3] 移动临时文件...")
    print()
    
    if dry_run:
        print("  [预览模式] 以下文件将被移动到归档目录：")
        print()
    else:
        # 创建归档目录
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        print(f"  创建归档目录: {ARCHIVE_DIR}")
        print()
    
    success_count = 0
    for file_path, pattern in temp_files:
        if not file_path.exists():
            continue
        if move_to_archive(file_path, ARCHIVE_DIR, dry_run):
            success_count += 1
    
    # 总结
    print()
    print("=" * 70)
    if dry_run:
        print(f"  预览完成：共 {len(temp_files)} 个文件将被移动")
        print()
        print("  使用 --execute 参数执行实际清理：")
        print(f"    python scripts/clean_temp_files.py --execute")
    else:
        print(f"  清理完成：成功移动 {success_count}/{len(temp_files)} 个文件")
        print()
        print(f"  归档位置: {ARCHIVE_DIR}")
        print()
        print("  如需恢复文件，请从归档目录中复制回原位置")
    print("=" * 70)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
