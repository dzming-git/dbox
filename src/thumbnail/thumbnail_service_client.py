#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缩略图微服务客户端 (Thumbnail Service Client)

提供与缩略图微服务交互的客户端类。
主应用通过此类调用缩略图微服务。

作者：<工作目录> AI
创建时间：2025-03-13
"""

import requests
import os
import time
from liblog import get_module_logger
from datetime import datetime

log = get_module_logger()


class ThumbnailServiceClient:
    """缩略图微服务客户端"""
    
    def __init__(self, service_url=None, timeout=10, max_retries=3, fallback_enabled=True):
        """
        初始化客户端
        
        Args:
            service_url: 缩略图服务URL，默认从环境变量读取
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
            fallback_enabled: 是否启用降级（服务不可用时使用本地生成）
        """
        self.service_url = service_url or os.getenv(
            'THUMBNAIL_SERVICE_URL',
            'http://localhost:5001'
        )
        self.timeout = timeout
        self.max_retries = max_retries
        self.fallback_enabled = fallback_enabled
        self.service_available = True
        self.last_check_time = None
        self.check_interval = 60  # 健康检查间隔（秒）
        
        log.runtime('INFO', f"缩略图服务客户端初始化: URL={self.service_url}, fallback={fallback_enabled}")
    
    def _make_request(self, method, endpoint, data=None, params=None):
        """
        发送HTTP请求到缩略图服务
        
        Args:
            method: HTTP方法（GET, POST等）
            endpoint: API端点
            data: 请求数据（POST）
            params: 查询参数（GET）
            
        Returns:
            响应数据或None
        """
        url = f"{self.service_url}{endpoint}"
        
        for attempt in range(self.max_retries):
            try:
                if method == 'GET':
                    response = requests.get(url, params=params, timeout=self.timeout)
                elif method == 'POST':
                    response = requests.post(url, json=data, timeout=self.timeout)
                else:
                    log.debug('ERROR', f"不支持的HTTP方法: {method}")
                    return None
                
                response.raise_for_status()
                return response.json()
                
            except requests.exceptions.Timeout:
                log.debug('WARN', f"请求超时: {url}, 尝试 {attempt + 1}/{self.max_retries}")
                if attempt == self.max_retries - 1:
                    self.service_available = False
                    return None
                    
            except requests.exceptions.ConnectionError:
                log.debug('WARN', f"连接失败: {url}, 尝试 {attempt + 1}/{self.max_retries}")
                if attempt == self.max_retries - 1:
                    self.service_available = False
                    return None
                    
            except requests.exceptions.HTTPError as e:
                log.debug('ERROR', f"HTTP错误: {url}, status={e.response.status_code}")
                return None
                
            except Exception as e:
                log.debug('ERROR', f"请求异常: {url}, 错误={str(e)}")
                return None
        
        return None
    
    def check_health(self):
        """
        检查服务健康状态
        
        Returns:
            bool: 服务是否可用
        """
        # 避免频繁检查
        if self.last_check_time:
            elapsed = (datetime.now() - self.last_check_time).total_seconds()
            if elapsed < self.check_interval:
                return self.service_available
        
        result = self._make_request('GET', '/health')
        
        if result and result.get('status') == 'healthy':
            self.service_available = True
            self.last_check_time = datetime.now()
            log.debug('DEBUG', f"服务健康检查通过: {result}")
            return True
        else:
            self.service_available = False
            log.debug('WARN', f"服务健康检查失败: {result}")
            return False
    
    def generate_thumbnail(self, video_path, video_hash, output_format='gif'):
        """
        请求生成缩略图
        
        Args:
            video_path: 视频文件路径
            video_hash: 视频hash
            output_format: 输出格式（gif或jpg）
            
        Returns:
            dict: 包含task_id和status，失败时返回None
        """
        data = {
            'video_path': video_path,
            'video_hash': video_hash,
            'output_format': output_format
        }
        
        result = self._make_request('POST', '/api/thumbnail/generate', data=data)
        
        if result and result.get('success'):
            log.runtime('INFO', f"成功请求缩略图生成: task_id={result.get('task_id')}, video_hash={video_hash}")
            return result
        else:
            log.debug('ERROR', f"请求缩略图生成失败: video_hash={video_hash}, result={result}")
            return None
    
    def get_task_status(self, task_id):
        """
        查询任务状态
        
        Args:
            task_id: 任务ID
            
        Returns:
            dict: 任务状态信息，失败时返回None
        """
        result = self._make_request('GET', f'/api/thumbnail/status/{task_id}')
        
        if result and result.get('success'):
            return result
        else:
            return None
    
    def get_task_status_by_hash(self, video_hash):
        """
        根据视频hash查询任务状态
        
        Args:
            video_hash: 视频hash
            
        Returns:
            dict: 任务状态信息，失败时返回None
        """
        result = self._make_request('GET', f'/api/thumbnail/by_hash/{video_hash}/status')
        
        if result and result.get('success'):
            return result
        else:
            return None
    
    def get_thumbnail_file(self, video_hash):
        """
        获取缩略图文件
        
        Args:
            video_hash: 视频hash
            
        Returns:
            bytes: 缩略图文件内容，失败时返回None
        """
        url = f"{self.service_url}/api/thumbnail/file/{video_hash}"
        
        for attempt in range(self.max_retries):
            try:
                response = requests.get(url, timeout=self.timeout)
                response.raise_for_status()
                return response.content
                
            except Exception as e:
                log.debug('WARN', f"获取缩略图文件失败: video_hash={video_hash}, 尝试 {attempt + 1}/{self.max_retries}, 错误={str(e)}")
                if attempt == self.max_retries - 1:
                    return None
        
        return None
    
    def regenerate_thumbnail(self, video_path, video_hash, output_format='gif'):
        """
        重新生成缩略图
        
        Args:
            video_path: 视频文件路径
            video_hash: 视频hash
            output_format: 输出格式（gif或jpg）
            
        Returns:
            dict: 包含task_id和status，失败时返回None
        """
        data = {
            'video_path': video_path,
            'video_hash': video_hash,
            'output_format': output_format
        }
        
        result = self._make_request('POST', '/api/thumbnail/regenerate', data=data)
        
        if result and result.get('success'):
            log.runtime('INFO', f"成功请求重新生成缩略图: task_id={result.get('task_id')}, video_hash={video_hash}")
            return result
        else:
            log.debug('ERROR', f"请求重新生成缩略图失败: video_hash={video_hash}, result={result}")
            return None
    
    def get_metrics(self):
        """
        获取服务指标
        
        Returns:
            dict: 服务指标信息，失败时返回None
        """
        result = self._make_request('GET', '/metrics')
        
        if result:
            return result
        else:
            return None
    
    def wait_for_completion(self, task_id, timeout=30, check_interval=1):
        """
        等待任务完成
        
        Args:
            task_id: 任务ID
            timeout: 超时时间（秒）
            check_interval: 检查间隔（秒）
            
        Returns:
            dict: 最终任务状态，超时返回None
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            status = self.get_task_status(task_id)
            
            if status is None:
                log.debug('WARN', f"查询任务状态失败: task_id={task_id}")
                return None
            
            task_status = status.get('status')
            
            if task_status == 'completed':
                log.runtime('INFO', f"任务完成: task_id={task_id}")
                return status
            elif task_status == 'failed':
                log.debug('ERROR', f"任务失败: task_id={task_id}, error={status.get('error')}")
                return status
            
            time.sleep(check_interval)
        
        log.debug('WARN', f"任务超时: task_id={task_id}, timeout={timeout}s")
        return None
    
    def is_available(self):
        """
        检查服务是否可用
        
        Returns:
            bool: 服务是否可用
        """
        return self.service_available and self.check_health()


# 全局客户端实例
_global_client = None


def get_thumbnail_client():
    """
    获取全局缩略图服务客户端实例
    
    Returns:
        ThumbnailServiceClient: 客户端实例
    """
    global _global_client
    
    if _global_client is None:
        _global_client = ThumbnailServiceClient()
    
    return _global_client


def reset_thumbnail_client():
    """
    重置全局客户端实例
    """
    global _global_client
    _global_client = None
