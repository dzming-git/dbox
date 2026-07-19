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
    favorite_count = db.Column(db.Integer, default=0)  # 收藏数
    download_count = db.Column(db.Integer, default=0)  # 下载次数
    priority = db.Column(db.Integer, default=0)  # 优先级，数值越大优先级越高
    min_role = db.Column(db.Integer, default=UserRole.GUEST, nullable=False)  # 最低访问权限要求
    is_downloaded = db.Column(db.Boolean, default=False)  # 是否已下载到本地
    local_path = db.Column(db.String(500))  # 本地存储路径
    file_name = db.Column(db.String(500))  # 文件名（仅作为属性，绝不作为视频唯一标识/key）
    library_id = db.Column(db.Integer, db.ForeignKey('video_libraries.id'))  # 所属视频库，NULL表示主数据库
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    tags = db.relationship('VideoTag', back_populates='video', cascade='all, delete-orphan')
    user_interactions = db.relationship('UserInteraction', back_populates='video', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Video {self.title}>'

    # 用于内容指纹的采样块大小（4MB）
    _HASH_CHUNK = 4 * 1024 * 1024

    @staticmethod
    def generate_hash(video_path):
        """生成视频唯一指纹（与文件名/路径无关，仅依赖文件内容）。

        采用 文件大小 + 头部4MB + 尾部4MB 的稳定指纹，避免读取整个
        （可能数十 GB 的）视频文件。文件名只作为属性，绝不作为标识。
        """
        import os
        try:
            size = os.path.getsize(video_path)
            h = hashlib.sha256()
            h.update(str(size).encode('utf-8'))
            with open(video_path, 'rb') as f:
                h.update(f.read(Video._HASH_CHUNK))
                if size > Video._HASH_CHUNK * 2:
                    f.seek(max(Video._HASH_CHUNK, size - Video._HASH_CHUNK))
                    h.update(f.read(Video._HASH_CHUNK))
                else:
                    h.update(f.read())
            return h.hexdigest()
        except (OSError, IOError):
            # 文件不可读时回退到路径哈希，保证不崩溃（此分支不应成为常态）
            return hashlib.sha256(video_path.encode('utf-8')).hexdigest()

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'hash': self.hash,
            'title': self.title,
            'description': self.description,
            'url': f'/api/videos/{self.id}/play',
            'thumbnail': self.thumbnail,
            'duration': self.duration,
            'file_size': self.file_size,
            'view_count': self.view_count,
            'like_count': self.like_count,
            'favorite_count': self.favorite_count,
            'download_count': self.download_count,
            'priority': self.priority,
            'min_role': self.min_role,
            'min_role_name': ROLE_NAMES.get(self.min_role, '未知'),
            'is_downloaded': self.is_downloaded,
            'local_path': self.local_path,
            'file_name': self.file_name,
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


class VideoMarker(db.Model):
    """用户标记的精彩片段时间戳（按个人会话区分，不覆盖文件名/标题）。"""
    __tablename__ = 'video_markers'

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey('videos.id'), nullable=False, index=True)
    user_session = db.Column(db.String(100), nullable=False, index=True)
    time_seconds = db.Column(db.Float, nullable=False)
    note = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    video = db.relationship('Video', backref='markers')

    def to_dict(self):
        return {
            'id': self.id,
            'video_id': self.video_id,
            'time_seconds': self.time_seconds,
            'note': self.note,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<VideoMarker {self.video_id} @ {self.time_seconds}s>'


class FavoriteCollection(db.Model):
    """用户收藏夹分组模型"""
    __tablename__ = 'favorite_collections'

    id = db.Column(db.Integer, primary_key=True)
    user_session = db.Column(db.String(100), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    position = db.Column(db.Integer, default=0)  # 排序位置
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship(
        'CollectionVideo', back_populates='collection',
        cascade='all, delete-orphan'
    )

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'position': self.position,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'video_count': len(self.items),
        }


class CollectionVideo(db.Model):
    """收藏夹与资源的关联表（视频 / 漫画地位等同，通过 item_type 区分）"""
    __tablename__ = 'collection_videos'

    id = db.Column(db.Integer, primary_key=True)
    collection_id = db.Column(db.Integer, db.ForeignKey('favorite_collections.id'), nullable=False)
    user_session = db.Column(db.String(100), nullable=False, index=True)
    item_type = db.Column(db.String(20), nullable=False, default='video')  # 'video' | 'comic'
    video_id = db.Column(db.Integer, db.ForeignKey('videos.id'), nullable=True)
    comic_id = db.Column(db.Integer, db.ForeignKey('comics.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    collection = db.relationship('FavoriteCollection', back_populates='items')
    comic = db.relationship('Comic', foreign_keys=[comic_id])

    def to_dict(self):
        return {
            'id': self.id,
            'collection_id': self.collection_id,
            'item_type': self.item_type,
            'video_id': self.video_id,
            'comic_id': self.comic_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class MediaCollection(db.Model):
    """合集（独立于收藏夹）：用户把视频/漫画按主题归组，支持排序与多归属。"""
    __tablename__ = 'media_collections'

    id = db.Column(db.Integer, primary_key=True)
    owner_key = db.Column(db.String(64), nullable=False, index=True)  # current_interaction_key
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    is_public = db.Column(db.Boolean, default=False)
    position = db.Column(db.Integer, default=0)  # 合集之间的排序
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self, item_count=None):
        return {
            'id': self.id,
            'owner_key': self.owner_key,
            'name': self.name,
            'description': self.description,
            'is_public': self.is_public,
            'position': self.position,
            'item_count': item_count if item_count is not None else 0,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class MediaCollectionItem(db.Model):
    """合集项（视频/漫画）。一个资源可同时属于多个合集。"""
    __tablename__ = 'media_collection_items'

    id = db.Column(db.Integer, primary_key=True)
    collection_id = db.Column(db.Integer, db.ForeignKey('media_collections.id', ondelete='CASCADE'), nullable=False, index=True)
    owner_key = db.Column(db.String(64), nullable=False, index=True)
    item_type = db.Column(db.String(16), nullable=False)  # 'video' | 'comic'
    item_hash = db.Column(db.String(64), nullable=False)    # 资源身份用 hash（与路径解耦）
    position = db.Column(db.Integer, default=0)             # 合集内排序
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('collection_id', 'item_type', 'item_hash', name='uq_media_collection_item'),
    )

    def to_dict(self, media=None):
        return {
            'id': self.id,
            'collection_id': self.collection_id,
            'item_type': self.item_type,
            'item_hash': self.item_hash,
            'position': self.position,
            'added_at': self.created_at.isoformat() if self.created_at else None,
            'media': media,
        }


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
    db_path = db.Column(db.String(500), nullable=False)  # 数据库文件子目录（相对于 data/），如 "libraries"
    db_file = db.Column(db.String(200), nullable=False)  # 数据库文件名，如 "xxx_123456.db"
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
        """获取完整的数据库文件绝对路径（运行时动态拼接，不依赖存储的绝对路径）"""
        import os
        # 优先从环境变量获取 data 目录
        data_dir = os.environ.get('DPLAYER_DATA_DIR')
        if not data_dir:
            # 兼容旧数据：db_path 可能是绝对路径
            # db_path = 'C:\\...' 表示旧数据，直接使用
            # db_path = 'libraries' 表示新数据，相对路径
            if os.path.isabs(self.db_path):
                return os.path.join(self.db_path, self.db_file)
            # db_path = 'libraries' 相对路径：相对于项目根目录的 data/
            # 正确计算：main.py 在 src/web/，向上两级到项目根目录
            _src_web = os.path.dirname(os.path.abspath(__file__))  # src/web/core
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(_src_web)))  # Dplayer2.0/
            data_dir = os.path.join(project_root, 'data')
            return os.path.join(data_dir, self.db_path, self.db_file)
        # 环境变量方式
        if os.path.isabs(self.db_path):
            sub = os.path.basename(self.db_path.rstrip('/\\'))
            return os.path.join(data_dir, sub, self.db_file)
        else:
            return os.path.join(data_dir, self.db_path, self.db_file)

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


# ==================== 漫画模式（Comic Mode）数据模型 ====================
class Comic(db.Model):
    """漫画模型 - 一本漫画 = 磁盘上一个扁平的图片文件夹"""
    __tablename__ = 'comics'

    id = db.Column(db.Integer, primary_key=True)
    hash = db.Column(db.String(64), unique=True, nullable=False, index=True)  # 内容指纹（与路径解耦）
    title = db.Column(db.String(300), nullable=False)
    folder_path = db.Column(db.String(600))            # 漫画文件夹本地路径
    cover_path = db.Column(db.String(600))             # 封面（第一页）本地路径
    library_id = db.Column(db.Integer, db.ForeignKey('video_libraries.id'), nullable=True)
    page_count = db.Column(db.Integer, default=0)
    like_count = db.Column(db.Integer, default=0)
    favorite_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    pages = db.relationship('ComicPage', back_populates='comic', cascade='all, delete-orphan',
                            order_by='ComicPage.page_index')
    interactions = db.relationship('ComicInteraction', back_populates='comic', cascade='all, delete-orphan')
    progress = db.relationship('ComicProgress', back_populates='comic', cascade='all, delete-orphan')

    @staticmethod
    def generate_hash(folder_path, page_paths):
        """基于图片文件名 + 文件大小的内容指纹（与文件夹路径解耦，重命名后仍可匹配）。"""
        import os
        h = hashlib.sha256()
        try:
            h.update(str(len(page_paths)).encode('utf-8'))
            for p in sorted(page_paths, key=lambda x: os.path.basename(x).lower()):
                h.update(os.path.basename(p).lower().encode('utf-8'))
                try:
                    h.update(str(os.path.getsize(p)).encode('utf-8'))
                except OSError:
                    pass
            # 混入文件夹名，避免两套图片集合完全相同被误判为同一本
            h.update(os.path.basename(folder_path.rstrip(os.sep)).lower().encode('utf-8'))
        except Exception:
            return hashlib.sha256(folder_path.encode('utf-8')).hexdigest()
        return h.hexdigest()

    def to_dict(self):
        return {
            'id': self.id,
            'hash': self.hash,
            'title': self.title,
            'page_count': self.page_count,
            'library_id': self.library_id,
            'like_count': self.like_count,
            'favorite_count': self.favorite_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class ComicPage(db.Model):
    """漫画页面 - 一页图片"""
    __tablename__ = 'comic_pages'

    id = db.Column(db.Integer, primary_key=True)
    comic_id = db.Column(db.Integer, db.ForeignKey('comics.id'), nullable=False, index=True)
    page_index = db.Column(db.Integer, nullable=False)   # 从 0 开始
    file_path = db.Column(db.String(600), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    comic = db.relationship('Comic', back_populates='pages')

    __table_args__ = (db.UniqueConstraint('comic_id', 'page_index', name='_comic_page_uc'),)


class ComicInteraction(db.Model):
    """漫画交互（点赞/收藏/不喜欢），结构对齐 videos 的 user_interactions"""
    __tablename__ = 'comic_interactions'

    id = db.Column(db.Integer, primary_key=True)
    comic_id = db.Column(db.Integer, db.ForeignKey('comics.id'), nullable=False, index=True)
    user_session = db.Column(db.String(100), nullable=False)
    interaction_type = db.Column(db.String(20), nullable=False)  # like / favorite / dislike
    interaction_score = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    comic = db.relationship('Comic', back_populates='interactions')

    __table_args__ = (db.UniqueConstraint('comic_id', 'user_session', 'interaction_type',
                                          name='_comic_interaction_uc'),)


class ComicProgress(db.Model):
    """漫画阅读进度（按用户）"""
    __tablename__ = 'comic_progress'

    id = db.Column(db.Integer, primary_key=True)
    comic_id = db.Column(db.Integer, db.ForeignKey('comics.id'), nullable=False, index=True)
    user_session = db.Column(db.String(100), nullable=False)
    page = db.Column(db.Integer, default=0)         # 当前阅读到的页码（从 1 开始）
    progress = db.Column(db.Float, default=0.0)     # 0~1 阅读进度
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    comic = db.relationship('Comic', back_populates='progress')

    __table_args__ = (db.UniqueConstraint('comic_id', 'user_session', name='_comic_progress_uc'),)


class ComicTag(db.Model):
    """漫画-标签关联表（复用主应用的 tags 表，支持多视频库独立标签体系）"""
    __tablename__ = 'comic_tags'

    id = db.Column(db.Integer, primary_key=True)
    comic_id = db.Column(db.Integer, db.ForeignKey('comics.id'), nullable=False, index=True)
    tag_id = db.Column(db.Integer, db.ForeignKey('tags.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    comic = db.relationship('Comic')
    tag = db.relationship('Tag')

    __table_args__ = (db.UniqueConstraint('comic_id', 'tag_id', name='_comic_tag_uc'),)


class ComicPlaylist(db.Model):
    """漫画合集/播放列表模型（对齐 videos 的 Playlist）"""
    __tablename__ = 'comic_playlists'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    user_session = db.Column(db.String(100), nullable=False, index=True)
    is_public = db.Column(db.Boolean, default=False)
    thumbnail = db.Column(db.String(500))
    comic_count = db.Column(db.Integer, default=0)
    play_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = db.relationship('ComicPlaylistItem', back_populates='playlist', cascade='all, delete-orphan')

    def update_comic_count(self):
        self.comic_count = len([item for item in self.items if item.comic is not None])

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'user_session': self.user_session,
            'is_public': self.is_public,
            'thumbnail': self.thumbnail,
            'comic_count': self.comic_count,
            'play_count': self.play_count,
            'items': [item.to_dict() for item in self.items if item.comic is not None],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class ComicPlaylistItem(db.Model):
    """漫画合集项模型（对齐 videos 的 PlaylistItem）"""
    __tablename__ = 'comic_playlist_items'

    id = db.Column(db.Integer, primary_key=True)
    playlist_id = db.Column(db.Integer, db.ForeignKey('comic_playlists.id'), nullable=False)
    comic_id = db.Column(db.Integer, db.ForeignKey('comics.id'), nullable=False)
    position = db.Column(db.Integer, nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    playlist = db.relationship('ComicPlaylist', back_populates='items')
    comic = db.relationship('Comic')

    __table_args__ = (db.UniqueConstraint('playlist_id', 'comic_id', name='_comic_playlist_uc'),)

    def to_dict(self):
        d = {
            'id': self.id,
            'playlist_id': self.playlist_id,
            'comic_id': self.comic_id,
            'position': self.position,
            'added_at': self.added_at.isoformat() if self.added_at else None
        }
        if self.comic:
            cd = self.comic.to_dict()
            cd['cover_url'] = f'/comic-cover/{self.comic.hash}'
            d['comic'] = cd
        else:
            d['comic'] = None
        return d


def migrate_collection_videos_schema():
    """[TEST] 为 collection_videos 增加 item_type / comic_id 列（支持收藏夹收纳漫画）。

    仅当列不存在时执行 ALTER，兼容旧库；create_all 不会为已存在的表新增列。
    """
    try:
        insp = db.inspect(db.engine)
        existing = {c['name'] for c in insp.get_columns('collection_videos')}
        with db.engine.begin() as conn:
            if 'item_type' not in existing:
                conn.execute(db.text(
                    "ALTER TABLE collection_videos ADD COLUMN item_type VARCHAR(20) NOT NULL DEFAULT 'video'"))
            if 'comic_id' not in existing:
                conn.execute(db.text(
                    "ALTER TABLE collection_videos ADD COLUMN comic_id INTEGER"))
    except Exception as e:
        print(f'[WARN] collection_videos 迁移跳过: {e}')





