"""检查每个库DB的名字和文件名对应关系"""
import sqlite3
import os

BASE = r'c:\Users\<用户>\<工作目录>\Claw\Dplayer2.0\data\libraries'
for fname in sorted(os.listdir(BASE)):
    if not fname.endswith('.db'):
        continue
    conn = sqlite3.connect(os.path.join(BASE, fname))
    cur = conn.cursor()
    cur.execute('SELECT id, name, db_file FROM video_libraries')
    rows = cur.fetchall()
    cur.execute('SELECT COUNT(*) FROM videos')
    vcnt = cur.fetchone()[0]
    conn.close()
    print(f'文件: {fname}  (videos={vcnt})')
    for r in rows:
        print(f'   库记录: id={r[0]}, name={r[1]}, db_file={r[2]}')
    print()
