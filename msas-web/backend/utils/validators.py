# 数据验证工具
import re
from typing import Optional, List


def validate_username(username: str) -> tuple[bool, str]:
    """验证用户名"""
    if not username:
        return False, "用户名不能为空"
    
    if len(username) < 3:
        return False, "用户名至少3个字符"
    
    if len(username) > 20:
        return False, "用户名最多20个字符"
    
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return False, "用户名只能包含字母、数字和下划线"
    
    return True, ""


def validate_password(password: str) -> tuple[bool, str]:
    """验证密码"""
    if not password:
        return False, "密码不能为空"
    
    if len(password) < 6:
        return False, "密码至少6个字符"
    
    if len(password) > 50:
        return False, "密码最多50个字符"
    
    return True, ""


def validate_email(email: Optional[str]) -> tuple[bool, str]:
    """验证邮箱"""
    if not email:
        return True, ""  # 邮箱可选
    
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        return False, "邮箱格式不正确"
    
    if len(email) > 100:
        return False, "邮箱最多100个字符"
    
    return True, ""


def validate_video_title(title: str) -> tuple[bool, str]:
    """验证视频标题"""
    if not title:
        return False, "视频标题不能为空"
    
    if len(title) > 200:
        return False, "视频标题最多200个字符"
    
    return True, ""


def validate_tag_name(name: str) -> tuple[bool, str]:
    """验证标签名称"""
    if not name:
        return False, "标签名称不能为空"
    
    if len(name) > 50:
        return False, "标签名称最多50个字符"
    
    return True, ""


def validate_page(page: int, default: int = 1) -> int:
    """验证页码"""
    if page < 1:
        return default
    return page


def validate_per_page(per_page: int, default: int = 20, max_per_page: int = 100) -> int:
    """验证每页数量"""
    if per_page < 1:
        return default
    if per_page > max_per_page:
        return max_per_page
    return per_page


def sanitize_string(s: str, max_length: int = 100) -> str:
    """清理字符串（去除首尾空格并截断）"""
    if not s:
        return ""
    return s.strip()[:max_length]
