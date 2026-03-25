#!/usr/bin/env python3
"""测试标签权限过滤问题"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'msa-web'))

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from enum import IntEnum

# 定义UserRole枚举
class UserRole(IntEnum):
    USER = 1
    ADMIN = 2
    ROOT = 3

# 创建Flask应用
app = Flask(__name__)
db_path = os.path.join(os.path.dirname(__file__), 'msa-web', 'instance', 'dplayer.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# 定义模型（只定义需要的）
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120))
    role = db.Column(db.Integer, default=UserRole.USER)

class VideoLibrary(db.Model):
    __tablename__ = 'video_libraries'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    path = db.Column(db.String(500), nullable=False)
    is_active = db.Column(db.Boolean, default=True)

class Video(db.Model):
    __tablename__ = 'videos'
    id = db.Column(db.Integer, primary_key=True)
    hash = db.Column(db.String(64), unique=True, nullable=False)
    title = db.Column(db.String(255))
    library_id = db.Column(db.Integer, db.ForeignKey('video_libraries.id'))

class Tag(db.Model):
    __tablename__ = 'tags'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    path = db.Column(db.String(200), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('tags.id'), nullable=True)
    library_id = db.Column(db.Integer, db.ForeignKey('video_libraries.id'), nullable=True)
    children = db.relationship('Tag', backref=db.backref('parent', remote_side=[id]))

class VideoTag(db.Model):
    __tablename__ = 'video_tags'
    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey('videos.id'), nullable=False)
    tag_id = db.Column(db.Integer, db.ForeignKey('tags.id'), nullable=False)

class LibraryPermission(db.Model):
    __tablename__ = 'library_permissions'
    id = db.Column(db.Integer, primary_key=True)
    library_id = db.Column(db.Integer, db.ForeignKey('video_libraries.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    group_id = db.Column(db.Integer, db.ForeignKey('library_user_groups.id'), nullable=True)

class LibraryUserGroupMember(db.Model):
    __tablename__ = 'library_user_group_members'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('library_user_groups.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

def test_tag_permission():
    """测试标签权限"""
    
    with app.app_context():
        print("=" * 60)
        print("标签权限诊断")
        print("=" * 60)
        
        # 1. 查询所有用户
        print("\n【用户列表】")
        users = User.query.all()
        for user in users:
            role_name = 'ROOT' if user.role == 3 else '管理员' if user.role == 2 else '普通用户' if user.role == 1 else '未知'
            print(f"  - ID: {user.id}, 用户名: {user.username}, 角色: {user.role} ({role_name})")
        
        # 2. 查询所有视频库
        print("\n【视频库列表】")
        libraries = VideoLibrary.query.all()
        for lib in libraries:
            print(f"  - ID: {lib.id}, 名称: {lib.name}, 路径: {lib.path}, 活跃: {lib.is_active}")
            # 统计该视频库的视频数量
            video_count = Video.query.filter_by(library_id=lib.id).count()
            print(f"    视频数量: {video_count}")
        
        # 3. 查询视频总数
        print("\n【视频统计】")
        total_videos = Video.query.count()
        print(f"  总视频数量: {total_videos}")
        
        # 按视频库统计
        for lib in libraries:
            count = Video.query.filter_by(library_id=lib.id).count()
            print(f"  视频库 {lib.name}: {count} 个视频")
        
        # 4. 查询标签统计
        print("\n【标签统计】")
        tags = Tag.query.all()
        print(f"  总标签数量: {len(tags)}")
        
        # 5. 模拟权限过滤逻辑
        print("\n【模拟权限过滤】")
        for user in users:
            print(f"\n用户: {user.username} (角色: {user.role})")
            
            # 计算用户可访问的视频库
            allowed_library_ids = []
            if user.role in [UserRole.ADMIN, UserRole.ROOT]:
                all_active_libs = VideoLibrary.query.filter_by(is_active=True).all()
                allowed_library_ids = [lib.id for lib in all_active_libs]
            else:
                user_perms = LibraryPermission.query.filter_by(user_id=user.id).all()
                for perm in user_perms:
                    lib = VideoLibrary.query.get(perm.library_id)
                    if lib and lib.is_active:
                        allowed_library_ids.append(perm.library_id)
                
                # 检查用户组权限
                user_groups = LibraryUserGroupMember.query.filter_by(user_id=user.id).all()
                for ugm in user_groups:
                    group_perms = LibraryPermission.query.filter_by(group_id=ugm.group_id).all()
                    for perm in group_perms:
                        lib = VideoLibrary.query.get(perm.library_id)
                        if lib and lib.is_active and perm.library_id not in allowed_library_ids:
                            allowed_library_ids.append(perm.library_id)
            
            print(f"  可访问视频库ID: {allowed_library_ids}")
            
            # 计算可访问的视频数量
            if allowed_library_ids:
                from sqlalchemy import or_ as sql_or
                video_count = Video.query.filter(
                    sql_or(
                        Video.library_id == None,
                        Video.library_id.in_(allowed_library_ids)
                    )
                ).count()
            else:
                video_count = 0
            
            print(f"  可访问视频数量: {video_count}")

if __name__ == '__main__':
    test_tag_permission()
