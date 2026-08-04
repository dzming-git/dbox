"""反馈状态探针（内置）。

直接读取反馈独立数据库（data/databases/feedback.db），返回：
  {issue_id: {'status': <str>, 'title': <str>, 'category': <str>, 'submitter': <str>}}

不依赖 backend 包，避免与主应用运行环境耦合；监听器独立进程也可安全使用。
"""
import os
import sqlite3

_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    'data', 'databases', 'feedback.db',
)


def snapshot():
    if not os.path.exists(_DB_PATH):
        return {}
    try:
        out = {}
        conn = sqlite3.connect(_DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute('SELECT id, status, title, category, submitter FROM feedback_issues')
        for row in cur.fetchall():
            out[row['id']] = {
                'status': row['status'],
                'title': row['title'],
                'category': row['category'],
                'submitter': row['submitter'],
            }
        conn.close()
        return out
    except Exception as e:
        print(f"[probe:feedback] snapshot 失败: {e}")
        return {}
