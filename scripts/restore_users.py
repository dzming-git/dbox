"""
从视频库 DB 恢复丢失的用户到主数据库
"""
import sqlite3
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_LIBRARIES_DIR = os.path.join(str(BASE_DIR), 'data', 'libraries')
MAIN_DB = os.path.join(str(BASE_DIR), 'data', 'databases', 'dplayer.db')

# 从所有库 DB 收集用户（去重）
all_users = {}  # username -> (id, username, password_hash, role, is_active, email, ...)

for fname in sorted(os.listdir(DATA_LIBRARIES_DIR)):
    if not fname.endswith('.db'):
        continue
    fpath = os.path.join(DATA_LIBRARIES_DIR, fname)
    try:
        lconn = sqlite3.connect(fpath)
        lcur = lconn.cursor()
        # 查 users 表结构
        lcur.execute('PRAGMA table_info(users)')
        cols = [c[1] for c in lcur.fetchall()]
        print(f'{fname} users列: {cols}')
        lcur.execute('SELECT * FROM users')
        rows = lcur.fetchall()
        for row in rows:
            uname = row[cols.index('username')]
            if uname not in all_users:
                all_users[uname] = (cols, row)
        lconn.close()
    except Exception as e:
        print(f'x {fname}: {e}')

print(f'\n收集到 {len(all_users)} 个用户: {list(all_users.keys())}')

# 与主数据库比较
conn = sqlite3.connect(MAIN_DB)
cur = conn.cursor()
cur.execute('PRAGMA table_info(users)')
main_cols = [c[1] for c in cur.fetchall()]
print(f'\n主DB users列: {main_cols}')
cur.execute('SELECT username FROM users')
existing_users = {r[0] for r in cur.fetchall()}
print(f'主DB已有用户: {existing_users}')

# 插入缺失的用户
for uname, (src_cols, src_row) in all_users.items():
    if uname in existing_users:
        print(f'  [skip] {uname} 已存在')
        continue
    # 构建插入数据（只取主DB有的列）
    values = {}
    for col in src_cols:
        if col in main_cols:
            values[col] = src_row[src_cols.index(col)]
    
    # 排除 id（让主DB自动分配）
    if 'id' in values:
        del values['id']
    
    cols_str = ', '.join(values.keys())
    placeholders = ', '.join(['?'] * len(values))
    sql = f'INSERT INTO users ({cols_str}) VALUES ({placeholders})'
    try:
        cur.execute(sql, list(values.values()))
        print(f'  [+] 已恢复用户: {uname} (role={values.get("role", "?")})')
    except Exception as e:
        print(f'  [x] 插入 {uname} 失败: {e}')

conn.commit()

print('\n=== 最终主DB用户列表 ===')
cur.execute('SELECT id, username, role, is_active FROM users')
for row in cur.fetchall():
    print(f'  ID={row[0]}  用户名={row[1]}  role={row[2]}  active={row[3]}')

conn.close()
