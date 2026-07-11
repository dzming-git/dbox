# -*- coding: utf-8 -*-
"""
资源管理模块 - 索引器
负责计算文件 hash、检测媒体类型、提取元数据
"""

import os
import hashlib
import mimetypes
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, Callable, List

# 视频文件扩展名
VIDEO_EXTS = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.mpg', '.mpeg', '.3gp'}
# 图片文件扩展名
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif', '.svg', '.ico'}
# 组图文件扩展名
GALLERY_EXTS = {'.zip', '.tar', '.gz', '.7z', '.rar'}


class MediaIndexer:
    """媒体索引器"""

    @staticmethod
    def get_file_hash(file_path: str, algorithm: str = 'sha256') -> str:
        """计算文件内容 hash"""
        hasher = hashlib.new(algorithm)
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def get_file_size(file_path: str) -> int:
        """获取文件大小（字节）"""
        return os.path.getsize(file_path)

    @staticmethod
    def get_mime_type(file_path: str) -> str:
        """获取文件的 MIME 类型"""
        mime_type, _ = mimetypes.guess_type(file_path)
        return mime_type or 'application/octet-stream'

    @classmethod
    def get_file_ext(cls, file_path: str) -> str:
        """获取文件扩展名（小写）"""
        _, ext = os.path.splitext(file_path)
        return ext.lower()

    @classmethod
    def detect_resource_type(cls, file_path: str) -> str:
        """根据扩展名检测资源类型"""
        ext = cls.get_file_ext(file_path)
        if ext in VIDEO_EXTS:
            return 'video'
        elif ext in IMAGE_EXTS:
            return 'image'
        elif ext in GALLERY_EXTS:
            return 'gallery'
        return 'unknown'

    @classmethod
    def get_dimensions(cls, file_path: str, resource_type: str) -> Tuple[Optional[int], Optional[int]]:
        """获取媒体尺寸（宽度, 高度）"""
        if resource_type == 'image':
            return cls._get_image_dimensions(file_path)
        elif resource_type == 'video':
            return cls._get_video_dimensions(file_path)
        return None, None

    @staticmethod
    def _get_image_dimensions(file_path: str) -> Tuple[Optional[int], Optional[int]]:
        """获取图片尺寸"""
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                return img.width, img.height
        except ImportError:
            try:
                with open(file_path, 'rb') as f:
                    data = f.read()
                if data[:8] == b'\x89PNG\r\n\x1a\n':
                    w = int.from_bytes(data[16:20], 'big')
                    h = int.from_bytes(data[20:24], 'big')
                    return w, h
            except Exception:
                pass
        except Exception:
            pass
        return None, None

    @staticmethod
    def _get_video_dimensions(file_path: str) -> Tuple[Optional[int], Optional[int]]:
        """获取视频尺寸（需要 ffprobe）"""
        try:
            import subprocess
            cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                   '-show_entries', 'stream=width,height', '-of', 'csv=p=0:s=x', file_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split('x')
                if len(parts) == 2:
                    return int(parts[0]), int(parts[1])
        except Exception:
            pass
        return None, None

    @classmethod
    def get_video_duration(cls, file_path: str) -> Optional[float]:
        """获取视频时长（秒）"""
        try:
            import subprocess
            cmd = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                   '-of', 'csv=p=0', file_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception:
            pass
        return None

    @classmethod
    def index_file(cls, file_path: str, library_id: int, folder_id: int = None) -> Optional[Dict[str, Any]]:
        """为单个文件建立索引"""
        if not os.path.isfile(file_path):
            print(f"[indexer] skip (not a file): {file_path}", flush=True)
            return None

        try:
            file_hash = cls.get_file_hash(file_path)
            file_size = cls.get_file_size(file_path)
            mime_type = cls.get_mime_type(file_path)
            file_ext = cls.get_file_ext(file_path)
            resource_type = cls.detect_resource_type(file_path)
            width, height = cls.get_dimensions(file_path, resource_type)
            duration = None
            if resource_type == 'video':
                duration = cls.get_video_duration(file_path)

            return {
                'library_id': library_id,
                'folder_id': folder_id,
                'hash': file_hash,
                'file_path': file_path,
                'file_name': os.path.basename(file_path),
                'file_ext': file_ext,
                'file_size': file_size,
                'mime_type': mime_type,
                'resource_type': resource_type,
                'width': width,
                'height': height,
                'duration': duration,
                'metadata': {'indexed_at': datetime.utcnow().isoformat()},
            }
        except Exception as e:
            print(f"[indexer] index_file failed: {file_path}: {e}", flush=True)
            return None

    @classmethod
    def scan_file(cls, file_path: str, library_id: int, folder_id: int = None) -> Optional[Dict[str, Any]]:
        """扫描单个文件"""
        return cls.index_file(file_path, library_id, folder_id)

    @classmethod
    def scan_directory(cls, directory: str, library_id: int, folder_id: int = None,
                      progress_callback: Callable = None) -> Dict[str, Any]:
        """扫描目录，返回所有文件的索引信息

        Args:
            progress_callback: 回调函数，接收 (current, total, current_file_path)
        """
        print(f"[indexer] scan_directory: start scanning {directory}", flush=True)
        stats = {'total': 0, 'videos': 0, 'images': 0, 'galleries': 0, 'unknown': 0}
        items = []
        added_files: List[str] = []
        removed_files: List[str] = []

        # 先收集所有文件（用于进度计算）
        all_files = []
        for root, dirs, files in os.walk(directory):
            for filename in files:
                all_files.append(os.path.join(root, filename))

        total = len(all_files)
        print(f"[indexer] scan_directory: found {total} files to scan", flush=True)
        for idx, file_path in enumerate(all_files, 1):
            if progress_callback:
                progress_callback(idx, total, file_path)
            try:
                info = cls.index_file(file_path, library_id, folder_id)
                if info:
                    stats['total'] += 1
                    rtype = info['resource_type']
                    stats[rtype + 's'] = stats.get(rtype + 's', 0) + 1
                    items.append(info)
                    added_files.append(file_path)
                else:
                    stats['unknown'] += 1
            except Exception as e:
                print(f"索引文件失败 {file_path}: {e}")
                stats['unknown'] += 1

        print(f"[indexer] scan_directory: done, {len(items)} items indexed, stats={stats}", flush=True)
        return {**stats, 'items': items, 'added_files': added_files, 'removed_files': removed_files}
