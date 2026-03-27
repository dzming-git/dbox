# -*- coding: utf-8 -*-
"""
BusUserAdapter - 用户管理服务的总线适配器

总线服务定义：

  Service:        com.dplayer.userd
  Interface:      com.dplayer.Userd
  Object Path:    /com/dplayer/userd

  Methods:
    ListUsers() → {users: [...]}

    GetUser(user_id) → {user: {...}}

    GetUserByUsername(username) → {user: {...}}

    CreateUser(username, password, role, email)
      → {success: bool, user_id: int}

    UpdateUser(user_id, fields)
      → {success: bool, user: {...}}

    DeleteUser(user_id, hard_delete)
      → {success: bool}

    ChangePassword(user_id, old_password, new_password)
      → {success: bool, error?: string}

    VerifyPassword(username, password)
      → {success: bool, user?: {...}}

    HealthCheck()
      → {status: str, user_count: int}
"""

import os
import sys
from datetime import datetime
from typing import Dict, Any, Optional

# 添加 src 目录到 path 以便导入 servicebus 和本地模块
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

# 支持直接运行和模块导入
try:
    from .models import User, UserDB, UserRole
except ImportError:
    from user.models import User, UserDB, UserRole

from servicebus.service_base import BaseDBusService


class BusUserAdapter(BaseDBusService):
    """
    用户管理服务总线适配器
    """

    BUS_NAME = 'com.dplayer.userd'
    INTERFACES = ['com.dplayer.Userd']
    OBJECT_PATH = '/com/dplayer/userd'

    def __init__(self, host: str = '127.0.0.1', rpc_port: int = 15555, pub_port: int = 15556):
        super().__init__(host, rpc_port, pub_port)

    # ============ 用户查询 ============

    def on_method_list_users(self, params: Dict[str, Any]) -> Dict:
        """列出所有用户"""
        try:
            include_inactive = params.get('include_inactive', False)
            users = UserDB.get_all(include_inactive=include_inactive)
            return {
                'success': True,
                'users': [user.to_dict() for user in users],
                'total': len(users),
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_get_user(self, params: Dict[str, Any]) -> Dict:
        """根据 ID 获取用户"""
        try:
            user_id = params.get('user_id')
            if not user_id:
                return {'success': False, 'error': '缺少 user_id'}

            user = UserDB.get_by_id(user_id)
            if not user:
                return {'success': False, 'error': '用户不存在'}

            return {'success': True, 'user': user.to_dict()}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_get_user_by_username(self, params: Dict[str, Any]) -> Dict:
        """根据用户名获取用户"""
        try:
            username = params.get('username', '').strip()
            if not username:
                return {'success': False, 'error': '缺少 username'}

            user = UserDB.get_by_username(username)
            if not user:
                return {'success': False, 'error': '用户不存在'}

            return {'success': True, 'user': user.to_dict()}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 用户创建 ============

    def on_method_create_user(self, params: Dict[str, Any]) -> Dict:
        """创建用户"""
        try:
            username = params.get('username', '').strip()
            password = params.get('password', '')
            role = params.get('role', 2)  # 默认普通用户
            email = params.get('email', '').strip()

            # 参数验证
            if not username:
                return {'success': False, 'error': '用户名不能为空'}
            if not password:
                return {'success': False, 'error': '密码不能为空'}
            if len(password) < 6:
                return {'success': False, 'error': '密码长度至少6位'}
            if len(username) < 3:
                return {'success': False, 'error': '用户名长度至少3位'}

            # 检查用户名是否存在
            if UserDB.exists_username(username):
                return {'success': False, 'error': f'用户名 {username} 已存在'}

            # 验证角色
            try:
                if isinstance(role, str):
                    role = UserRole[role.upper()].value
                user_role = UserRole(int(role))
            except (ValueError, KeyError):
                return {'success': False, 'error': f'无效的角色: {role}'}

            # 创建用户
            user = User(
                username=username,
                role=user_role,
                email=email,
            )
            user.set_password(password)

            user_id = UserDB.create(user)
            user.id = user_id

            return {
                'success': True,
                'user_id': user_id,
                'user': user.to_dict(),
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 用户更新 ============

    def on_method_update_user(self, params: Dict[str, Any]) -> Dict:
        """更新用户"""
        try:
            user_id = params.get('user_id')
            if not user_id:
                return {'success': False, 'error': '缺少 user_id'}

            user = UserDB.get_by_id(user_id)
            if not user:
                return {'success': False, 'error': '用户不存在'}

            # 更新字段
            if 'username' in params:
                new_username = params['username'].strip()
                if new_username and new_username != user.username:
                    if UserDB.exists_username(new_username, exclude_id=user_id):
                        return {'success': False, 'error': f'用户名 {new_username} 已存在'}
                    user.username = new_username

            if 'email' in params:
                user.email = params['email'].strip()

            if 'role' in params:
                try:
                    if isinstance(params['role'], str):
                        role_val = UserRole[params['role'].upper()].value
                    else:
                        role_val = int(params['role'])
                    user.role = UserRole(role_val)
                except (ValueError, KeyError):
                    return {'success': False, 'error': f'无效的角色: {params["role"]}'}

            if 'is_active' in params:
                user.is_active = bool(params['is_active'])

            UserDB.update(user)
            return {'success': True, 'user': user.to_dict()}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 用户删除 ============

    def on_method_delete_user(self, params: Dict[str, Any]) -> Dict:
        """删除用户"""
        try:
            user_id = params.get('user_id')
            if not user_id:
                return {'success': False, 'error': '缺少 user_id'}

            # 检查用户是否存在
            user = UserDB.get_by_id(user_id)
            if not user:
                return {'success': False, 'error': '用户不存在'}

            # 不允许删除超级管理员
            if user.role == UserRole.ROOT:
                return {'success': False, 'error': '不能删除超级管理员'}

            # 硬删除或软删除
            hard_delete = params.get('hard_delete', False)
            if hard_delete:
                success = UserDB.hard_delete(user_id)
            else:
                success = UserDB.delete(user_id)

            return {'success': success}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 密码管理 ============

    def on_method_change_password(self, params: Dict[str, Any]) -> Dict:
        """修改密码"""
        try:
            user_id = params.get('user_id')
            old_password = params.get('old_password', '')
            new_password = params.get('new_password', '')

            if not user_id:
                return {'success': False, 'error': '缺少 user_id'}
            if not old_password:
                return {'success': False, 'error': '请输入原密码'}
            if not new_password:
                return {'success': False, 'error': '请输入新密码'}
            if len(new_password) < 6:
                return {'success': False, 'error': '新密码长度至少6位'}

            user = UserDB.get_by_id(user_id)
            if not user:
                return {'success': False, 'error': '用户不存在'}

            # 验证原密码（ROOT 用户可以跳过验证）
            if user.role != UserRole.ROOT:
                if not user.check_password(old_password):
                    return {'success': False, 'error': '原密码错误'}

            # 设置新密码
            user.set_password(new_password)
            UserDB.update(user)

            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def on_method_verify_password(self, params: Dict[str, Any]) -> Dict:
        """验证密码（登录用）"""
        try:
            username = params.get('username', '').strip()
            password = params.get('password', '')

            if not username:
                return {'success': False, 'error': '请输入用户名'}
            if not password:
                return {'success': False, 'error': '请输入密码'}

            user = UserDB.verify_login(username, password)
            if not user:
                return {'success': False, 'error': '用户名或密码错误'}

            return {
                'success': True,
                'user': user.to_dict(),
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ============ 健康检查 ============

    def on_method_health_check(self, params: Dict[str, Any]) -> Dict:
        """健康检查"""
        try:
            user_count = UserDB.count()
            return {
                'status': 'healthy',
                'user_count': user_count,
            }
        except Exception as e:
            return {'status': 'error', 'error': str(e)}