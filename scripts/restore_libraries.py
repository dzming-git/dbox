"""
修正视频库注册：根据文件名推断库名（去掉时间戳后缀）
文件名格式：{库名}_{时间戳}.db
"""
import sqlite3
import os
import re
import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_LIBRARIES_DIR = os.path.join(str(BASE_DIR), 'data', 'libraries')
MAIN_DB = os.path.join(str(BASE_DIR), 'data', 'databases', 'dplayer.db')

def parse_lib_name(fname):
    """从文件名提取库名：去掉末尾的 _数字戳.db"""
    base = fname[:-3]  # 去掉 .db
    # 去掉末尾 _数字
    m = re.match(r'^(.+)_(\d+)$', base)
    if m:
        return m.group(1)
    return base

conn = sqlite3.connect(MAIN_DB)
cur = conn.cursor()

# 清空已有记录重新注册
cur.execute('DELETE FROM video_libraries')
print('已清空旧的 video_libraries 记录')

inserted = 0
for fname in sorted(os.listdir(DATA_LIBRARIES_DIR)):
    if not fname.endswith('.db'):
        continue
    fpath = os.path.join(DATA_LIBRARIES_DIR, fname)
    
    lib_name = parse_lib_name(fname)
    
    try:
        lconn = sqlite3.connect(fpath)
        lcur = lconn.cursor()
        lcur.execute('SELECT COUNT(*) FROM videos')
        vcnt = lcur.fetchone()[0]
        lconn.close()
    except:
        vcnt = 0
    
    now = datetime.datetime.now().isoformat()
    cur.execute('''
        INSERT INTO video_libraries (name, description, db_path, db_file, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, ?, ?)
    ''', (lib_name, '', DATA_LIBRARIES_DIR, fname, now, now))
    print(f'+ 已注册: [{lib_name}]  文件={fname}  视频数={vcnt}')
    inserted += 1

conn.commit()

# 验证结果
print('\n=== 最终注册结果 ===')
cur.execute('SELECT id, name, db_path, db_file, is_active FROM video_libraries')
for row in cur.fetchall():
    print(f'  ID={row[0]}  名称={row[1]}  文件={row[3]}  active={row[4]}')

conn.close()
print(f'\n完成，共注册 {inserted} 个视频库')
