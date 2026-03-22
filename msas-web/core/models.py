from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import hashlib
from werkzeug.security import generate_password_hash, check_password_hash
from enum import IntEnum

db = SQLAlchemy()


class UserRole(IntEnum):
    """用户角色枚举"""
    GUEST = 0      # 游客 - 未登录用户
    USER = 1       # 普通用户
    ADMIN = 2      # 管理员
    ROOT = 3       # 超级管理员


# 角色名称映射
ROLE_NAMES = {
    UserRole.GUEST: '游客',
    UserRole.USER: '用户',
    UserRole.ADMIN: '管理员',
    UserRole.ROOT: '超级管理员'
}


class User(db.Model):
    """用户模型"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)  # 密码哈希，不存储明文
    role = db.Column(db.Integer, default=UserRole.USER, nullable=False)  # 用户角色
    email = db.Column(db.String(120), unique=True, nullable=True)  # 邮箱（可选）
    is_active = db.Column(db.Boolean, default=True)  # 账户是否激活
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)  # 最后登录时间

    def __repr__(self):
        return f'<User {self.username} ({ROLE_NAMES.get(self.role, "未知")})>'

    def set_password(self, password):
        """设置密码（自动哈希）"""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """验证密码"""
        return check_password_hash(self.password_hash, password)

    @property
    def role_name(self):
        """获取角色名称"""
        return ROLE_NAMES.get(self.role, '未知')

    def has_permission(self, required_role):
        """检查是否具有指定权限
        
        Args:
            required_role: 需要的角色 (UserRole枚举值)
        
        Returns:
            bool: 是否具有权限
        """
        return self.role >= required_role

    def is_admin_or_above(self):
        """是否是管理员或以上"""
        return self.role >= UserRole.ADMIN

    def is_root(self):
        """是否是超级管理员"""
        return self.role == UserRole.ROOT

    def to_dict(self, include_sensitive=False):
        """转换为字典
        
        Args:
            include_sensitive: 是否包含敏感信息
        """
        result = {
            'id': self.id,
            'username': self.username,
            'role': self.role,
            'role_name': self.role_name,
            'email': self.email,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }
        if include_sensitive:
            result['updated_at'] = self.updated_at.isoformat() if self.updated_at else None
        return result


class UserSession(db.Model):
    """用户会话模型 - 用于管理登录状态"""
    __tablename__ = 'user_sessions'

    id = db.Column(db.Integer, primary_key=True)
    session_token = db.Column(db.String(128), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    ip_address = db.Column(db.String(45))  # IPv6最长45字符
    user_agent = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)  # 过期时间
    is_active = db.Column(db.Boolean, default=True)

    # 关系
    user = db.relationship('User', backref=db.backref('sessions', lazy='dynamic'))

    def __repr__(self):
        return f'<UserSession {self.user_id} - {self.session_token[:8]}...>'

    @staticmethod
    def generate_token():
        """生成会话令牌"""
        import secrets
        return secrets.token_hex(32)

    def is_expired(self):
        """检查会话是否过期"""
        from datetime import datetime
        return datetime.utcnow() > self.expires_at

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'session_token': self.session_token[:8] + '...',  # 只显示前8位
            'user_id': self.user_id,
            'ip_address': self.ip_address,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'is_active': self.is_active
        }

class Video(db.Model):
    """视频模型"""
    __tablename__ = 'videos'

    id = db.Column(db.Integer, primary_key=True)
    hash = db.Column(db.String(64), unique=True, nullable=False, index=True)  # 视频唯一标识符
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    url = db.Column(db.String(500), nullable=False)  # 视频URL
    thumbnail = db.Column(db.String(500))  # 视频缩略图URL
    duration = db.Column(db.Integer)  # 视频时长(秒)
    file_size = db.Column(db.BigInteger)  # 文件大小(字节)
    view_count = db.Column(db.Integer, default=0)  # 播放次数
    like_count = db.Column(db.Integer, default=0)  # 点赞数
    download_count = db.Column(db.Integer, default=0)  # 下载次数
    priority = db.Column(db.Integer, default=0)  # 优先级，数值越大优先级越高
    min_role = db.Column(db.Integer, default=UserRole.GUEST, nullable=False)  # 最低访问权限要求
    is_downloaded = db.Column(db.Boolean, default=False)  # 是否已下载到本地
    local_path = db.Column(db.String(500))  # 本地存储路径
    library_id = db.Column(db.Integer, db.ForeignKey('video_libraries.id'))  # 所属视频库，NULL表示主数据库
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    tags = db.relationship('VideoTag', back_populates='video', cascade='all, delete-orphan')
    user_interactions = db.relationship('UserInteraction', back_populates='video', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Video {self.title}>'

    @staticmethod
    def generate_hash(video_url):
        """生成视频唯一hash"""
        return hashlib.sha256(video_url.encode('utf-8')).hexdigest()

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'hash': self.hash,
            'title': self.title,
            'description': self.description,
            'url': self.url,
            'thumbnail': self.thumbnail,
            'duration': self.duration,
            'file_size': self.file_size,
            'view_count': self.view_count,
            'like_count': self.like_count,
            'download_count': self.download_count,
            'priority': self.priority,
            'min_role': self.min_role,
            'min_role_name': ROLE_NAMES.get(self.min_role, '未知'),
            'is_downloaded': self.is_downloaded,
            'local_path': self.local_path,
            'tags': [vt.tag.to_dict() for vt in self.tags if vt.tag is not None],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class Tag(db.Model):
    """标签模型 - 支持多视频库独立标签体系"""
    __tablename__ = 'tags'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, index=True)  # 标签名称（同一路径下唯一）
    path = db.Column(db.String(200), nullable=False, index=True)  # 完整路径，如 /动物/狗/哈士奇
    category = db.Column(db.String(50))  # 标签分类：如 "类型", "作者", "地区" 等
    parent_id = db.Column(db.Integer, db.ForeignKey('tags.id'), nullable=True)  # 父标签ID，支持多级
    library_id = db.Column(db.Integer, db.ForeignKey('video_libraries.id'), nullable=True)  # 视频库ID，null表示全局标签
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 关系
    videos = db.relationship('VideoTag', back_populates='tag', cascade='all, delete-orphan')
    parent = db.relationship('Tag', remote_side=[id], backref='children')  # 自关联：父标签 / 子标签
    library = db.relationship('VideoLibrary', backref='tags')  # 视频库关系

    # 唯一约束：同一视频库下路径唯一
    __table_args__ = (db.UniqueConstraint('path', 'library_id', name='_path_library_uc'),)

    def __repr__(self):
        return f'<Tag {self.path}>'

    def calculate_path(self):
        """计算完整路径"""
        if self.parent:
            parent_path = self.parent.calculate_path() if self.parent.path == '/' else self.parent.path
            self.path = f"{parent_path}/{self.name}" if parent_path != '/' else f"/{self.name}"
        else:
            self.path = f"/{self.name}"
        return self.path

    def video_count(self):
        """获取实际存在的视频数量（包含所有子标签的视频）"""
        # 统计当前标签及其所有子标签的视频数量
        tag_ids = self.get_all_child_ids()
        return VideoTag.query.filter(VideoTag.tag_id.in_(tag_ids)).count()

    def get_all_child_ids(self):
        """获取当前标签及所有子标签的ID列表"""
        ids = [self.id]
        for child in self.children:
            ids.extend(child.get_all_child_ids())
        return ids

    def get_all_parent_ids(self):
        """获取所有父标签ID列表（用于继承逻辑）"""
        ids = []
        if self.parent:
            ids.append(self.parent.id)
            ids.extend(self.parent.get_all_parent_ids())
        return ids

    def to_dict(self, include_children=False):
        result = {
            'id': self.id,
            'name': self.name,
            'path': self.path,
            'category': self.category,
            'parent_id': self.parent_id,
            'library_id': self.library_id,
            'video_count': self.video_count()
        }
        if include_children:
            result['children'] = [child.to_dict(include_children=True) for child in self.children]
        return result


class VideoTag(db.Model):
    """视频-标签关联表"""
    __tablename__ = 'video_tags'

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey('videos.id'), nullable=False)
    tag_id = db.Column(db.Integer, db.ForeignKey('tags.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 关系
    video = db.relationship('Video', back_populates='tags')
    tag = db.relationship('Tag', back_populates='videos')

    # 唯一约束，防止重复关联
    __table_args__ = (db.UniqueConstraint('video_id', 'tag_id', name='_video_tag_uc'),)


class UserInteraction(db.Model):
    """用户交互记录模型"""
    __tablename__ = 'user_interactions'

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey('videos.id'), nullable=False)
    user_session = db.Column(db.String(100), nullable=False)  # 用户会话ID（简单模拟用户）
    interaction_type = db.Column(db.String(20), nullable=False)  # 交互类型: view, like, download, share, favorite
    interaction_score = db.Column(db.Float, default=0.0)  # 交互评分（用于推荐算法）
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 关系
    video = db.relationship('Video', back_populates='user_interactions')

    def __repr__(self):
        return f'<UserInteraction {self.user_session} - {self.interaction_type}>'


class UserPreference(db.Model):
    """用户偏好模型"""
    __tablename__ = 'user_preferences'

    id = db.Column(db.Integer, primary_key=True)
    user_session = db.Column(db.String(100), nullable=False, index=True)
    tag_id = db.Column(db.Integer, db.ForeignKey('tags.id'), nullable=False)
    preference_score = db.Column(db.Float, default=1.0)  # 偏好评分，越高表示越喜欢
    interaction_count = db.Column(db.Integer, default=0)  # 交互次数
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<UserPreference {self.user_session} - {self.preference_score}>'


class Playlist(db.Model):
    """播放列表模型"""
    __tablename__ = 'playlists'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    user_session = db.Column(db.String(100), nullable=False, index=True)  # 用户会话ID
    is_public = db.Column(db.Boolean, default=False)  # 是否公开
    thumbnail = db.Column(db.String(500))  # 播放列表缩略图
    total_duration = db.Column(db.Integer, default=0)  # 总时长（秒）
    video_count = db.Column(db.Integer, default=0)  # 视频数量
    play_count = db.Column(db.Integer, default=0)  # 播放次数
    shuffle_play = db.Column(db.Boolean, default=False)  # 随机播放
    repeat_mode = db.Column(db.String(20), default='none')  # 重复模式: none, all, one
    current_video_id = db.Column(db.Integer)  # 当前播放的视频ID
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    items = db.relationship('PlaylistItem', back_populates='playlist', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Playlist {self.name}>'

    def update_video_count(self):
        """更新视频数量"""
        self.video_count = len([item for item in self.items if item.video is not None])
        self.total_duration = sum(item.video.duration for item in self.items if item.video and item.video.duration)

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'user_session': self.user_session,
            'is_public': self.is_public,
            'thumbnail': self.thumbnail,
            'total_duration': self.total_duration,
            'video_count': self.video_count,
            'play_count': self.play_count,
            'shuffle_play': self.shuffle_play,
            'repeat_mode': self.repeat_mode,
            'current_video_id': self.current_video_id,
            'items': [item.to_dict() for item in self.items if item.video is not None],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class PlaylistItem(db.Model):
    """播放列表项模型"""
    __tablename__ = 'playlist_items'

    id = db.Column(db.Integer, primary_key=True)
    playlist_id = db.Column(db.Integer, db.ForeignKey('playlists.id'), nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('videos.id'), nullable=False)
    position = db.Column(db.Integer, nullable=False)  # 播放顺序
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 关系
    playlist = db.relationship('Playlist', back_populates='items')
    video = db.relationship('Video')

    # 唯一约束，防止重复添加
    __table_args__ = (
        db.UniqueConstraint('playlist_id', 'video_id', name='_playlist_video_uc'),
    )

    def __repr__(self):
        return f'<PlaylistItem {self.playlist_id} - {self.video_id}>'

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'playlist_id': self.playlist_id,
            'video_id': self.video_id,
            'video': self.video.to_dict() if self.video else None,
            'position': self.position,
            'added_at': self.added_at.isoformat() if self.added_at else None
        }


# ==================== 多数据库视频库管理模型 ====================

class VideoLibrary(db.Model):
    """视频库模型 - 每个视频库对应一个独立的数据库"""
    __tablename__ = 'video_libraries'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    db_path = db.Column(db.String(500), nullable=False)  # 数据库文件目录
    db_file = db.Column(db.String(200), nullable=False)  # 数据库文件名
    is_active = db.Column(db.Boolean, default=True)  # 是否激活
    config = db.Column(db.JSON)  # 额外配置
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    permissions = db.relationship('LibraryPermission', back_populates='library', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<VideoLibrary {self.name}>'

    @property
    def full_db_path(self):
        """获取完整的数据库文件路径"""
        import os
        return os.path.join(self.db_path, self.db_file)

    def to_dict(self, include_stats=False):
        """转换为字典"""
        result = {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'db_path': self.db_path,
            'db_file': self.db_file,
            'is_active': self.is_active,
            'config': self.config,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        if include_stats:
            # 这里不直接查询，因为每个库是独立的数据库
            result['video_count'] = 0
            result['user_count'] = len([p for p in self.permissions if p.user_id])
        return result


class LibraryPermission(db.Model):
    """视频库权限模型"""
    __tablename__ = 'library_permissions'

    id = db.Column(db.Integer, primary_key=True)
    library_id = db.Column(db.Integer, db.ForeignKey('video_libraries.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # 用户ID，为NULL表示用户组权限
    group_id = db.Column(db.Integer, db.ForeignKey('library_user_groups.id'))  # 用户组ID
    role = db.Column(db.String(20), nullable=False, default='user')  # admin 或 user
    access_level = db.Column(db.String(20), nullable=False, default='read')  # full, read, write, custom
    permissions = db.Column(db.JSON)  # 详细权限配置
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    # 关系
    library = db.relationship('VideoLibrary', back_populates='permissions')
    user = db.relationship('User', foreign_keys=[user_id])
    group = db.relationship('LibraryUserGroup', back_populates='permissions')

    # 唯一约束
    __table_args__ = (
        db.UniqueConstraint('library_id', 'user_id', name='_library_user_uc'),
        db.UniqueConstraint('library_id', 'group_id', name='_library_group_uc'),
    )

    def __repr__(self):
        return f'<LibraryPermission library={self.library_id} user={self.user_id}>'

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'library_id': self.library_id,
            'user_id': self.user_id,
            'group_id': self.group_id,
            'role': self.role,
            'access_level': self.access_level,
            'permissions': self.permissions,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'user': {'id': self.user.id, 'username': self.user.username} if self.user else None,
            'group': {'id': self.group.id, 'name': self.group.name} if self.group else None
        }


class LibraryUserGroup(db.Model):
    """用户组模型"""
    __tablename__ = 'library_user_groups'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 关系
    permissions = db.relationship('LibraryPermission', back_populates='group', cascade='all, delete-orphan')
    members = db.relationship('LibraryUserGroupMember', back_populates='group', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<LibraryUserGroup {self.name}>'

    def to_dict(self, include_members=False):
        """转换为字典"""
        result = {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'member_count': len(self.members),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        if include_members:
            result['members'] = [m.user.to_dict() for m in self.members if m.user]
        return result


class LibraryUserGroupMember(db.Model):
    """用户组成员关联表"""
    __tablename__ = 'library_user_group_members'

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('library_user_groups.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 关系
    group = db.relationship('LibraryUserGroup', back_populates='members')
    user = db.relationship('User')

    # 唯一约束
    __table_args__ = (
        db.UniqueConstraint('group_id', 'user_id', name='_group_user_uc'),
    )

    def __repr__(self):
        return f'<LibraryUserGroupMember group={self.group_id} user={self.user_id}>'


class LibraryAuditLog(db.Model):
    """权限变更审计日志"""
    __tablename__ = 'library_audit_log'

    id = db.Column(db.Integer, primary_key=True)
    library_id = db.Column(db.Integer, db.ForeignKey('video_libraries.id'))
    target_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(20), nullable=False)  # create, update, delete
    old_value = db.Column(db.JSON)
    new_value = db.Column(db.JSON)
    operator_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<LibraryAuditLog {self.action} library={self.library_id}>'

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'library_id': self.library_id,
            'target_user_id': self.target_user_id,
            'action': self.action,
            'old_value': self.old_value,
            'new_value': self.new_value,
            'operator_id': self.operator_id,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class SharedWatchSession(db.Model):
    """共享观看会话模型 - 一对一视频同步"""
    __tablename__ = 'shared_watch_sessions'

    id = db.Column(db.Integer, primary_key=True)
    share_code = db.Column(db.String(16), unique=True, nullable=False, index=True)  # 分享码（URL中的标识）
    video_hash = db.Column(db.String(64), nullable=False, index=True)  # 视频hash
    creator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # 创建者ID
    invitee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # 被邀请者ID（接受后设置）

    # 视频播放状态
    current_time = db.Column(db.Float, default=0.0)  # 当前播放时间（秒）
    is_playing = db.Column(db.Boolean, default=False)  # 是否正在播放

    # 状态
    status = db.Column(db.String(20), default='pending')  # pending, active, ended
    last_sync_at = db.Column(db.DateTime)  # 最后同步时间

    # 时间戳（用于网络延迟补偿）
    client_timestamp = db.Column(db.String(50))  # 客户端发送时的时间戳（ISO格式）
    server_timestamp = db.Column(db.String(50))  # 服务器接收时的时间戳（ISO格式）

    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)  # 过期时间
    ended_at = db.Column(db.DateTime)  # 结束时间

    # 关系
    creator = db.relationship('User', foreign_keys=[creator_id], backref='created_sessions')
    invitee = db.relationship('User', foreign_keys=[invitee_id], backref='invited_sessions')

    def __repr__(self):
        return f'<SharedWatchSession {self.share_code} video={self.video_hash}>'

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'share_code': self.share_code,
            'video_hash': self.video_hash,
            'creator_id': self.creator_id,
            'invitee_id': self.invitee_id,
            'current_time': self.current_time,
            'is_playing': self.is_playing,
            'status': self.status,
            'last_sync_at': self.last_sync_at.isoformat() if self.last_sync_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'ended_at': self.ended_at.isoformat() if self.ended_at else None
        }


