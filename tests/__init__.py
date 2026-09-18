# -*- coding: utf-8 -*-
"""测试包：把数据目录强制隔离到临时目录。

⚠️ 为什么必须有这一层（真实事故，勿删）：

`tests/test_library_permission_deny.py` 会 `import main` 后调用 `db.drop_all()`。
而 `import main` 会把 SQLAlchemy 绑到 `backend.paths` 解析出的**真实运行库**——
paths 在【导入时】就把 DATA_DIR 定下来了。一旦同进程里先有别的测试模块导入过
main（例如 test_app_import），后续任何 `os.environ[...] = 临时目录` 都已经太晚：
db 已经指向生产库，drop_all() 会把 videos / resource_index / memberships 整表删空
（实测一次清空 1106 个视频 + 1634 条索引/归属行）。

因此隔离必须发生在「任何 src 模块被导入之前」，而包级 __init__.py 正是这个时机：
`python -m unittest tests.xxx` 会先导入 tests 包，再导入具体测试模块。

注意：直接以脚本方式运行（python tests/xxx.py）不会导入本包，那种跑法不受保护；
需要隔离的测试请走 `python -m unittest tests.xxx`。
"""
import os
import tempfile as _tempfile

if not os.environ.get('DBOX_DATA_DIR'):
    _TMP = _tempfile.mkdtemp(prefix='dbox_tests_')
    os.environ['DBOX_DATA_DIR'] = os.path.join(_TMP, 'data')
    os.environ.setdefault('DBOX_USER_CONFIG_DIR', os.path.join(_TMP, 'config'))
