"""
初始化root账号脚本
用于手动创建或重置root账号

用法:
    python scripts/init_root.py
"""
import os
import sys

# 添加项目路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, 'msas-web'))

from flask import Flask
from core.models import db, User, UserRole
from auth_service import init_root_user

def create_app():
    """创建Flask应用实例"""
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'init-root-secret-key'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(
        project_root, 'msas-web', 'instance', 'dplayer.db'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    return app

def main():
    """主函数"""
    print("=" * 60)
    print("DPlayer - Root账号初始化工具")
    print("=" * 60)
    
    app = create_app()
    
    with app.app_context():
        # 确保数据库表存在
        db.create_all()
        print("[OK] 数据库初始化完成")
        
        # 检查当前root账号状态
        existing_root = User.query.filter_by(role=UserRole.ROOT).first()
        
        if existing_root:
            print(f"[INFO] 已存在root账号: {existing_root.username}")
            print("[INFO] 如需重置密码，请使用管理员功能或联系系统管理员")
        else:
            print("[INFO] 未找到root账号，正在创建...")
            init_root_user()
            
            # 验证创建结果
            new_root = User.query.filter_by(role=UserRole.ROOT).first()
            if new_root:
                print("[OK] root账号创建成功!")
                print(f"[INFO] 用户名: {new_root.username}")
                print(f"[INFO] 密码: <初始密码>")
                print(f"[INFO] 角色: {new_root.role_name}")
            else:
                print("[ERROR] root账号创建失败!")
                return 1
        
        print("=" * 60)
        print("初始化完成")
        print("=" * 60)
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
