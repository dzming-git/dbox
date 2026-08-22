"""
用户认证服务
提供用户注册、登录、会话管理等功能
"""
from datetime import datetime, timedelta
from flask import session, request, g
from core.models import db, User, UserSession, UserRole
import secrets
from liblog import get_service_logger
log = get_service_logger('dbox-web')

# 会话配置
SESSION_LIFETIME = timedelta(days=7)  # 会话有效期7天
SESSION_TOKEN_KEY = 'auth_token'  # session中存储token的key


class AuthService:
    """用户认证服务类"""

    @staticmethod
    def register(username, password, email=None, role=UserRole.USER):
        """注册新用户
        
        Args:
            username: 用户名
            password: 密码（明文，会被自动哈希）
            email: 邮箱（可选）
            role: 用户角色（默认为普通用户）
        
        Returns:
            tuple: (success: bool, message: str, user: User|None)
        """
        try:
            # 检查用户名是否已存在
            if User.query.filter_by(username=username).first():
                return False, '用户名已存在', None

            # 检查邮箱是否已存在
            if email and User.query.filter_by(email=email).first():
                return False, '邮箱已被注册', None

            # 创建用户
            user = User(
                username=username,
                email=email,
                role=role
            )
            user.set_password(password)

            db.session.add(user)
            db.session.commit()

            log.runtime('INFO', f"新用户注册成功: {username}, 角色: {user.role_name}")
            return True, '注册成功', user

        except Exception as e:
            db.session.rollback()
            log.debug('ERROR', f"用户注册失败: {e}")
            return False, f'注册失败: {str(e)}', None

    @staticmethod
    def login(username, password, remember=True):
        """用户登录

        Args:
            username: 用户名
            password: 密码
            remember: 是否记住登录（延长会话时间，默认为True，保存长久token）

        Returns:
            tuple: (success: bool, message: str, user: User|None)
        """
        try:
            # 查找用户
            user = User.query.filter_by(username=username).first()
            if not user:
                return False, '用户名或密码错误', None

            # 检查账户状态
            if not user.is_active:
                return False, '账户已被禁用', None

            # 验证密码
            if not user.check_password(password):
                return False, '用户名或密码错误', None

            # 创建会话 - 默认使用长久的token（28天）
            session_lifetime = SESSION_LIFETIME * 4 if remember else SESSION_LIFETIME
            session_token = UserSession.generate_token()
            expires_at = datetime.utcnow() + session_lifetime

            user_session = UserSession(
                session_token=session_token,
                user_id=user.id,
                ip_address=request.remote_addr if request else None,
                user_agent=request.user_agent.string[:500] if request and request.user_agent else None,
                expires_at=expires_at
            )

            db.session.add(user_session)

            # 更新最后登录时间
            user.last_login = datetime.utcnow()

            db.session.commit()

            # 存储token到flask session
            session[SESSION_TOKEN_KEY] = session_token
            session.permanent = True  # 默认启用长久session

            log.runtime('INFO', f"用户登录成功: {username}, IP: {user_session.ip_address}")
            return True, '登录成功', user

        except Exception as e:
            db.session.rollback()
            log.debug('ERROR', f"用户登录失败: {e}")
            return False, f'登录失败: {str(e)}', None

    @staticmethod
    def logout():
        """用户登出
        
        Returns:
            bool: 是否成功
        """
        try:
            session_token = session.get(SESSION_TOKEN_KEY)
            if session_token:
                # 标记会话为无效
                user_session = UserSession.query.filter_by(
                    session_token=session_token
                ).first()
                if user_session:
                    user_session.is_active = False
                    db.session.commit()
                    log.runtime('INFO', f"用户登出: user_id={user_session.user_id}")

            # 清除session
            session.pop(SESSION_TOKEN_KEY, None)
            return True

        except Exception as e:
            log.debug('ERROR', f"用户登出失败: {e}")
            return False

    @staticmethod
    def get_current_user():
        """获取当前登录用户
        
        Returns:
            User|None: 当前用户对象，未登录返回None
        """
        # 先尝试从g对象获取（避免重复查询）
        if hasattr(g, 'current_user'):
            return g.current_user

        session_token = session.get(SESSION_TOKEN_KEY)
        if not session_token:
            return None

        try:
            # 查找有效的会话
            user_session = UserSession.query.filter_by(
                session_token=session_token,
                is_active=True
            ).first()

            if not user_session:
                session.pop(SESSION_TOKEN_KEY, None)
                return None

            # 检查是否过期
            if user_session.is_expired():
                user_session.is_active = False
                db.session.commit()
                session.pop(SESSION_TOKEN_KEY, None)
                return None

            # 获取用户
            user = User.query.get(user_session.user_id)
            if not user or not user.is_active:
                return None

            # 缓存到g对象
            g.current_user = user
            return user

        except Exception as e:
            log.debug('ERROR', f"获取当前用户失败: {e}")
            return None

    @staticmethod
    def get_user_by_token(token):
        """通过 Authorization: Bearer <session_token> 中的 session_token 反查登录用户。

        前端登录后将后端返回的 session_token 存入 localStorage，并以
        `Authorization: Bearer <session_token>` 发送；该 token 并非 JWT，
        而是 UserSession.session_token。此处直接用它反查有效用户。
        """
        if not token:
            return None
        try:
            if hasattr(g, 'current_user') and getattr(g, 'current_user', None):
                return g.current_user
            user_session = UserSession.query.filter_by(
                session_token=token,
                is_active=True
            ).first()
            if not user_session or user_session.is_expired():
                return None
            user = User.query.get(user_session.user_id)
            if not user or not user.is_active:
                return None
            g.current_user = user
            return user
        except Exception as e:
            log.debug('ERROR', f"通过 token 获取用户失败: {e}")
            return None

    @staticmethod
    def get_current_role():
        """获取当前用户的角色
        
        未登录返回游客角色
        
        Returns:
            UserRole: 当前用户角色
        """
        user = AuthService.get_current_user()
        return user.role if user else UserRole.GUEST

    @staticmethod
    def is_logged_in():
        """检查是否已登录
        
        Returns:
            bool: 是否已登录
        """
        return AuthService.get_current_user() is not None

    @staticmethod
    def is_admin():
        """检查当前用户是否是管理员或以上
        
        Returns:
            bool: 是否是管理员
        """
        user = AuthService.get_current_user()
        return user is not None and user.is_admin_or_above()

    @staticmethod
    def is_root():
        """检查当前用户是否是超级管理员
        
        Returns:
            bool: 是否是超级管理员
        """
        user = AuthService.get_current_user()
        return user is not None and user.is_root()

    @staticmethod
    def check_permission(required_role):
        """检查当前用户是否具有指定权限
        
        Args:
            required_role: 需要的角色
        
        Returns:
            bool: 是否具有权限
        """
        current_role = AuthService.get_current_role()
        return current_role <= required_role

    @staticmethod
    def change_password(user_id, old_password, new_password):
        """修改密码
        
        Args:
            user_id: 用户ID
            old_password: 旧密码
            new_password: 新密码
        
        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            user = User.query.get(user_id)
            if not user:
                return False, '用户不存在'

            # 验证旧密码
            if not user.check_password(old_password):
                return False, '旧密码错误'

            # 设置新密码
            user.set_password(new_password)
            db.session.commit()

            log.runtime('INFO', f"用户修改密码成功: {user.username}")
            return True, '密码修改成功'

        except Exception as e:
            db.session.rollback()
            log.debug('ERROR', f"修改密码失败: {e}")
            return False, f'修改密码失败: {str(e)}'

    @staticmethod
    def cleanup_expired_sessions():
        """清理过期的会话
        
        Returns:
            int: 清理的会话数量
        """
        try:
            expired_sessions = UserSession.query.filter(
                UserSession.expires_at < datetime.utcnow()
            ).all()

            count = len(expired_sessions)
            for s in expired_sessions:
                s.is_active = False

            db.session.commit()
            if count > 0:
                log.runtime('INFO', f"清理过期会话: {count}个")
            return count

        except Exception as e:
            log.debug('ERROR', f"清理过期会话失败: {e}")
            return 0


def init_root_user():
    """初始化超级管理员账户
    
    如果不存在root用户，则创建一个默认的root账户
    root账号是唯一且最高权限的账户
    """
    try:
        # 检查是否已存在root用户
        root_user = User.query.filter_by(role=UserRole.ROOT).first()
        if root_user:
            log.runtime('INFO', "超级管理员账户已存在")
            return

        # 检查是否已有名为root的用户（非ROOT角色）
        existing_root_name = User.query.filter_by(username='root').first()
        if existing_root_name:
            # 如果存在同名用户但不是ROOT角色，将其升级为ROOT
            existing_root_name.role = UserRole.ROOT
            existing_root_name.set_password('dzmingroot')
            db.session.commit()
            log.debug('WARN', "已将现有root用户升级为超级管理员，密码已重置为: dzmingroot")
            return

        # 创建默认root用户
        root_user = User(
            username='root',
            role=UserRole.ROOT,
            email=None
        )
        root_user.set_password('dzmingroot')  # 指定密码

        db.session.add(root_user)
        db.session.commit()

        log.debug('WARN', "已创建默认超级管理员账户: root / dzmingroot")

    except Exception as e:
        db.session.rollback()
        log.debug('ERROR', f"初始化root用户失败: {e}")
