import json
import re
import os
import urllib.parse
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

class ResourceIndex(db.Model):
    """资源索引表：解耦「实体（视频/图集/帖子/文本）」与「本体在磁盘上的具体位置」。

    每个实体只持有 resource_index_id，通过本表指向具体的磁盘路径：
      - kind='video_file'   -> location 为视频文件
      - kind='gallery_folder' -> location 为图集（图片集）文件夹
      - kind='text'         -> 文本资源（未来扩展）
    移动 / 重命名资源只需更新本表 location 一行，所有引用它的实体自动跟随。

    meta（JSON）是「通用资产呈现」存储，标准化键（缺省可空）：
      title / thumbnail / duration(秒) / width / height /
      page_count / caption / summary / source_url / downloaded_by
    无论是否建了 Video/Gallery/Text 富化实体，都能用 presentation() 渲染卡片。
    """
    __tablename__ = 'resource_index'
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False, index=True)
    location = db.Column(db.String(600), nullable=False)
    cover = db.Column(db.String(2000), nullable=True)  # 统一封面入口：封面服务 URL，所有上层实体（视频/图集/帖子）从索引读取
    library_id = db.Column(db.Integer, db.ForeignKey('resource_libraries.id'), nullable=True)
    hash = db.Column(db.String(64), index=True)
    meta = db.Column(db.Text)  # JSON: 通用资产呈现（见类文档）
    hidden = db.Column(db.Boolean, default=False, nullable=False)  # 是否隐藏：隐藏的资源不出现在视频/图集库列表，仅在帖子流可见
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_meta(self):
        try:
            return json.loads(self.meta) if self.meta else {}
        except Exception:
            return {}

    def set_meta(self, patch):
        """合并写入 meta（只更新提供的键）。"""
        m = self.get_meta()
        m.update({k: v for k, v in (patch or {}).items() if v is not None})
        self.meta = json.dumps(m, ensure_ascii=False)

    def _basename(self):
        if not self.location:
            return None
        return self.location.replace('\\', '/').rstrip('/').split('/')[-1]

    def presentation(self):
        """通用资产呈现：任一模式（含只属于帖子的资源）都能用同一套字段渲染卡片。"""
        m = self.get_meta()
        return {
            'title': m.get('title') or self._basename(),
            'thumbnail': m.get('thumbnail'),
            'duration': m.get('duration'),
            'width': m.get('width'),
            'height': m.get('height'),
            'page_count': m.get('page_count'),
            'caption': m.get('caption'),
            'summary': m.get('summary'),
            'source_url': m.get('source_url'),
            'downloaded_by': m.get('downloaded_by'),
        }

    def to_dict(self):
        return {
            'id': self.id,
            'kind': self.kind,
            'location': self.location,
            'library_id': self.library_id,
            'hash': self.hash,
            'cover': self.cover,
            'hidden': bool(self.hidden),
            'meta': self.get_meta(),
            'presentation': self.presentation(),
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.avif')


def _gallery_folder_image_list(ri):
    """列出 gallery_folder 资源目录下的图片文件（按名称排序），供帖子专属图集内联渲染。"""
    if not ri or ri.kind != 'gallery_folder' or not ri.location or not os.path.isdir(ri.location):
        return []
    return sorted(f for f in os.listdir(ri.location) if f.lower().endswith(_IMAGE_EXTS))


class ResourceMode:
    """资源模式（逻辑呈现轴）。

    - 单资源模式（video/gallery/text）：可见性 = resource_memberships 中对应 mode 的归属行。
    - 组合模式（post）：由 Post 通过 PostRef 引用资源表达，不写入 membership 表。
    """
    VIDEO = 'video'
    GALLERY = 'gallery'
    TEXT = 'text'
    POST = 'post'   # 组合模式

    SINGLE = (VIDEO, GALLERY, TEXT)  # 单资源模式集合

    @classmethod
    def is_valid(cls, mode):
        return mode in (cls.VIDEO, cls.GALLERY, cls.TEXT, cls.POST)

    @classmethod
    def is_single(cls, mode):
        return mode in cls.SINGLE


class ResourceModeMembership(db.Model):
    """资源-模式归属：单资源模式（video/gallery/text）可见性的唯一真相源。

    与富化实体（Video/Gallery/Text）在「同一事务」内写入，杜绝与实体存在性双源漂移。
    """
    __tablename__ = 'resource_memberships'
    id = db.Column(db.Integer, primary_key=True)
    resource_index_id = db.Column(db.Integer, db.ForeignKey('resource_index.id'), nullable=False, index=True)
    mode = db.Column(db.String(32), nullable=False, index=True)
    position = db.Column(db.Integer, default=0)
    note = db.Column(db.Text)  # 该模式下覆盖的标题/说明
    collection_id = db.Column(db.Integer, db.ForeignKey('collections.id'), nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    resource_index = db.relationship('ResourceIndex', backref='memberships')

    __table_args__ = (db.UniqueConstraint('resource_index_id', 'mode', name='uq_res_mode'),)

    def to_dict(self):
        return {
            'id': self.id,
            'resource_index_id': self.resource_index_id,
            'mode': self.mode,
            'position': self.position,
            'note': self.note,
            'collection_id': self.collection_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Collection(db.Model):
    """模式内合集（可选分组）：如「某次爬取的图文合集」。"""
    __tablename__ = 'collections'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    mode = db.Column(db.String(32), nullable=False, index=True)
    library_id = db.Column(db.Integer, db.ForeignKey('resource_libraries.id'), nullable=True)
    created_by = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    memberships = db.relationship('ResourceModeMembership', backref='collection')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'mode': self.mode,
            'library_id': self.library_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Text(db.Model):
    """文本模式富化实体（未来的文本内容管理）。

    文本资源的本体即 resource_index.location（可为文本文件路径或留空，正文存 body）。
    """
    __tablename__ = 'texts'
    id = db.Column(db.Integer, primary_key=True)
    resource_index_id = db.Column(db.Integer, db.ForeignKey('resource_index.id'), nullable=False, unique=True)
    body = db.Column(db.Text)
    summary = db.Column(db.Text)
    resource_index = db.relationship('ResourceIndex', backref='text')

    def to_dict(self):
        ri = self.resource_index
        return {
            'id': self.id,
            'resource_index_id': self.resource_index_id,
            'body': self.body,
            'summary': self.summary,
            'kind': ri.kind if ri else None,
            'location': ri.location if ri else None,
            'presentation': ri.presentation() if ri else None,
            'updated_at': ri.updated_at.isoformat() if ri and ri.updated_at else None,
        }


def ensure_mode_enrichment(ri, mode):
    """为某单资源模式确保富化实体存在（与 membership 同一事务内调用）。"""
    if mode == ResourceMode.VIDEO:
        if not Video.query.filter_by(resource_index_id=ri.id).first():
            meta = ri.get_meta()
            title = meta.get('title') or ri._basename() or '未命名视频'
            v = Video(resource_index_id=ri.id, library_id=ri.library_id,
                      file_name=ri._basename(), hash=ri.hash or ri.location or f'ri-{ri.id}',
                      title=title, url=ri.location or '', duration=meta.get('duration'))
            db.session.add(v)
    elif mode == ResourceMode.GALLERY:
        if not Gallery.query.filter_by(resource_index_id=ri.id).first():
            gh = ri.hash
            # resource_index 未带 hash 时，绝不能回退成文件夹路径（路径含反斜杠会破坏路由且无法删除）
            if not gh or len(gh) != 64 or not all(ch in '0123456789abcdefABCDEF' for ch in gh):
                gh = Gallery.generate_hash_from_folder(ri.location)
            c = Gallery(resource_index_id=ri.id, folder_path=ri.location,
                       library_id=ri.library_id, title=ri._basename() or '未命名图集',
                       hash=gh or f'ri-{ri.id}')
            db.session.add(c)
    elif mode == ResourceMode.TEXT:
        if not Text.query.filter_by(resource_index_id=ri.id).first():
            t = Text(resource_index_id=ri.id, summary=ri.get_meta().get('summary'))
            db.session.add(t)


def delete_mode_enrichment(ri, mode):
    """移除某模式时清理其富化实体（membership 是可见性唯一真相源）。"""
    if mode == ResourceMode.VIDEO:
        v = Video.query.filter_by(resource_index_id=ri.id).first()
        if v:
            db.session.delete(v)
    elif mode == ResourceMode.GALLERY:
        c = Gallery.query.filter_by(resource_index_id=ri.id).first()
        if c:
            db.session.delete(c)
    elif mode == ResourceMode.TEXT:
        t = Text.query.filter_by(resource_index_id=ri.id).first()
        if t:
            db.session.delete(t)


def set_resource_modes(ri, modes, collection_id=None, user_id=None):
    """设置资源的单资源模式归属（membership 行 + 富化实体同步增删）。

    组合模式（post）不在此处理——它由 Post 通过 PostRef 引用表达。
    """
    wanted = []
    for m in (modes or []):
        if m == ResourceMode.POST or not ResourceMode.is_valid(m):
            continue
        if m not in wanted:
            wanted.append(m)
    existing = {mbr.mode: mbr for mbr in ri.memberships}
    for mode in existing:
        if mode not in wanted:
            delete_mode_enrichment(ri, mode)
            db.session.delete(existing[mode])
    for mode in wanted:
        if mode not in existing:
            mbr = ResourceModeMembership(resource_index_id=ri.id, mode=mode,
                                         collection_id=collection_id, created_by=user_id)
            db.session.add(mbr)
            ensure_mode_enrichment(ri, mode)
    db.session.commit()
    return ri


def create_post(title, content=None, resource_index_ids=None, user_id=None, display_modes=None,
                author_name=None, author_url=None, source_url=None, group_key=None):
    """由一组资源索引创建一条帖子（组合模式）。

    例：图文+视频一体的下载 -> [image_set_ri, video_ri] 合成一条帖子，视频模式不会单独出现。
    display_modes: 可选 {resource_index_id: 'link'|'embed'}，缺省按 'embed' 处理。
    author_name/author_url/source_url: 来源信息（X 下载器回填），前端展示为可点击链接。
    group_key: 下载来源分组键（如 X 的 tweet_id），用于重复下载时定位并更新同一条帖子。
    """
    # 帖子标题可选：用户不填则存空，前端展示时根本不渲染标题区域
    d = Post(
        title=title or None,
        content=content,
        owner_id=user_id,
        author_name=author_name,
        author_url=author_url,
        source_url=source_url,
        group_key=group_key,
    )
    db.session.add(d)
    db.session.flush()
    for i, rid in enumerate(resource_index_ids):
        ri = ResourceIndex.query.get(rid)
        if not ri:
            continue
        mode = (display_modes or {}).get(rid, 'embed')
        ref = PostRef(post_id=d.id, resource_index_id=rid, position=i, display_mode=mode)
        db.session.add(ref)
    db.session.commit()
    return d


def upsert_post_by_group(group_key, title, content, resource_index_ids, user_id=None,
                         display_modes=None, author_name=None, author_url=None,
                         source_url=None):
    """按 group_key 查重：已存在同组帖子则更新（重建引用 + 同步来源信息），否则新建。

    重复下载同一来源（如同一推文）时避免产生多条重复帖子。
    """
    existing = None
    if group_key:
        existing = Post.query.filter_by(group_key=group_key).first()
    if existing:
        existing.title = title or None
        existing.content = content
        existing.owner_id = user_id
        existing.author_name = author_name
        existing.author_url = author_url
        existing.source_url = source_url
        # 重复下载（同来源）视为「重新生成帖子」，应从回收站恢复，
        # 否则用户删除过一次后，后续重复下载只会更新同 group_key 帖子、
        # in_trash 保持 True，导致帖子流永远看不到该帖子。
        if existing.in_trash:
            existing.in_trash = False
            existing.trashed_at = None
        # 重建引用（顺序编排）
        PostRef.query.filter_by(post_id=existing.id).delete()
        db.session.flush()
        for i, rid in enumerate(resource_index_ids):
            ri = ResourceIndex.query.get(rid)
            if not ri:
                continue
            mode = (display_modes or {}).get(rid, 'embed')
            ref = PostRef(post_id=existing.id, resource_index_id=rid, position=i, display_mode=mode)
            db.session.add(ref)
        db.session.commit()
        return existing
    return create_post(title, content, resource_index_ids, user_id=user_id,
                       display_modes=display_modes, author_name=author_name,
                       author_url=author_url, source_url=source_url, group_key=group_key)


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
    resource_index_id = db.Column(db.Integer, db.ForeignKey('resource_index.id'), nullable=True, index=True)
    resource_index = db.relationship('ResourceIndex', foreign_keys=[resource_index_id])

    @property
    def local_path(self):
        # 通过资源索引表解析真实磁盘路径（解耦实体与本体的绑定）
        if self.resource_index:
            return self.resource_index.location
        return None

    @local_path.setter
    def local_path(self, value):
        if self.resource_index is None:
            self.resource_index = ResourceIndex(kind='video_file')
        self.resource_index.location = value
        if self.library_id is not None:
            self.resource_index.library_id = self.library_id

    file_name = db.Column(db.String(500))  # 文件名（仅作为属性，绝不作为视频唯一标识/key）
    library_id = db.Column(db.Integer, db.ForeignKey('resource_libraries.id'))  # 所属资源库，NULL表示主数据库
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # 上传者/资源归属者，NULL 表示历史资源
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 回收站（软删除）标记
    in_trash = db.Column(db.Boolean, default=False, nullable=False, index=True)
    trashed_at = db.Column(db.DateTime, nullable=True)

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
            'resource_index_id': self.resource_index_id,
            'title': self.title,
            'description': self.description,
            'url': f'/api/videos/{self.id}/play',
            'thumbnail': self.cover_url,
            'cover_url': self.cover_url,
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
            'owner_id': self.owner_id,
            'hidden': bool(self.resource_index.hidden) if self.resource_index else False,
            'tags': [
                {**vt.tag.to_dict(), 'selected_qualifiers': vt.get_selected_qualifiers()}
                for vt in self.tags if vt.tag is not None
            ],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    @property
    def cover_url(self):
        """统一封面入口：优先取资源索引的 cover，缺失时兜底为缩略图路由。"""
        if self.resource_index and self.resource_index.cover:
            return self.resource_index.cover
        return self.thumbnail or f'/thumbnail/{self.hash}'


class Tag(db.Model):
    """标签模型 - 支持多资源库独立标签体系"""
    __tablename__ = 'tags'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, index=True)  # 标签名称（同一路径下唯一）
    qualifiers = db.Column(db.Text)  # 补充项（可选）：JSON 数组字符串，如 ["白","长毛"]，标签维度预设的属性池（非层级）
    path = db.Column(db.String(200), nullable=False, index=True)  # 完整路径，如 /动物/狗/哈士奇
    category = db.Column(db.String(50))  # 标签分类：如 "类型", "作者", "地区" 等
    parent_id = db.Column(db.Integer, db.ForeignKey('tags.id'), nullable=True)  # 父标签ID，支持多级
    library_id = db.Column(db.Integer, db.ForeignKey('resource_libraries.id'), nullable=True)  # 资源库ID，null表示全局标签
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 关系
    videos = db.relationship('VideoTag', back_populates='tag', cascade='all, delete-orphan')
    parent = db.relationship('Tag', remote_side=[id], backref='children')  # 自关联：父标签 / 子标签
    library = db.relationship('ResourceLibrary', backref='tags')  # 资源库关系

    # 唯一约束：同一资源库下路径唯一
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

    def get_qualifiers(self):
        """返回补充项列表（去重、去空白后的字符串数组）。"""
        if not self.qualifiers:
            return []
        try:
            data = json.loads(self.qualifiers)
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        seen = set()
        result = []
        for q in data:
            if not isinstance(q, str):
                continue
            q = q.strip()
            if not q or q in seen:
                continue
            seen.add(q)
            result.append(q)
        return result

    @staticmethod
    def normalize_qualifiers(raw):
        """将原始输入（逗号/换行/空格分隔的字符串，或字符串数组）规范化为补充项列表。"""
        if raw is None:
            return []
        if isinstance(raw, str):
            items = re.split(r'[\n,，;；\s]+', raw)
        elif isinstance(raw, (list, tuple)):
            items = list(raw)
        else:
            return []
        seen = set()
        result = []
        for q in items:
            if not isinstance(q, str):
                continue
            q = q.strip()
            if not q or q in seen:
                continue
            seen.add(q)
            result.append(q[:80])
        return result

    def set_qualifiers(self, raw):
        """设置补充项（覆盖写），存储为 JSON 字符串。"""
        self.qualifiers = json.dumps(self.normalize_qualifiers(raw), ensure_ascii=False)

    def to_dict(self, include_children=False):
        result = {
            'id': self.id,
            'name': self.name,
            'qualifiers': self.get_qualifiers(),
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
    selected_qualifiers = db.Column(db.Text)  # 该视频在此标签上勾选的补充项（JSON 数组，标签 qualifiers 的子集）
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 关系
    video = db.relationship('Video', back_populates='tags')
    tag = db.relationship('Tag', back_populates='videos')

    # 唯一约束，防止重复关联
    __table_args__ = (db.UniqueConstraint('video_id', 'tag_id', name='_video_tag_uc'),)

    def get_selected_qualifiers(self):
        """返回该视频在标签上选中的补充项列表。"""
        if not self.selected_qualifiers:
            return []
        try:
            data = json.loads(self.selected_qualifiers)
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        return [str(q).strip() for q in data if str(q).strip()]

    def set_selected_qualifiers(self, raw):
        """设置选中的补充项（覆盖写），并过滤为标签预设集合的子集。"""
        allowed = set(self.tag.get_qualifiers()) if self.tag else set()
        items = []
        if isinstance(raw, (list, tuple)):
            items = [str(q).strip() for q in raw if str(q).strip()]
        elif isinstance(raw, str):
            items = [q.strip() for q in re.split(r'[\n,，;；\s]+', raw) if q.strip()]
        # 只保留标签预设池内的补充项；若标签未预设，则允许自由值
        if allowed:
            items = [q for q in items if q in allowed]
        # 去重保序
        seen = set()
        result = []
        for q in items:
            if q not in seen:
                seen.add(q)
                result.append(q)
        self.selected_qualifiers = json.dumps(result, ensure_ascii=False) if result else None


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


class WatchLater(db.Model):
    """稍后再看：用户稍后观看/阅读的条目（视频/图集/帖子/文本）。

    身份键 user_key 采用与交互记录一致的策略：登录用户为 u{user_id}（跨设备一致），
    未登录游客为随机会话（仅当前设备/浏览器有效）。列表以 user_key 为唯一归属维度。
    """
    __tablename__ = 'watch_later'

    id = db.Column(db.Integer, primary_key=True)
    user_key = db.Column(db.String(100), nullable=False, index=True)
    item_type = db.Column(db.String(20), nullable=False)  # video/gallery/post/text
    item_id = db.Column(db.String(255), nullable=False)    # 视频/图集用 hash，帖子/文本用 id
    title = db.Column(db.String(500))
    thumbnail = db.Column(db.String(1000))
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    # 软删除时间戳：移除「稍后再看」条目时只打墓碑，不物理删除。
    # 这样即使底层视频随后被恢复/重新入库、或某客户端把本地残留列表回推服务端，
    # 被用户删除过的条目也不会「复活」重新出现在列表里（见 watch_later_api）。
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)

    __table_args__ = (
        db.UniqueConstraint('user_key', 'item_type', 'item_id', name='_watch_later_uc'),
    )

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def to_dict(self):
        return {
            'type': self.item_type,
            'id': self.item_id,
            'title': self.title,
            'thumbnail': self.thumbnail,
            'addedAt': self.added_at.isoformat() if self.added_at else None,
        }

    def __repr__(self):
        return f'<WatchLater {self.user_key} {self.item_type}:{self.item_id}>'


class WatchHistory(db.Model):
    """观看历史：记录用户观看/阅读的进度（视频/图集）。

    身份键 user_key 采用与 WatchLater/UserInteraction 一致的策略：
    登录用户为 u{user_id}（跨设备一致），未登录游客为随机会话（仅当前设备有效）。
    后端作为唯一数据源，取代原先分散在 localStorage 的观看记录。
    """
    __tablename__ = 'watch_history'

    id = db.Column(db.Integer, primary_key=True)
    user_key = db.Column(db.String(100), nullable=False, index=True)
    item_type = db.Column(db.String(20), nullable=False)  # video / gallery
    item_id = db.Column(db.String(255), nullable=False)    # 视频/图集用 hash
    title = db.Column(db.String(500))
    thumbnail = db.Column(db.String(1000))
    progress = db.Column(db.Float, default=0.0)            # 0~1 观看进度
    duration = db.Column(db.Float, default=0.0)            # 媒体时长（秒）
    watched_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, index=True)

    __table_args__ = (
        db.UniqueConstraint('user_key', 'item_type', 'item_id', name='_watch_history_uc'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'userKey': self.user_key,
            'itemType': self.item_type,
            'itemId': self.item_id,
            'title': self.title,
            'thumbnail': self.thumbnail,
            'progress': self.progress,
            'duration': self.duration,
            'watchedAt': self.watched_at.isoformat() if self.watched_at else None,
        }

    def __repr__(self):
        return f'<WatchHistory {self.user_key} {self.item_type}:{self.item_id}>'


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
    """收藏夹与资源的关联表（视频 / 图集地位等同，通过 item_type 区分）"""
    __tablename__ = 'collection_videos'

    id = db.Column(db.Integer, primary_key=True)
    collection_id = db.Column(db.Integer, db.ForeignKey('favorite_collections.id'), nullable=False)
    user_session = db.Column(db.String(100), nullable=False, index=True)
    item_type = db.Column(db.String(20), nullable=False, default='video')  # 'video' | 'gallery'
    video_id = db.Column(db.Integer, db.ForeignKey('videos.id'), nullable=True)
    gallery_id = db.Column(db.Integer, db.ForeignKey('galleries.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    collection = db.relationship('FavoriteCollection', back_populates='items')
    gallery = db.relationship('Gallery', foreign_keys=[gallery_id])

    def to_dict(self):
        return {
            'id': self.id,
            'collection_id': self.collection_id,
            'item_type': self.item_type,
            'video_id': self.video_id,
            'gallery_id': self.gallery_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class MediaCollection(db.Model):
    """合集（独立于收藏夹）：用户把视频/图集按主题归组，支持排序与多归属。"""
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
    """合集项（视频/图集）。一个资源可同时属于多个合集。"""
    __tablename__ = 'media_collection_items'

    id = db.Column(db.Integer, primary_key=True)
    collection_id = db.Column(db.Integer, db.ForeignKey('media_collections.id', ondelete='CASCADE'), nullable=False, index=True)
    owner_key = db.Column(db.String(64), nullable=False, index=True)
    item_type = db.Column(db.String(16), nullable=False)  # 'video' | 'gallery'
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


class AppSetting(db.Model):
    """通用应用设置存储（分层：global / user）。

    浏览器层（device）由前端 localStorage 管理，不入库。
    合并优先级（高->低）：browser > user > global > defaults
    """
    __tablename__ = 'app_settings'

    id = db.Column(db.Integer, primary_key=True)
    scope = db.Column(db.String(20), nullable=False)        # 'global' 或 'user'
    owner = db.Column(db.String(50), nullable=False, default='')  # 用户层为 user_id 字符串，全局层为 ''
    data = db.Column(db.Text, nullable=False, default='{}')  # JSON 字符串
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('scope', 'owner', name='uq_app_settings_scope_owner'),
    )

    def get_data(self):
        try:
            return json.loads(self.data) if self.data else {}
        except Exception:
            return {}

    def set_data(self, value):
        self.data = json.dumps(value or {}, ensure_ascii=False)

    def to_dict(self):
        return {
            'scope': self.scope,
            'owner': self.owner,
            'data': self.get_data(),
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


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


# ==================== 多数据库资源库管理模型 ====================

class ResourceLibrary(db.Model):
    """资源库模型 - 每个资源库对应一个独立的数据库"""
    __tablename__ = 'resource_libraries'

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
        return f'<ResourceLibrary {self.name}>'

    @property
    def full_db_path(self):
        """获取完整的数据库文件绝对路径（运行时动态拼接，不依赖存储的绝对路径）"""
        import os
        # 优先从环境变量获取 data 目录
        data_dir = os.environ.get('DBOX_DATA_DIR')
        if not data_dir:
            # 兼容旧数据：db_path 可能是绝对路径
            # db_path = 'C:\\...' 表示旧数据，直接使用
            # db_path = 'libraries' 表示新数据，相对路径
            if os.path.isabs(self.db_path):
                return os.path.join(self.db_path, self.db_file)
            # db_path = 'libraries' 相对路径：相对于项目根目录的 data/
            # 正确计算：main.py 在 src/web/，向上两级到项目根目录
            _src_web = os.path.dirname(os.path.abspath(__file__))  # src/web/core
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(_src_web)))  # Dbox2.0/
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
    """资源库权限模型"""
    __tablename__ = 'library_permissions'

    id = db.Column(db.Integer, primary_key=True)
    library_id = db.Column(db.Integer, db.ForeignKey('resource_libraries.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))  # 用户ID，为NULL表示用户组权限
    group_id = db.Column(db.Integer, db.ForeignKey('library_user_groups.id'))  # 用户组ID
    role = db.Column(db.String(20), nullable=False, default='user')  # admin 或 user
    access_level = db.Column(db.String(20), nullable=False, default='read')  # full, read, write, custom
    permissions = db.Column(db.JSON)  # 详细权限配置
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    # 关系
    library = db.relationship('ResourceLibrary', back_populates='permissions')
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
    library_id = db.Column(db.Integer, db.ForeignKey('resource_libraries.id'))
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


# ==================== 图集模式（Gallery Mode）数据模型 ====================
class Gallery(db.Model):
    """图集模型 - 一本图集 = 磁盘上一个扁平的图片文件夹"""
    __tablename__ = 'galleries'

    id = db.Column(db.Integer, primary_key=True)
    hash = db.Column(db.String(64), unique=True, nullable=False, index=True)  # 内容指纹（与路径解耦）
    title = db.Column(db.String(300), nullable=False)
    resource_index_id = db.Column(db.Integer, db.ForeignKey('resource_index.id'), nullable=True, index=True)
    resource_index = db.relationship('ResourceIndex', foreign_keys=[resource_index_id])

    @property
    def folder_path(self):
        # 通过资源索引表解析真实磁盘文件夹（解耦实体与本体的绑定）
        if self.resource_index:
            return self.resource_index.location
        return None

    @folder_path.setter
    def folder_path(self, value):
        if self.resource_index is None:
            self.resource_index = ResourceIndex(kind='gallery_folder')
        self.resource_index.location = value
        if self.library_id is not None:
            self.resource_index.library_id = self.library_id

    @property
    def cover_path(self):
        # 封面即第一页图片，由 pages 推导（与具体磁盘绑定解耦）
        if self.pages and len(self.pages) > 0:
            return self.pages[0].file_path
        return None

    @property
    def cover_url(self):
        """统一封面入口：优先取资源索引的 cover，缺失时兜底为第一页封面路由。"""
        if self.resource_index and self.resource_index.cover:
            return self.resource_index.cover
        return f'/gallery-cover/{self.hash}' if self.hash else None

    library_id = db.Column(db.Integer, db.ForeignKey('resource_libraries.id'), nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # 上传者/资源归属者，NULL 表示历史资源
    page_count = db.Column(db.Integer, default=0)
    like_count = db.Column(db.Integer, default=0)
    favorite_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 回收站（软删除）标记
    in_trash = db.Column(db.Boolean, default=False, nullable=False, index=True)
    trashed_at = db.Column(db.DateTime, nullable=True)

    pages = db.relationship('GalleryPage', back_populates='gallery', cascade='all, delete-orphan',
                            order_by='GalleryPage.page_index')
    interactions = db.relationship('GalleryInteraction', back_populates='gallery', cascade='all, delete-orphan')
    progress = db.relationship('GalleryProgress', back_populates='gallery', cascade='all, delete-orphan')

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

    @staticmethod
    def generate_hash_from_folder(folder_path):
        """扫描文件夹内图片文件，计算内容指纹（供 resource_index 缺失 hash 时兜底，
        绝不返回路径本身，避免产生含反斜杠的非法 hash）。文件夹不存在时返回 None。"""
        import os
        import glob
        if not folder_path or not os.path.isdir(folder_path):
            return None
        exts = ('*.jpg', '*.jpeg', '*.png', '*.gif', '*.webp', '*.bmp')
        pages = []
        for ext in exts:
            pages.extend(glob.glob(os.path.join(folder_path, ext)))
            pages.extend(glob.glob(os.path.join(folder_path, ext.upper())))
        if not pages:
            return hashlib.sha256(folder_path.encode('utf-8')).hexdigest()
        return Gallery.generate_hash(folder_path, pages)

    def to_dict(self):
        return {
            'id': self.id,
            'hash': self.hash,
            'resource_index_id': self.resource_index_id,
            'title': self.title,
            'page_count': self.page_count,
            'library_id': self.library_id,
            'owner_id': self.owner_id,
            'like_count': self.like_count,
            'favorite_count': self.favorite_count,
            'hidden': bool(self.resource_index.hidden) if self.resource_index else False,
            'folder_path': self.folder_path,
            'cover_url': self.cover_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class GalleryPage(db.Model):
    """图集页面 - 一页图片"""
    __tablename__ = 'gallery_pages'

    id = db.Column(db.Integer, primary_key=True)
    gallery_id = db.Column(db.Integer, db.ForeignKey('galleries.id'), nullable=False, index=True)
    # 兼容老版本 SQLite：部分库仍保留 comic_id 列且为 NOT NULL，与 gallery_id 同值同步写入
    comic_id = db.Column(db.Integer, nullable=True)
    page_index = db.Column(db.Integer, nullable=False)   # 从 0 开始
    file_path = db.Column(db.String(600), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    gallery = db.relationship('Gallery', back_populates='pages')

    __table_args__ = (db.UniqueConstraint('gallery_id', 'page_index', name='_gallery_page_uc'),)


class GalleryInteraction(db.Model):
    """图集交互（点赞/收藏/不喜欢），结构对齐 videos 的 user_interactions"""
    __tablename__ = 'gallery_interactions'

    id = db.Column(db.Integer, primary_key=True)
    gallery_id = db.Column(db.Integer, db.ForeignKey('galleries.id'), nullable=False, index=True)
    user_session = db.Column(db.String(100), nullable=False)
    interaction_type = db.Column(db.String(20), nullable=False)  # like / favorite / dislike
    interaction_score = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    gallery = db.relationship('Gallery', back_populates='interactions')

    __table_args__ = (db.UniqueConstraint('gallery_id', 'user_session', 'interaction_type',
                                          name='_gallery_interaction_uc'),)


class GalleryProgress(db.Model):
    """图集阅读进度（按用户）"""
    __tablename__ = 'gallery_progress'

    id = db.Column(db.Integer, primary_key=True)
    gallery_id = db.Column(db.Integer, db.ForeignKey('galleries.id'), nullable=False, index=True)
    user_session = db.Column(db.String(100), nullable=False)
    page = db.Column(db.Integer, default=0)         # 当前阅读到的页码（从 1 开始）
    progress = db.Column(db.Float, default=0.0)     # 0~1 阅读进度
    in_continue = db.Column(db.Boolean, default=False, nullable=False, index=True)  # 是否主动加入「继续阅读」列表
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    gallery = db.relationship('Gallery', back_populates='progress')

    __table_args__ = (db.UniqueConstraint('gallery_id', 'user_session', name='_gallery_progress_uc'),)


class GalleryTag(db.Model):
    """图集-标签关联表（复用主应用的 tags 表，支持多资源库独立标签体系）"""
    __tablename__ = 'gallery_tags'

    id = db.Column(db.Integer, primary_key=True)
    gallery_id = db.Column(db.Integer, db.ForeignKey('galleries.id'), nullable=False, index=True)
    tag_id = db.Column(db.Integer, db.ForeignKey('tags.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    gallery = db.relationship('Gallery')
    tag = db.relationship('Tag')

    __table_args__ = (db.UniqueConstraint('gallery_id', 'tag_id', name='_gallery_tag_uc'),)


class GalleryPlaylist(db.Model):
    """图集合集/播放列表模型（对齐 videos 的 Playlist）"""
    __tablename__ = 'gallery_playlists'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    user_session = db.Column(db.String(100), nullable=False, index=True)
    is_public = db.Column(db.Boolean, default=False)
    thumbnail = db.Column(db.String(500))
    gallery_count = db.Column(db.Integer, default=0)
    play_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = db.relationship('GalleryPlaylistItem', back_populates='playlist', cascade='all, delete-orphan')

    def update_gallery_count(self):
        self.gallery_count = len([item for item in self.items if item.gallery is not None])

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'user_session': self.user_session,
            'is_public': self.is_public,
            'thumbnail': self.thumbnail,
            'gallery_count': self.gallery_count,
            'play_count': self.play_count,
            'items': [item.to_dict() for item in self.items if item.gallery is not None],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class GalleryPlaylistItem(db.Model):
    """图集合集项模型（对齐 videos 的 PlaylistItem）"""
    __tablename__ = 'gallery_playlist_items'

    id = db.Column(db.Integer, primary_key=True)
    playlist_id = db.Column(db.Integer, db.ForeignKey('gallery_playlists.id'), nullable=False)
    gallery_id = db.Column(db.Integer, db.ForeignKey('galleries.id'), nullable=False)
    position = db.Column(db.Integer, nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    playlist = db.relationship('GalleryPlaylist', back_populates='items')
    gallery = db.relationship('Gallery')

    __table_args__ = (db.UniqueConstraint('playlist_id', 'gallery_id', name='_gallery_playlist_uc'),)

    def to_dict(self):
        d = {
            'id': self.id,
            'playlist_id': self.playlist_id,
            'gallery_id': self.gallery_id,
            'position': self.position,
            'added_at': self.added_at.isoformat() if self.added_at else None
        }
        if self.gallery:
            cd = self.gallery.to_dict()
            cd['cover_url'] = f'/gallery-cover/{self.gallery.hash}'
            d['gallery'] = cd
        else:
            d['gallery'] = None
        return d


class Post(db.Model):
    """帖子：通过资源索引表自由引用多个资源（视频 / 图片集 / 文本等）并编排顺序。

    帖子本身不持有任何具体文件，只持有对 resource_index 的引用，
    因此同一视频 / 图片集可被多个帖子、多个模式共享，且不复制数据。
    """
    __tablename__ = 'posts'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=True, default='')
    content = db.Column(db.Text, default='')  # 文字正文
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    library_id = db.Column(db.Integer, db.ForeignKey('resource_libraries.id'), nullable=True)
    in_trash = db.Column(db.Boolean, default=False, nullable=False, index=True)
    trashed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 来源信息：X 下载器会回填作者与原始推文地址，前端展示为可点击链接
    author_name = db.Column(db.String(200), nullable=True)
    author_url = db.Column(db.String(1000), nullable=True)
    source_url = db.Column(db.String(1000), nullable=True)

    # 下载来源分组键（如 X 的 tweet_id），用于重复下载时定位并更新同一条帖子
    group_key = db.Column(db.String(200), nullable=True, index=True)

    refs = db.relationship('PostRef', back_populates='post',
                            cascade='all, delete-orphan', order_by='PostRef.position')

    def to_dict(self, resolve=True):
        d = {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'owner_id': self.owner_id,
            'library_id': self.library_id,
            'in_trash': self.in_trash,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if resolve:
            items = []
            for r in self.refs:
                entry = {
                    'ref_id': r.id,
                    'position': r.position,
                    'note': r.note,
                    'resource_index_id': r.resource_index_id,
                    'display_mode': r.display_mode,
                }
                ri = r.resource_index
                if ri:
                    entry['kind'] = ri.kind
                    entry['location'] = ri.location
                    # 兼容前端：输出映射后的 type（video/gallery/text/document）
                    _KIND_TO_TYPE = {
                        'video_file': 'video',
                        'gallery_folder': 'gallery',
                        'text': 'text',
                        'document_file': 'document',
                    }
                    entry['type'] = _KIND_TO_TYPE.get(ri.kind, ri.kind)
                    # 引用级封面：供前端卡片/列表直接取用，避免依赖 gallery/video 实体是否存在
                    entry['cover_url'] = Post._ref_cover_url(ri)
                    # 解析出实际实体（视频 / 图集）的概要
                    if ri.kind == 'video_file':
                        v = Video.query.filter_by(resource_index_id=ri.id).first()
                        if v:
                            entry['video'] = v.to_dict()
                        else:
                            # 只属于帖子、未建 Video 实体的视频：用通用呈现渲染
                            entry['presentation'] = ri.presentation()
                    elif ri.kind == 'gallery_folder':
                        c = Gallery.query.filter_by(resource_index_id=ri.id).first()
                        if c:
                            entry['gallery'] = c.to_dict()
                            # 附带图集页面图片 URL 列表，供前端内联渲染多张图
                            entry['images'] = [
                                f'/gallery-page/{urllib.parse.quote(p.file_path)}'
                                for p in c.pages
                            ]
                        else:
                            # 帖子专属图集（仅 post 模式、未建 Gallery 实体）：
                            # 直接按资源索引目录提供图片，列表与详情页可内联渲染
                            entry['presentation'] = ri.presentation()
                            entry['images'] = [
                                f'/resource-file/{ri.id}/{i}'
                                for i in range(len(_gallery_folder_image_list(ri)))
                            ]
                    elif ri.kind == 'text':
                        t = Text.query.filter_by(resource_index_id=ri.id).first()
                        if t:
                            entry['text'] = t.to_dict()
                        else:
                            entry['presentation'] = ri.presentation()
                    elif ri.kind == 'document_file':
                        # 帖子专属文档附件：提供下载地址，正文/详情页渲染为可下载卡片
                        entry['presentation'] = ri.presentation()
                        entry['docUrl'] = f'/resource-file/{ri.id}/doc'
                items.append(entry)
            d['refs'] = items
        else:
            d['refs'] = [r.to_dict() for r in self.refs]
        d['cover_url'] = self.cover_url
        d['authorName'] = self.author_name
        d['authorUrl'] = self.author_url
        d['sourceUrl'] = self.source_url
        d['groupKey'] = self.group_key
        return d

    @staticmethod
    def _ref_cover_url(ri):
        """按资源索引类型推导单条引用的封面 URL（不依赖 cover 字段是否设置）。"""
        if ri is None:
            return None
        if ri.kind == 'gallery_folder':
            c = Gallery.query.filter_by(resource_index_id=ri.id).first()
            if c and c.hash:
                return c.cover_url or f'/gallery-cover/{c.hash}'
            return f'/resource-file/{ri.id}/0'
        if ri.kind == 'video_file':
            v = Video.query.filter_by(resource_index_id=ri.id).first()
            if v:
                return v.thumbnail or f'/thumbnail/{v.hash}'
        if ri.cover:
            return ri.cover
        return None

    @property
    def cover_url(self):
        """统一封面入口：帖子本身没有资源索引，封面取首个带封面的引用资源（按 refs 顺序）。

        若资源索引未显式设置 cover（历史数据 / 部分入库路径），按资源类型推导：
          - 图集 -> /gallery-cover/{hash}
          - 视频 -> 视频缩略图
        """
        for r in self.refs:
            ri = r.resource_index
            if ri is not None and ri.cover:
                return ri.cover
        # 回退：引用资源的索引未设置 cover 时，按类型推导
        for r in self.refs:
            ri = r.resource_index
            if ri is None:
                continue
            if ri.kind == 'gallery_folder':
                c = Gallery.query.filter_by(resource_index_id=ri.id).first()
                if c and c.hash:
                    return f'/gallery-cover/{c.hash}'
                # 帖子专属图集（无 Gallery 实体）：用图集文件夹首图
                return f'/resource-file/{ri.id}/0'
            elif ri.kind == 'video_file':
                v = Video.query.filter_by(resource_index_id=ri.id).first()
                if v:
                    return v.thumbnail or f'/thumbnail/{v.hash}'
        return None


# 帖子正文内联资源的标记语法：[可见文字](res:资源索引ID:显示模式)
# 显示模式 display_mode ∈ {'link': 仅超链接, 'embed': 超链接 + 内嵌预览}
POST_REF_TOKEN_RE = __import__('re').compile(r'\[([^\]]*)\]\(res:(\d+):(link|embed)\)')


def parse_post_content_tokens(content):
    """解析帖子正文中的内联资源标记，返回有序列表：
    [{resource_index_id:int, display_mode:str, label:str}, ...]
    """
    if not content:
        return []
    out = []
    for m in POST_REF_TOKEN_RE.finditer(content):
        label, rid, mode = m.group(1), m.group(2), m.group(3)
        out.append({
            'resource_index_id': int(rid),
            'display_mode': mode,
            'label': label,
        })
    return out


class PostRef(db.Model):
    """帖子 - 资源索引 关联：一条帖子可引用多个索引（视频 / 图片集 / 文本），可带备注与顺序。

    正文通过标记语法内联引用（见 parse_post_content_tokens），display_mode 控制该引用
    在帖子流里是「仅超链接」还是「超链接 + 内嵌预览」。
    """
    __tablename__ = 'post_refs'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column('dynamic_id', db.Integer, db.ForeignKey('posts.id'), nullable=False)
    resource_index_id = db.Column(db.Integer, db.ForeignKey('resource_index.id'), nullable=False)
    position = db.Column(db.Integer, default=0)
    note = db.Column(db.Text, default='')
    display_mode = db.Column(db.String(16), default='embed', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    post = db.relationship('Post', back_populates='refs')
    resource_index = db.relationship('ResourceIndex')

    def to_dict(self):
        return {
            'id': self.id,
            'post_id': self.post_id,
            'resource_index_id': self.resource_index_id,
            'position': self.position,
            'note': self.note,
            'display_mode': self.display_mode,
        }


def _migrate_dynamic_tables_to_posts():
    """动态 -> 帖子：将历史表 dynamics/dynamic_refs 重命名为 posts/post_refs（幂等，向后兼容旧数据）。"""
    try:
        for old, new in (('dynamics', 'posts'), ('dynamic_refs', 'post_refs')):
            old_e = db.session.execute(
                db.text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"),
                {'n': old}).fetchone()
            new_e = db.session.execute(
                db.text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"),
                {'n': new}).fetchone()
            if old_e and not new_e:
                db.session.execute(db.text(f"ALTER TABLE {old} RENAME TO {new}"))
                db.session.commit()
            elif old_e and new_e:
                # create_all 已在本轮启动生成空的新表，丢弃后把旧表数据迁过来
                db.session.execute(db.text(f"DROP TABLE {new}"))
                db.session.commit()
                db.session.execute(db.text(f"ALTER TABLE {old} RENAME TO {new}"))
                db.session.commit()
    except Exception as e:
        db.session.rollback()
        try:
            from flask import current_app
            current_app.logger.warning(f'动态->帖子 表迁移跳过: {e}')
        except Exception:
            print(f'动态->帖子 表迁移跳过: {e}')


def _migrate_post_ref_display_mode():
    """帖子引用新增 display_mode 列（'link' 仅超链接 / 'embed' 超链接+内嵌预览），幂等。"""
    try:
        cols = [c[1] for c in db.session.execute(
            db.text("PRAGMA table_info(post_refs)")).fetchall()]
        if 'display_mode' not in cols:
            db.session.execute(db.text(
                "ALTER TABLE post_refs ADD COLUMN display_mode VARCHAR(16) NOT NULL DEFAULT 'embed'"))
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        try:
            from flask import current_app
            current_app.logger.warning(f'post_refs.display_mode 迁移跳过: {e}')
        except Exception:
            print(f'post_refs.display_mode 迁移跳过: {e}')


def _migrate_comic_tables_to_galleries():
    """漫画 -> 图集：将历史表 comics/* 重命名为 galleries/*（幂等，向后兼容旧数据）。

    注意：必须先把父表 comics 重命名为 galleries，SQLite 才会同步更新子表
    （comic_pages 等）指向 comics 的外键引用，使其改写为指向 galleries。
    """
    pairs = [
        ('comics', 'galleries'),
        ('comic_pages', 'gallery_pages'),
        ('comic_interactions', 'gallery_interactions'),
        ('comic_progress', 'gallery_progress'),
        ('comic_tags', 'gallery_tags'),
        ('comic_playlists', 'gallery_playlists'),
        ('comic_playlist_items', 'gallery_playlist_items'),
    ]
    try:
        for old, new in pairs:
            old_e = db.session.execute(
                db.text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"),
                {'n': old}).fetchone()
            new_e = db.session.execute(
                db.text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"),
                {'n': new}).fetchone()
            if old_e and not new_e:
                db.session.execute(db.text(f"ALTER TABLE {old} RENAME TO {new}"))
                db.session.commit()
            elif old_e and new_e:
                # create_all 已在本轮启动生成空的新表，丢弃后把旧表数据迁过来
                db.session.execute(db.text(f"DROP TABLE {new}"))
                db.session.commit()
                db.session.execute(db.text(f"ALTER TABLE {old} RENAME TO {new}"))
                db.session.commit()
        # 列名：comic_id -> gallery_id（兼容老版本 SQLite：新增列并拷贝，旧列保留不删除）
        for t in ('galleries', 'gallery_pages', 'gallery_interactions', 'gallery_progress',
                  'gallery_tags', 'gallery_playlist_items', 'collection_videos'):
            try:
                cols = [r[1] for r in db.session.execute(db.text(f"PRAGMA table_info({t})")).fetchall()]
                if 'comic_id' in cols and 'gallery_id' not in cols:
                    db.session.execute(db.text(f"ALTER TABLE {t} ADD COLUMN gallery_id INTEGER"))
                    db.session.execute(db.text(f"UPDATE {t} SET gallery_id = comic_id"))
                    db.session.commit()
            except Exception:
                db.session.rollback()
        # 模式值：membership.mode 'comic' -> 'gallery'
        db.session.execute(db.text(
            "UPDATE resource_memberships SET mode='gallery' WHERE mode='comic'"))
        db.session.commit()
        # 资源索引 kind 'comic_folder' -> 'gallery_folder'
        db.session.execute(db.text(
            "UPDATE resource_index SET kind='gallery_folder' WHERE kind='comic_folder'"))
        db.session.commit()
        # 合集关联 item_type 'comic' -> 'gallery'
        db.session.execute(db.text(
            "UPDATE collection_videos SET item_type='gallery' WHERE item_type='comic'"))
        db.session.commit()
        print('[MIGRATE] 图集表已重命名为图集')
    except Exception as e:
        db.session.rollback()
        try:
            from flask import current_app
            current_app.logger.warning(f'图集->图集 表迁移跳过: {e}')
        except Exception:
            print(f'图集->图集 表迁移跳过: {e}')


def _migrate_gallery_interactions_pk():
    """修复 gallery_interactions 表的 id 主键。

    历史表 comic_interactions 经 RENAME 而来，原始 schema 的 id 为 INT（无 PRIMARY KEY /
    自增），导致：1) 新插入行的 id 为 NULL；2) SQLAlchemy 无法加载 NULL 主键行（.first()/
    .all() 返回 None）；3) 切换点赞时误判「不存在」又尝试 INSERT，触发
    (gallery_id, user_session, interaction_type) 唯一约束冲突，接口返回「操作失败」。

    此处幂等重建表：回填 NULL id 为唯一值，并将 id 改为 INTEGER PRIMARY KEY AUTOINCREMENT。
    """
    try:
        row = db.session.execute(db.text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='gallery_interactions'"
        )).fetchone()
        if not row:
            return
        sql_def = (row[0] or '').upper()
        if 'PRIMARY KEY' in sql_def:
            return  # 已是正确的自增主键，无需处理
        # 1) 为 NULL id 行分配唯一值（基于 rowid，必然唯一且不与小 id 冲突）
        db.session.execute(db.text(
            "UPDATE gallery_interactions SET id = 900000 + rowid WHERE id IS NULL"))
        db.session.commit()
        # 2) 重建为带自增主键的表，保留数据与唯一约束
        db.session.execute(db.text(
            "CREATE TABLE gallery_interactions_new ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " gallery_id INTEGER NOT NULL,"
            " user_session VARCHAR(100) NOT NULL,"
            " interaction_type VARCHAR(20) NOT NULL,"
            " interaction_score REAL DEFAULT 0.0,"
            " created_at DATETIME,"
            " CONSTRAINT _gallery_interaction_uc UNIQUE (gallery_id, user_session, interaction_type)"
            ")"))
        db.session.execute(db.text(
            "INSERT INTO gallery_interactions_new "
            "(id, gallery_id, user_session, interaction_type, interaction_score, created_at) "
            "SELECT id, gallery_id, user_session, interaction_type, interaction_score, created_at "
            "FROM gallery_interactions"))
        db.session.execute(db.text("DROP TABLE gallery_interactions"))
        db.session.execute(db.text("ALTER TABLE gallery_interactions_new RENAME TO gallery_interactions"))
        db.session.execute(db.text(
            "CREATE INDEX IF NOT EXISTS ix_gallery_interactions_gallery_id "
            "ON gallery_interactions(gallery_id)"))
        db.session.commit()
        print('[MIGRATE] gallery_interactions 主键已修复（id 改为自增主键）')
    except Exception as e:
        db.session.rollback()
        try:
            from flask import current_app
            current_app.logger.warning(f'gallery_interactions 主键迁移跳过: {e}')
        except Exception:
            print(f'gallery_interactions 主键迁移跳过: {e}')


def _migrate_gallery_progress_col():
    """修复 gallery_progress 表的 comic_id 遗留列。

    历史表 comic_progress 经 RENAME 而来，原 schema 为 (id, comic_id NOT NULL,
    user_session, page, progress, updated_at)，迁移时仅 ADD 了可为空的 gallery_id
    并拷贝数据，但保留了 NOT NULL 的 comic_id。模型 GalleryProgress 只写 gallery_id，
    插入新行时 comic_id 为 NULL 触发 NOT NULL 约束，接口返回 500。

    此处幂等重建表：将 comic_id 数据并入 gallery_id，并把列收敛为模型期望的
    (id PK 自增, gallery_id NOT NULL, user_session NOT NULL, page, progress,
    in_continue NOT NULL DEFAULT 0, updated_at)，删除遗留的 comic_id。
    """
    try:
        row = db.session.execute(db.text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='gallery_progress'"
        )).fetchone()
        if not row:
            return
        cols = [r[1] for r in db.session.execute(
            db.text("PRAGMA table_info(gallery_progress)")).fetchall()]
        # 若已无 comic_id 列且 gallery_id 存在，则无需处理
        if 'comic_id' not in cols and 'gallery_id' in cols:
            return
        # 1) 把 comic_id 数据补进 gallery_id（仅当 gallery_id 缺失时）
        if 'comic_id' in cols and 'gallery_id' in cols:
            db.session.execute(db.text(
                "UPDATE gallery_progress SET gallery_id = comic_id WHERE gallery_id IS NULL"))
            db.session.commit()
        # 2) 重建表，去掉 comic_id，保证 gallery_id NOT NULL
        db.session.execute(db.text(
            "CREATE TABLE gallery_progress_new ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " gallery_id INTEGER NOT NULL,"
            " user_session VARCHAR(100) NOT NULL,"
            " page INTEGER,"
            " progress FLOAT,"
            " in_continue BOOLEAN NOT NULL DEFAULT 0,"
            " updated_at DATETIME,"
            " CONSTRAINT _gallery_progress_uc UNIQUE (gallery_id, user_session)"
            ")"))
        db.session.execute(db.text(
            "INSERT INTO gallery_progress_new "
            "(id, gallery_id, user_session, page, progress, in_continue, updated_at) "
            "SELECT id, COALESCE(gallery_id, comic_id), user_session, page, progress, "
            "COALESCE(in_continue, 0), updated_at "
            "FROM gallery_progress"))
        db.session.execute(db.text("DROP TABLE gallery_progress"))
        db.session.execute(db.text("ALTER TABLE gallery_progress_new RENAME TO gallery_progress"))
        db.session.execute(db.text(
            "CREATE INDEX IF NOT EXISTS ix_gallery_progress_gallery_id "
            "ON gallery_progress(gallery_id)"))
        db.session.commit()
        print('[MIGRATE] gallery_progress 已收敛 comic_id -> gallery_id')
    except Exception as e:
        db.session.rollback()
        try:
            from flask import current_app
            current_app.logger.warning(f'gallery_progress 列迁移跳过: {e}')
        except Exception:
            print(f'gallery_progress 列迁移跳过: {e}')


def _migrate_gallery_playlists_col():
    """修复图集播放列表表的 comic 遗留列。

    历史表 comic_playlists / comic_playlist_items 经 RENAME 而来：
    - gallery_playlists 仍保留 comic_count 列，而模型 GalleryPlaylist 期望 gallery_count，
      查询时 SELECT 该列不存在导致 /api/gallery-playlists 返回 500。
    - gallery_playlist_items 同时保留 comic_id 与新增的 gallery_id，模型仅用 gallery_id，
      需把 comic_id 数据并入 gallery_id 并删除遗留列，避免语义混乱。

    幂等：列已收敛则跳过。
    """
    try:
        # --- gallery_playlists: comic_count -> gallery_count ---
        pl_cols = [r[1] for r in db.session.execute(
            db.text("PRAGMA table_info(gallery_playlists)")).fetchall()]
        if 'comic_count' in pl_cols and 'gallery_count' not in pl_cols:
            db.session.execute(db.text(
                "CREATE TABLE gallery_playlists_new ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " name VARCHAR(200) NOT NULL,"
                " description TEXT,"
                " user_session VARCHAR(100) NOT NULL,"
                " is_public BOOLEAN,"
                " thumbnail VARCHAR(500),"
                " gallery_count INTEGER DEFAULT 0,"
                " play_count INTEGER DEFAULT 0,"
                " created_at DATETIME,"
                " updated_at DATETIME"
                ")"))
            db.session.execute(db.text(
                "INSERT INTO gallery_playlists_new "
                "(id, name, description, user_session, is_public, thumbnail, gallery_count, "
                " play_count, created_at, updated_at) "
                "SELECT id, name, description, user_session, is_public, thumbnail, "
                "COALESCE(comic_count, 0), COALESCE(play_count, 0), created_at, updated_at "
                "FROM gallery_playlists"))
            db.session.execute(db.text("DROP TABLE gallery_playlists"))
            db.session.execute(db.text("ALTER TABLE gallery_playlists_new RENAME TO gallery_playlists"))
            db.session.execute(db.text(
                "CREATE INDEX IF NOT EXISTS ix_gallery_playlists_user_session "
                "ON gallery_playlists(user_session)"))
            db.session.commit()
            print('[MIGRATE] gallery_playlists 已收敛 comic_count -> gallery_count')

        # --- gallery_playlist_items: comic_id -> gallery_id ---
        pi_cols = [r[1] for r in db.session.execute(
            db.text("PRAGMA table_info(gallery_playlist_items)")).fetchall()]
        if 'comic_id' in pi_cols:
            # 1) 把 comic_id 数据补进 gallery_id（仅当 gallery_id 缺失时）
            if 'gallery_id' in pi_cols:
                db.session.execute(db.text(
                    "UPDATE gallery_playlist_items SET gallery_id = comic_id "
                    "WHERE gallery_id IS NULL"))
                db.session.commit()
            # 2) 重建表去掉 comic_id
            db.session.execute(db.text(
                "CREATE TABLE gallery_playlist_items_new ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " playlist_id INTEGER NOT NULL,"
                " gallery_id INTEGER NOT NULL,"
                " position INTEGER NOT NULL,"
                " added_at DATETIME"
                ")"))
            db.session.execute(db.text(
                "INSERT INTO gallery_playlist_items_new "
                "(id, playlist_id, gallery_id, position, added_at) "
                "SELECT id, playlist_id, COALESCE(gallery_id, comic_id), position, added_at "
                "FROM gallery_playlist_items"))
            db.session.execute(db.text("DROP TABLE gallery_playlist_items"))
            db.session.execute(db.text("ALTER TABLE gallery_playlist_items_new RENAME TO gallery_playlist_items"))
            db.session.execute(db.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS _gallery_playlist_uc "
                "ON gallery_playlist_items(playlist_id, gallery_id)"))
            db.session.execute(db.text(
                "CREATE INDEX IF NOT EXISTS ix_gallery_playlist_items_gallery_id "
                "ON gallery_playlist_items(gallery_id)"))
            db.session.commit()
            print('[MIGRATE] gallery_playlist_items 已收敛 comic_id -> gallery_id')
    except Exception as e:
        db.session.rollback()
        try:
            from flask import current_app
            current_app.logger.warning(f'gallery_playlists 列迁移跳过: {e}')
        except Exception:
            print(f'gallery_playlists 列迁移跳过: {e}')


def _is_valid_hash(h):
    return bool(h) and len(h) == 64 and all(ch in '0123456789abcdefABCDEF' for ch in h)


def _migrate_gallery_bad_hashes():
    """修复历史图集的非法 hash。

    早期 ensure_mode_enrichment 在 resource_index 缺失 hash 时把 hash 回退成了
    文件夹路径（含反斜杠），导致：
      1) 前端路由 /gallery/<hash> 携带反斜杠无法匹配，打开即 404；
      2) 删除接口同样 404，图集删不掉。

    本函数对 hash 非标准 sha256 的图集：能读到原文件夹则按内容重算 hash 并同步
    更新 resource_index.hash；文件夹已丢失则直接删除该图集（含 membership）。
    """
    try:
        bad = Gallery.query.filter(
            db.or_(
                Gallery.hash.is_(None),
                db.func.length(Gallery.hash) != 64,
            )
        ).all()
        # 也兜底：长度 64 但含非 hex 字符（极少见）
        existing = {g.hash for g in Gallery.query.all() if _is_valid_hash(g.hash)}
        fixed = removed = 0
        for g in bad:
            if _is_valid_hash(g.hash):
                continue
            ri = g.resource_index
            folder = ri.location if ri else None
            new_hash = Gallery.generate_hash_from_folder(folder) if folder else None
            if not new_hash or new_hash in existing:
                # 无法重算或哈希冲突：删除该图集（连同 membership）
                try:
                    from sqlalchemy import text as _t
                    db.session.execute(_t(
                        "DELETE FROM resource_memberships WHERE resource_index_id=:rid"
                    ), {'rid': ri.id}) if ri else None
                    if ri:
                        db.session.delete(ri)
                    db.session.delete(g)
                    db.session.commit()
                    removed += 1
                    continue
                except Exception:
                    db.session.rollback()
            # 更新 hash
            g.hash = new_hash
            if ri and not _is_valid_hash(ri.hash):
                ri.hash = new_hash
            existing.add(new_hash)
            db.session.commit()
            fixed += 1
        if fixed or removed:
            print(f'[MIGRATE] 图集非法 hash 修复: 重算 {fixed} 条, 删除 {removed} 条')
    except Exception as e:
        db.session.rollback()
        try:
            from flask import current_app
            current_app.logger.warning(f'图集非法 hash 迁移跳过: {e}')
        except Exception:
            print(f'图集非法 hash 迁移跳过: {e}')


def migrate_resource_index():
    """[资源索引表] 将 videos.local_path / galleries.folder_path 的历史数据回填到 resource_index，
    并为实体设置 resource_index_id，使「实体」与「磁盘位置」解耦。

    - videos / galleries 表已存在，create_all 不会为旧表新增列，因此此处显式 ALTER 补列。
    - 仅对尚未绑定 resource_index 的实体回填（幂等）。
    - 旧的 local_path / folder_path 列保留在库中但不被模型映射（避免破坏性 DROP COLUMN）。
    """
    # 0) 历史表 dynamics/dynamic_refs 重命名为 posts/post_refs（动态 -> 帖子）
    _migrate_dynamic_tables_to_posts()
    # 0.05) 历史表 comics/* 重命名为 galleries/*（漫画 -> 图集）
    _migrate_comic_tables_to_galleries()
    # 0.06) 修复 gallery_interactions 的 id 主键（历史 comic 表无自增主键，导致点赞切换失败）
    _migrate_gallery_interactions_pk()
    # 0.07) 收敛 gallery_progress 的 comic_id 遗留列 -> gallery_id（NOT NULL 约束导致写入 500）
    _migrate_gallery_progress_col()
    # 0.08) 修复历史图集的非法 hash（hash 被存成文件夹路径，导致路由 404 且无法删除）
    _migrate_gallery_bad_hashes()
    # 0.1) 帖子引用新增 display_mode 列
    _migrate_post_ref_display_mode()
    try:
        # 1) 为已存在的实体表新增 resource_index_id 列（指向 resource_index.id）
        for table in ('videos', 'galleries'):
            cols = [r[1] for r in db.session.execute(db.text(f"PRAGMA table_info({table})")).fetchall()]
            if 'resource_index_id' not in cols:
                db.session.execute(db.text(f"ALTER TABLE {table} ADD COLUMN resource_index_id INTEGER"))
                db.session.commit()

        # 2) 视频：local_path -> resource_index(kind='video_file')
        rows = db.session.execute(db.text(
            "SELECT id, local_path, library_id FROM videos "
            "WHERE local_path IS NOT NULL AND local_path != '' AND resource_index_id IS NULL")).fetchall()
        for vid, lp, lib in rows:
            ri = ResourceIndex(kind='video_file', location=lp, library_id=lib)
            db.session.add(ri)
            db.session.flush()
            db.session.execute(db.text("UPDATE videos SET resource_index_id=:rid WHERE id=:vid"),
                               {'rid': ri.id, 'vid': vid})

        # 3) 图集：folder_path -> resource_index(kind='gallery_folder')
        rows = db.session.execute(db.text(
            "SELECT id, folder_path, library_id FROM galleries "
            "WHERE folder_path IS NOT NULL AND folder_path != '' AND resource_index_id IS NULL")).fetchall()
        for cid, fp, lib in rows:
            ri = ResourceIndex(kind='gallery_folder', location=fp, library_id=lib)
            db.session.add(ri)
            db.session.flush()
            db.session.execute(db.text("UPDATE galleries SET resource_index_id=:rid WHERE id=:cid"),
                               {'rid': ri.id, 'cid': cid})

        # 4) 模式归属回填：单资源模式可见性 = membership 行
        #    video_file 资源被 Video 引用 -> mode='video'；gallery_folder 被 Gallery 引用 -> mode='gallery'
        video_count = 0
        for (rid,) in db.session.execute(db.text(
                "SELECT DISTINCT resource_index_id FROM videos WHERE resource_index_id IS NOT NULL")).fetchall():
            if not ResourceModeMembership.query.filter_by(resource_index_id=rid, mode=ResourceMode.VIDEO).first():
                db.session.add(ResourceModeMembership(resource_index_id=rid, mode=ResourceMode.VIDEO))
                video_count += 1
        gallery_m_count = 0
        for (rid,) in db.session.execute(db.text(
                "SELECT DISTINCT resource_index_id FROM galleries WHERE resource_index_id IS NOT NULL")).fetchall():
            if not ResourceModeMembership.query.filter_by(resource_index_id=rid, mode=ResourceMode.GALLERY).first():
                db.session.add(ResourceModeMembership(resource_index_id=rid, mode=ResourceMode.GALLERY))
                gallery_m_count += 1
        print(f'[MIGRATE] mode-memberships 回填完成 (video={video_count}, gallery={gallery_m_count})')

        db.session.commit()
        print(f'[MIGRATE] resource_index 回填完成：视频/图集已解耦到资源索引表')
    except Exception as e:
        db.session.rollback()
        print(f'[WARN] resource_index 迁移跳过: {e}')

    # 5) 统一封面入口：在 resource_index 上新增 cover 列，并把存量封面回填到索引。
    #    独立执行，不依赖上面的旧列迁移步骤，确保存量封面一定能被回填。
    try:
        _ri_cols = [r[1] for r in db.session.execute(db.text("PRAGMA table_info(resource_index)")).fetchall()]
        if 'cover' not in _ri_cols:
            db.session.execute(db.text("ALTER TABLE resource_index ADD COLUMN cover VARCHAR(2000)"))
            db.session.commit()
        # 视频封面：优先用实体 thumbnail，兜底为缩略图路由
        for v in Video.query.filter(Video.resource_index_id.isnot(None)).all():
            ri = v.resource_index
            if ri is not None and not ri.cover:
                ri.cover = v.thumbnail or f'/thumbnail/{v.hash}'
        # 图集封面：第一页封面路由（/gallery-cover/{hash}）
        for c in Gallery.query.filter(Gallery.resource_index_id.isnot(None)).all():
            ri = c.resource_index
            if ri is not None and not ri.cover and c.hash:
                ri.cover = f'/gallery-cover/{c.hash}'
        db.session.commit()
        print(f'[MIGRATE] resource_index.cover 封面回填完成')
    except Exception as e:
        db.session.rollback()
        print(f'[WARN] resource_index.cover 迁移跳过: {e}')

    # 6) 资源「是否隐藏」标志列：create_all 会为新库建列，此处补旧库列（默认 False）。
    try:
        _ri_cols = [r[1] for r in db.session.execute(db.text("PRAGMA table_info(resource_index)")).fetchall()]
        if 'hidden' not in _ri_cols:
            db.session.execute(db.text("ALTER TABLE resource_index ADD COLUMN hidden BOOLEAN DEFAULT 0 NOT NULL"))
            db.session.commit()
        print(f'[MIGRATE] resource_index.hidden 列就绪')
    except Exception as e:
        db.session.rollback()
        print(f'[WARN] resource_index.hidden 迁移跳过: {e}')


def migrate_collection_videos_schema():
    """[TEST] 为 collection_videos 增加 item_type / gallery_id 列（支持收藏夹收纳图集）。

    仅当列不存在时执行 ALTER，兼容旧库；create_all 不会为已存在的表新增列。
    """
    try:
        insp = db.inspect(db.engine)
        existing = {c['name'] for c in insp.get_columns('collection_videos')}
        with db.engine.begin() as conn:
            if 'item_type' not in existing:
                conn.execute(db.text(
                    "ALTER TABLE collection_videos ADD COLUMN item_type VARCHAR(20) NOT NULL DEFAULT 'video'"))
            if 'gallery_id' not in existing:
                conn.execute(db.text(
                    "ALTER TABLE collection_videos ADD COLUMN gallery_id INTEGER"))
    except Exception as e:
        print(f'[WARN] collection_videos 迁移跳过: {e}')


def migrate_owner_columns():
    """为 videos / galleries 增加 owner_id 列（资源归属者），并把历史资源归属 root。

    仅当列不存在时执行 ALTER，兼容旧库；create_all 不会为已存在的表新增列。
    历史资源（owner_id 为 NULL）统一归属到 root 用户（id=1），保证其可管理。
    """
    try:
        from sqlalchemy import inspect as sa_inspect
        insp = sa_inspect(db.engine)
        root_user = User.query.filter_by(role=UserRole.ROOT).order_by(User.id).first()
        root_id = root_user.id if root_user else 1

        for table in ('videos', 'galleries'):
            cols = {c['name'] for c in insp.get_columns(table)}
            if 'owner_id' not in cols:
                with db.engine.begin() as conn:
                    conn.execute(db.text(
                        f"ALTER TABLE {table} ADD COLUMN owner_id INTEGER"))
                # 历史资源归属 root
                with db.engine.begin() as conn:
                    conn.execute(db.text(
                        f"UPDATE {table} SET owner_id = :rid WHERE owner_id IS NULL"),
                        {'rid': root_id})
                print(f'[INFO] {table}.owner_id 迁移完成，历史资源归属 root(id={root_id})')
    except Exception as e:
        print(f'[WARN] owner_id 迁移跳过: {e}')


def migrate_video_libraries_rename():
    """将旧表 video_libraries 重命名为 resource_libraries（兼容历史库）。

    仅当 video_libraries 表仍存在时执行 ALTER，已重命名过的库不受影响。
    SQLite 会自动将 videos / galleries / tags 等表的 library_id 外键引用同步到新表名。
    """
    try:
        with db.engine.connect() as conn:
            res = conn.execute(db.text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='video_libraries'"))
            if res.fetchone():
                conn.execute(db.text('ALTER TABLE video_libraries RENAME TO resource_libraries'))
                conn.commit()
                print('[MIGRATE] video_libraries 已重命名为 resource_libraries')
    except Exception as e:
        print(f'[WARN] video_libraries 重命名跳过: {e}')


def migrate_trash_columns():
    """为 videos / galleries 增加回收站字段 in_trash / trashed_at（兼容历史库）。"""
    try:
        with db.engine.connect() as conn:
            for table in ('videos', 'galleries'):
                cols = [r[1] for r in conn.execute(
                    db.text(f"PRAGMA table_info({table})")).fetchall()]
                if 'in_trash' not in cols:
                    conn.execute(db.text(
                        f"ALTER TABLE {table} ADD COLUMN in_trash BOOLEAN NOT NULL DEFAULT 0"))
                if 'trashed_at' not in cols:
                    conn.execute(db.text(
                        f"ALTER TABLE {table} ADD COLUMN trashed_at DATETIME"))
            conn.commit()
            print('[MIGRATE] trash 字段已就绪')
    except Exception as e:
        print(f'[WARN] trash 字段迁移跳过: {e}')


def migrate_watch_later_deleted_at():
    """为 watch_later 增加软删除字段 deleted_at（兼容历史库）。

    移除「稍后再看」条目改为软删除（只打墓碑），需要该列存在才能判定条目是否已删除。
    仅当列不存在时执行 ALTER，兼容旧库；create_all 不会为已存在的表新增列。
    """
    try:
        with db.engine.connect() as conn:
            cols = [r[1] for r in conn.execute(
                db.text("PRAGMA table_info(watch_later)")).fetchall()]
            if 'deleted_at' not in cols:
                conn.execute(db.text(
                    "ALTER TABLE watch_later ADD COLUMN deleted_at DATETIME"))
                conn.commit()
                print('[MIGRATE] watch_later.deleted_at 已新增')
    except Exception as e:
        print(f'[WARN] watch_later.deleted_at 迁移跳过: {e}')


def migrate_tag_qualifiers():
    """标签补充项（qualifiers）重构：用 qualifiers 替代 display_name，并为 video_tags 增加 selected_qualifiers。

    - tags 表：新增 qualifiers 列；若存在旧 display_name 列则删除。
    - video_tags 表：新增 selected_qualifiers 列。
    仅当列不存在时执行，兼容旧库。
    """
    try:
        with db.engine.connect() as conn:
            # tags 表
            tag_cols = [r[1] for r in conn.execute(
                db.text("PRAGMA table_info(tags)")).fetchall()]
            if 'qualifiers' not in tag_cols:
                conn.execute(db.text("ALTER TABLE tags ADD COLUMN qualifiers TEXT"))
                print('[MIGRATE] tags.qualifiers 已新增')
            if 'display_name' in tag_cols:
                try:
                    conn.execute(db.text("ALTER TABLE tags DROP COLUMN display_name"))
                    print('[MIGRATE] tags.display_name 已移除')
                except Exception as e:
                    # 旧版 SQLite 不支持 DROP COLUMN，保留空列即可（模型已不再引用）
                    print(f'[INFO] tags.display_name 保留（SQLite 不支持删除列）: {e}')
            # video_tags 表
            vt_cols = [r[1] for r in conn.execute(
                db.text("PRAGMA table_info(video_tags)")).fetchall()]
            if 'selected_qualifiers' not in vt_cols:
                conn.execute(db.text("ALTER TABLE video_tags ADD COLUMN selected_qualifiers TEXT"))
                print('[MIGRATE] video_tags.selected_qualifiers 已新增')
            conn.commit()
    except Exception as e:
        print(f'[WARN] tag qualifiers 迁移跳过: {e}')


def migrate_post_title_nullable():
    """帖子标题改为可空：支持用户不写标题的帖子（存储 NULL，前端展示时不渲染标题区域）。

    SQLite 不支持直接 ALTER COLUMN 去掉 NOT NULL，采用重建表法，保留全部数据。
    幂等：仅当 posts.title 仍为 NOT NULL 时执行。
    """
    try:
        with db.engine.connect() as conn:
            cols = {r[1]: r for r in conn.execute(
                db.text("PRAGMA table_info(posts)")).fetchall()}
            if 'title' not in cols:
                print('[INFO] posts 表不存在，跳过标题可空迁移')
                return
            if cols['title'][3] == 0:  # notnull == 0 表示已可空
                print('[INFO] posts.title 已可空，跳过迁移')
                return
            # 重建表：title 改为可空
            conn.execute(db.text("PRAGMA foreign_keys=OFF"))
            conn.execute(db.text("BEGIN"))
            conn.execute(db.text("""
                CREATE TABLE posts_new (
                    id INTEGER NOT NULL PRIMARY KEY,
                    title VARCHAR(300),
                    content TEXT,
                    owner_id INTEGER,
                    library_id INTEGER,
                    in_trash BOOLEAN,
                    trashed_at DATETIME,
                    created_at DATETIME,
                    updated_at DATETIME,
                    FOREIGN KEY(owner_id) REFERENCES users (id),
                    FOREIGN KEY(library_id) REFERENCES resource_libraries (id)
                )
            """))
            conn.execute(db.text("""
                INSERT INTO posts_new (id, title, content, owner_id, library_id,
                                       in_trash, trashed_at, created_at, updated_at)
                SELECT id, title, content, owner_id, library_id,
                       in_trash, trashed_at, created_at, updated_at FROM posts
            """))
            conn.execute(db.text("DROP TABLE posts"))
            conn.execute(db.text("ALTER TABLE posts_new RENAME TO posts"))
            conn.execute(db.text("COMMIT"))
            conn.execute(db.text("PRAGMA foreign_keys=ON"))
            print('[MIGRATE] posts.title 已改为可空')
    except Exception as e:
        print(f'[WARN] post title 可空迁移跳过: {e}')


def migrate_post_source_columns():
    """为 posts 表补充来源字段：author_name / author_url / source_url（兼容历史库）。

    供 X 下载器回填作者与原始推文地址，前端展示为可点击超链接。幂等。
    """
    try:
        with db.engine.connect() as conn:
            cols = [r[1] for r in conn.execute(
                db.text("PRAGMA table_info(posts)")).fetchall()]
            for col in ('author_name', 'author_url', 'source_url'):
                if col not in cols:
                    conn.execute(db.text(
                        f"ALTER TABLE posts ADD COLUMN {col} VARCHAR(1000)"))
                    print(f'[MIGRATE] posts.{col} 已新增')
            conn.commit()
    except Exception as e:
        print(f'[WARN] post source 列迁移跳过: {e}')


def migrate_post_group_key():
    """为 posts 表补充 group_key 列（兼容历史库），用于重复下载时定位并更新同一条帖子。幂等。"""
    try:
        with db.engine.connect() as conn:
            cols = [r[1] for r in conn.execute(
                db.text("PRAGMA table_info(posts)")).fetchall()]
            if 'group_key' not in cols:
                conn.execute(db.text("ALTER TABLE posts ADD COLUMN group_key VARCHAR(200)"))
                conn.execute(db.text("CREATE INDEX IF NOT EXISTS ix_posts_group_key ON posts (group_key)"))
                conn.commit()
                print('[MIGRATE] posts.group_key 已新增')
    except Exception as e:
        print(f'[WARN] post group_key 列迁移跳过: {e}')


MAIN_LIBRARY_NAME = '主资源库'


def migrate_main_library():
    """将「无归属主库」的资源统一归入一个受 is_active 管控的「主资源库」。

    背景：早期视频/图集的 library_id 允许为 NULL（视为「主数据库」），但这些资源
    对 is_active 过滤免疫——取消所有资源库激活后仍会对外可见，造成越权泄露。
    本迁移创建「主资源库」（priority=0, is_active=True），并给其附加通用权限
    (user_id=NULL) 以保持既有「未登录用户也能看主库」的语义；随后把 library_id
    为 NULL 的 videos / galleries 回填到主库，使所有资源都归属某个库，NULL 语义消亡。

    幂等：已存在「主资源库」则复用；已回填的资源不会重复处理。
    """
    try:
        main_lib = ResourceLibrary.query.filter_by(name=MAIN_LIBRARY_NAME).first()
        if not main_lib:
            main_lib = ResourceLibrary(
                name=MAIN_LIBRARY_NAME,
                description='系统主资源库，承载未指定归属的视频与图集',
                db_path='libraries',
                db_file='main.db',
                is_active=True,
            )
            db.session.add(main_lib)
            db.session.flush()
            # 默认通用权限：所有用户（含未登录游客）均可访问主库，维持历史可见性语义
            if not LibraryPermission.query.filter_by(
                library_id=main_lib.id, user_id=None
            ).first():
                db.session.add(LibraryPermission(
                    library_id=main_lib.id, user_id=None,
                    role='user', access_level='full',
                    permissions={'browse': True, 'play': True, 'download': True,
                                 'upload': True, 'edit': True, 'delete': True},
                ))
            print(f'[MIGRATE] 创建主资源库 id={main_lib.id}')

        # 回填 NULL 归属资源到主库
        for table in ('videos', 'galleries'):
            try:
                n = db.session.execute(
                    db.text(
                        f"UPDATE {table} SET library_id = :lid "
                        f"WHERE library_id IS NULL"
                    ),
                    {'lid': main_lib.id},
                ).rowcount
                if n:
                    print(f'[MIGRATE] {table}: {n} 条 NULL 归属资源已归入主资源库')
            except Exception as e:
                print(f'[WARN] {table} 回填主库跳过: {e}')

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f'[WARN] 主资源库迁移跳过: {e}')




