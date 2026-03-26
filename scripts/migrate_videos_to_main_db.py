"""
精确迁移脚本：根据分析结果，从源文件把正确的视频数据导入主 DB
数据来源：porn_girl_1774197682.db 包含两个真实库的数据
  - library_id=3 (porn): 948个视频
  - library_id=4 (喜鹊谋杀案): 6个视频
"""
import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
MAIN_DB = os.path.join(DATA_DIR, 'databases', 'dplayer.db')
LIBRARIES_DIR = os.path.join(DATA_DIR, 'libraries')

# =====================================================
# 迁移映射：(源文件, 源library_id) -> 主DB library_id
# =====================================================
# 分析结果：
#   porn_girl_1774197682.db 里 library_id=3 的视频 -> 应属于 porn 库
#   porn_girl_1774197682.db 里 library_id=4 的视频 -> 应属于 喜鹊谋杀案 库
# 主DB当前注册：
#   ID=2 porn_girl (文件名是混乱的，但我们把这批 library_id=3 的数据对应到 '喜鹊谋杀案' 库)
#   ID=3 喜鹊谋杀案
# 需要先搞清楚主DB库名和实际数据的对应

mconn = sqlite3.connect(MAIN_DB)
mconn.row_factory = sqlite3.Row
mcur = mconn.cursor()

# 打印主DB当前库注册
print('主DB当前视频库注册:')
mcur.execute('SELECT id, name, db_file FROM video_libraries')
main_libs = {row['id']: dict(row) for row in mcur.fetchall()}
for lib in main_libs.values():
    print(f"  ID={lib['id']}  name={lib['name']}  file={lib['db_file']}")

# 重新确定：源文件里两个库 id=3(porn) 和 id=4(喜鹊谋杀案)
# 主DB里：需要 porn 和 喜鹊谋杀案 两个对应的 id
mcur.execute("SELECT id FROM video_libraries WHERE name='porn'")
r = mcur.fetchone()
main_porn_id = r[0] if r else None

mcur.execute("SELECT id FROM video_libraries WHERE name='喜鹊谋杀案'")
r = mcur.fetchone()
main_xique_id = r[0] if r else None

print(f'\n主DB porn ID={main_porn_id}, 喜鹊谋杀案 ID={main_xique_id}')

# 如果缺少，自动创建
import datetime
now = datetime.datetime.now().isoformat()
if not main_porn_id:
    mcur.execute('''INSERT INTO video_libraries (name, description, db_path, db_file, is_active, created_at, updated_at)
                    VALUES (?,?,?,?,1,?,?)''', ('porn', '', 'libraries', 'porn_girl_1774197682.db', now, now))
    main_porn_id = mcur.lastrowid
    print(f'  [自动创建] porn ID={main_porn_id}')

if not main_xique_id:
    mcur.execute('''INSERT INTO video_libraries (name, description, db_path, db_file, is_active, created_at, updated_at)
                    VALUES (?,?,?,?,1,?,?)''', ('喜鹊谋杀案', '', 'libraries', 'porn_girl_1774197682.db', now, now))
    main_xique_id = mcur.lastrowid
    print(f'  [自动创建] 喜鹊谋杀案 ID={main_xique_id}')

# =====================================================
# 迁移视频
# =====================================================
src_file = os.path.join(LIBRARIES_DIR, 'porn_girl_1774197682.db')
lconn = sqlite3.connect(src_file)
lconn.row_factory = sqlite3.Row
lcur = lconn.cursor()

# 迁移映射：源 library_id -> 主 DB library_id
transfer_map = {
    3: main_porn_id,       # porn
    4: main_xique_id,      # 喜鹊谋杀案
}

total_migrated = 0
total_skipped = 0

for src_lib_id, dst_lib_id in transfer_map.items():
    lcur.execute('SELECT * FROM videos WHERE library_id=?', (src_lib_id,))
    videos = lcur.fetchall()
    migrated = skipped = 0
    
    for v in videos:
        mcur.execute('SELECT id FROM videos WHERE hash=?', (v['hash'],))
        if mcur.fetchone():
            skipped += 1
            continue
        mcur.execute('''
            INSERT INTO videos 
            (hash, title, description, url, thumbnail, duration, file_size,
             view_count, like_count, download_count, priority, min_role,
             is_downloaded, local_path, library_id, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            v['hash'], v['title'], v['description'] if v['description'] else '',
            v['url'], v['thumbnail'],
            v['duration'], v['file_size'],
            v['view_count'] or 0, v['like_count'] or 0, v['download_count'] or 0,
            v['priority'] or 0, v['min_role'] if v['min_role'] is not None else 0,
            v['is_downloaded'] or 0, v['local_path'],
            dst_lib_id,
            v['created_at'], v['updated_at']
        ))
        migrated += 1
    
    src_name = 'porn' if src_lib_id == 3 else '喜鹊谋杀案'
    dst_name = main_libs.get(dst_lib_id, {}).get('name', f'ID={dst_lib_id}')
    print(f'  [{src_name}] 迁移 {migrated} 个，跳过 {skipped} 个 -> 主DB库[{dst_lib_id}:{src_name}]')
    total_migrated += migrated
    total_skipped += skipped

# 迁移 porn_1774079885.db 里的1个测试视频
src_file2 = os.path.join(LIBRARIES_DIR, 'porn_1774079885.db')
lconn2 = sqlite3.connect(src_file2)
lconn2.row_factory = sqlite3.Row
lcur2 = lconn2.cursor()
lcur2.execute('SELECT * FROM videos')
test_videos = lcur2.fetchall()

# 测试视频库在主DB里的ID
mcur.execute("SELECT id FROM video_libraries WHERE name='porn'")
r = mcur.fetchone()
# 实际上这批只有1个视频，关联到 porn 库或单独创建的测试库都行
# 这里关联到 porn 库
for v in test_videos:
    mcur.execute('SELECT id FROM videos WHERE hash=?', (v['hash'],))
    if mcur.fetchone():
        total_skipped += 1
        continue
    mcur.execute('''
        INSERT INTO videos (hash, title, description, url, thumbnail, duration, file_size,
         view_count, like_count, download_count, priority, min_role,
         is_downloaded, local_path, library_id, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        v['hash'], v['title'], v['description'] if v['description'] else '',
        v['url'], v['thumbnail'], v['duration'], v['file_size'],
        v['view_count'] or 0, v['like_count'] or 0, v['download_count'] or 0,
        v['priority'] or 0, v['min_role'] if v['min_role'] is not None else 0,
        v['is_downloaded'] or 0, v['local_path'],
        main_porn_id,
        v['created_at'], v['updated_at']
    ))
    total_migrated += 1

lconn2.close()
lconn.close()

mconn.commit()

print(f'\n=== 迁移完成 ===')
print(f'新增视频: {total_migrated}')
print(f'跳过(已存在): {total_skipped}')
print()
print('主DB videos 分布:')
mcur.execute('SELECT library_id, COUNT(*) AS cnt FROM videos GROUP BY library_id ORDER BY library_id')
for row in mcur.fetchall():
    lib_name = main_libs.get(row[0], {}).get('name', '?') if row[0] else '(无库)'
    print(f'  library_id={row[0]} ({lib_name}): {row[1]} 个')

# 清理主DB中多余的无数据视频库（可选）
print()
print('主DB视频库最终状态:')
mcur.execute('SELECT id, name, db_file FROM video_libraries')
for row in mcur.fetchall():
    mcur.execute('SELECT COUNT(*) FROM videos WHERE library_id=?', (row[0],))
    vcnt = mcur.fetchone()[0]
    print(f'  ID={row[0]}  name={row[1]}  videos={vcnt}')

mconn.close()
