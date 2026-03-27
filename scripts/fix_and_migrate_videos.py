"""
修复并完成视频到 resource.db 的迁移

问题分析：
- dplayer.db: library_id=1 (porn) 有 949 个视频，library_id=2 (喜鹊谋杀案) 有 6 个视频
- resource.db: library_id=2 (porn) 有 947 个，library_id=3 (喜鹊谋杀案) 有 6 个
- 缺失 2 个视频，但 video 955 实际应该是"喜鹊谋杀案"库

正确的迁移映射：
- video 913 (porn) -> resource_library_id=2 (porn)
- video 955 (实际是喜鹊谋杀案) -> resource_library_id=3 (喜鹊谋杀案)
"""
import sqlite3
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOURCE_DB = os.path.join(BASE_DIR, 'data', 'databases', 'resource.db')
DPLAYER_DB = os.path.join(BASE_DIR, 'data', 'databases', 'dplayer.db')

print(f"RESOURCE_DB: {RESOURCE_DB}")
print(f"DPLAYER_DB: {DPLAYER_DB}")

# 连接数据库
dconn = sqlite3.connect(DPLAYER_DB)
dc = dconn.cursor()

rconn = sqlite3.connect(RESOURCE_DB)
rc = rconn.cursor()

# 查看当前状态
print("\n=== 迁移前状态 ===")
dc.execute("SELECT id, name FROM video_libraries")
print("dplayer video_libraries:")
for row in dc.fetchall():
    print(f"  id={row[0]}, name={row[1]}")

rc.execute("SELECT id, name FROM resource_libraries")
print("\nresource_libraries:")
for row in rc.fetchall():
    print(f"  id={row[0]}, name={row[1]}")

# 获取缺失的视频 (hash, title, local_path, library_id, file_size)
dc.execute("SELECT hash, title, local_path, library_id, file_size FROM videos WHERE hash IN (?, ?)",
           ('a375d3cfcd5bd93f131974f4d7b81cb34172699c85216f143efd1520cbdec5df',
            'f2b402cbd59a79b339362d40f96ce2c7a8548013274ad4e0179914369d98ba42'))
missing_videos = dc.fetchall()
print(f"\n缺失的视频: {len(missing_videos)}")
for v in missing_videos:
    print(f"  hash={v[0][:20]}... library_id={v[3]} title={v[1]}")

# 根据路径确定正确的 library 映射
def get_resource_library_id(video):
    local_path = video[2] or ''
    if 'qinglanhua' in local_path.lower() or local_path.startswith('M:'):
        return 2  # porn
    elif '喜鹊谋杀案' in local_path or 'Magpie' in local_path:
        return 3  # 喜鹊谋杀案
    return 2  # 默认

# 插入缺失的视频
print("\n=== 执行迁移 ===")
for v in missing_videos:
    res_lib_id = get_resource_library_id(v)
    video_hash = v[0]
    video_title = v[1]
    local_path = v[2]
    file_size = v[4]

    print(f"迁移: hash={video_hash[:20]}... title={video_title} -> library_id={res_lib_id}")

    # 检查是否已存在
    rc.execute("SELECT 1 FROM resource_items WHERE hash=?", (video_hash,))
    if rc.fetchone():
        print(f"  已存在，跳过")
        continue

    # 获取文件信息
    file_name = os.path.basename(local_path) if local_path else video_title
    file_ext = os.path.splitext(file_name)[1].lower() if file_name else '.mp4'

    # 插入
    now = datetime.now().isoformat()
    rc.execute("""
        INSERT INTO resource_items
        (hash, library_id, file_path, file_name, file_ext, file_size, mime_type,
         is_deleted, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
    """, (
        video_hash,
        res_lib_id,
        local_path,
        file_name,
        file_ext,
        file_size,
        'video/mp4' if file_ext == '.mp4' else 'video/x-msvideo',
        now,
        now
    ))
    print(f"  插入成功")

rconn.commit()

# 验证结果
print("\n=== 迁移后状态 ===")
rc.execute("SELECT library_id, COUNT(*) FROM resource_items GROUP BY library_id")
print("resource_items by library:")
for row in rc.fetchall():
    print(f"  library_id={row[0]}: {row[1]} 个")

# 清理
dconn.close()
rconn.close()

print("\n=== 迁移完成 ===")