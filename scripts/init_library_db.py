#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
初始化视频库管理数据库表
"""
import sqlite3
import os
import sys

# 设置输出编码
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB_PATH = r'c:\Users\<用户>\<工作目录>\Claw\Dplayer2.0\instance\dplayer.db'

def create_tables():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # video_libraries 表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS video_libraries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name VARCHAR(100) NOT NULL UNIQUE,
        description TEXT,
        db_path VARCHAR(500) NOT NULL,
        db_file VARCHAR(200) NOT NULL,
        is_active BOOLEAN DEFAULT 1,
        config TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    print('✓ video_libraries 表')
    
    # library_permissions 表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS library_permissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        library_id INTEGER NOT NULL,
        user_id INTEGER,
        group_id INTEGER,
        role VARCHAR(20) NOT NULL DEFAULT 'user',
        access_level VARCHAR(20) NOT NULL DEFAULT 'read',
        permissions TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        created_by INTEGER,
        FOREIGN KEY (library_id) REFERENCES video_libraries(id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        UNIQUE(library_id, user_id),
        UNIQUE(library_id, group_id)
    )
    ''')
    print('✓ library_permissions 表')
    
    # library_user_groups 表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS library_user_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name VARCHAR(50) NOT NULL UNIQUE,
        description TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    print('✓ library_user_groups 表')
    
    # library_user_group_members 表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS library_user_group_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (group_id) REFERENCES library_user_groups(id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        UNIQUE(group_id, user_id)
    )
    ''')
    print('✓ library_user_group_members 表')
    
    # library_audit_log 表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS library_audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        library_id INTEGER,
        target_user_id INTEGER,
        action VARCHAR(20) NOT NULL,
        old_value TEXT,
        new_value TEXT,
        operator_id INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (library_id) REFERENCES video_libraries(id),
        FOREIGN KEY (target_user_id) REFERENCES users(id),
        FOREIGN KEY (operator_id) REFERENCES users(id)
    )
    ''')
    print('✓ library_audit_log 表')
    
    conn.commit()
    conn.close()
    
    print('\n所有视频库管理表创建完成!')
    
    # 验证
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'library%'")
    tables = [t[0] for t in cursor.fetchall()]
    print(f'\n现有视频库相关表: {tables}')
    conn.close()

if __name__ == '__main__':
    create_tables()
