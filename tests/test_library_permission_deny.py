# -*- coding: utf-8 -*-
"""资源库权限「显式拒绝」回归测试。

复现用户反馈的严重缺陷：给某用户关闭某资源库（设为 none）后，该用户首页仍能看到
该库的资源。

根因：权限模型只支持「授予」（直接 + 用户组 + 通用授权三者并集），没有「拒绝」
语义。当某库通过 user_id=NULL 的通用授权对所有人可见时，仅删除该用户的「直接
授权」无法撤销其可见性——因为可见性来自通用授权而非直接授权。

修复：将 level='none' 落库为一条 access_level='none' 的直接授权，并在权限计算时
让「显式拒绝」覆盖通用/用户组授权。
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

# 必须在导入任何 src/web 模块前，把数据区指到一个临时目录，避免触碰真实运行库
_TMP = tempfile.mkdtemp(prefix='dbox_perm_test_')
os.environ['DBOX_DATA_ROOT'] = _TMP
os.environ['DBOX_USER_CONFIG_DIR'] = os.path.join(_TMP, 'config')

SRC_WEB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src', 'web'))
if SRC_WEB not in sys.path:
    sys.path.insert(0, SRC_WEB)

import main  # noqa: E402  (触发建表到临时库)
from core.models import db, User, UserRole, ResourceLibrary, LibraryPermission  # noqa: E402
from backend.access import get_allowed_library_ids, _collect_user_denials  # noqa: E402


class TestLibraryPermissionDeny(unittest.TestCase):
    def setUp(self):
        self.ctx = main.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()

        u = User(username='lyx', password_hash='x', role=UserRole.USER)
        db.session.add(u)
        db.session.flush()

        p = ResourceLibrary(name='p', is_active=True, db_path='p.db', db_file='p.db')
        gp = ResourceLibrary(name='gp', is_active=True, db_path='gp.db', db_file='gp.db')
        db.session.add_all([p, gp])
        db.session.flush()

        # 关键复现场景：库 p 通过 user_id=NULL 的「通用授权」对所有人可见
        db.session.add(LibraryPermission(library_id=p.id, user_id=None,
                                        access_level='full'))
        # 库 gp 通过「直接授权」可见
        db.session.add(LibraryPermission(user_id=u.id, library_id=gp.id,
                                         access_level='read'))
        db.session.commit()

        self.uid = u.id
        self.pid = p.id
        self.gpid = gp.id

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    def _as(self, uid):
        # 直接替换 access 模块内的 resolve_identity，模拟该登录用户
        return patch('backend.access.resolve_identity',
                     return_value=(uid, UserRole.USER))

    def test_universal_grant_visible_until_denied(self):
        # 修复前行为：通用授权使库 p 对 lyx 可见
        with self._as(self.uid):
            allowed = get_allowed_library_ids()
        self.assertIn(self.pid, allowed, '库p经通用授权应对用户可见（复现原行为）')
        self.assertIn(self.gpid, allowed)

        # 模拟管理员把库 p 设为 none：写入 access_level='none' 的拒绝行
        db.session.add(LibraryPermission(user_id=self.uid, library_id=self.pid,
                                        access_level='none'))
        db.session.flush()

        # 修复后行为：显式拒绝必须覆盖通用授权
        with self._as(self.uid):
            allowed2 = get_allowed_library_ids()
        self.assertNotIn(self.pid, allowed2,
                         '显式拒绝后应覆盖通用授权，库p不再可见')
        self.assertIn(self.gpid, allowed2, '未被拒绝的库gp仍应可见')

    def test_collect_denials(self):
        db.session.add(LibraryPermission(user_id=self.uid, library_id=self.pid,
                                        access_level='none'))
        db.session.flush()
        self.assertIn(self.pid, _collect_user_denials(self.uid))


if __name__ == '__main__':
    unittest.main()
