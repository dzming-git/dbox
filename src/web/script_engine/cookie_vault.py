# -*- coding: utf-8 -*-
"""兼容层：cookie 保险库已迁至 ``src/web/common/cookie_vault``。

为保持 ``script_engine.manager`` 等历史 import 不变，这里直接复用通用模块。
新增代码请直接 ``from common.cookie_vault import CredentialVault``。
"""
from common.cookie_vault import (  # noqa: F401
    CredentialVault,
    CookieVault,
    data_dir_for,
)
