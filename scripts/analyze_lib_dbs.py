"""分析每个库 DB 文件的实际内容，建立正确的文件->库名映射"""
import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBRARIES_DIR = os.path.join(BASE_DIR, 'data', 'libraries')
MAIN_DB = os.path.join(BASE_DIR, 'data', 'databases', 'dplayer.db')

for fname in sorted(os.listdir(LIBRARIES_DIR)):
    if not fname.endswith('.db'):
        continue
    fpath = os.path.join(LIBRARIES_DIR, fname)
    conn = sqlite3.connect(fpath)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    print(f'\n=== 文件: {fname} ===')
    
    # 列出所有库记录
    cur.execute('SELECT id, name, db_file FROM video_libraries')
    libs = cur.fetchall()
    print(f'  库记录:')
    for lib in libs:
        cur.execute('SELECT COUNT(*) FROM videos WHERE library_id=?', (lib['id'],))
        vcnt = cur.fetchone()[0]
        print(f'    id={lib["id"]}  name={lib["name"]}  db_file={lib["db_file"]}  -> videos={vcnt}')
    
    # 检查 db_file 等于自身文件名的记录
    cur.execute('SELECT id, name FROM video_libraries WHERE db_file=?', (fname,))
    self_rec = cur.fetchone()
    if self_rec:
        print(f'  [自身记录] id={self_rec["id"]}  name={self_rec["name"]}')
    else:
        print(f'  [无自身记录，db_file 不匹配]')
    
    conn.close()
