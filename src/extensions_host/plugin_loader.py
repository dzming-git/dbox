"""插件加载与热重载（手动触发）。

承载插件 Blueprint 的「首次加载」与「重新加载」逻辑，供 app.py（启动时）
与 routes.py（/api/admin/scripts/reload 接口）共用，避免循环导入。

核心能力：
- load_all_plugins(app)        ：启动时扫描并注册全部插件 Blueprint。
- reload_plugin(app, key)      ：注销某插件的旧 Blueprint + 重新 import 模块 + 重新注册。
                                用于文件改动后「手动重载」，无需重启进程。
- reload_all_plugins(app)      ：逐个 reload 全部有 backend 的插件。

为何需要手动 reload：extensions_host 关闭了 werkzeug reloader（见 app.py 注释），
插件代码只在进程启动时加载一次。改完插件 .py / manifest / ui 后，必须主动
重载才能生效。本模块让 /api/admin/scripts/reload 真正重新注册 Blueprint，
而非仅刷新 manifest 字典。
"""
import os
import re
import sys
import logging

from flask import Flask

from manifest import load_all, scripts_base_dir
from plugin_host import build_host


def import_plugin_module(key, folder_dir, mod_path):
    """按文件夹路径导入插件模块（支持连字符等非合法 Python 标识符的文件夹名）。

    把插件文件夹作为一个包（包名 ext_<sanitized_key>）挂到 sys.modules，
    从而插件内部的相对导入（如 `from .engine import ...`）仍可正常工作；
    彻底解除对 `importlib.import_module('extensions.<id>...')` 的依赖。
    """
    safe = re.sub(r'[^0-9A-Za-z_]', '_', key)
    pkg_name = 'ext_%s' % safe
    if pkg_name not in sys.modules:
        init_file = os.path.join(folder_dir, '__init__.py')
        if os.path.isfile(init_file):
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                pkg_name, init_file, submodule_search_locations=[folder_dir])
            pkg = importlib.util.module_from_spec(spec)
            sys.modules[pkg_name] = pkg
            if spec.loader is not None:
                spec.loader.exec_module(pkg)
        else:
            import importlib.machinery
            # 命名空间包：loader 为 None，仅需声明搜索路径即可解析子模块。
            spec = importlib.machinery.ModuleSpec(pkg_name, None, is_package=True)
            spec.submodule_search_locations = [folder_dir]
            pkg = importlib.util.module_from_spec(spec)
            sys.modules[pkg_name] = pkg
    return __import__(pkg_name + '.' + mod_path, fromlist=[''])


def unregister_blueprint(app: Flask, bp_name: str):
    """注销已注册的 Blueprint（Flask 无官方 unregister，手工清理 url_map + view_functions）。

    关键：必须同时清理 app.view_functions 中该蓝图的所有端点，否则重新注册同名
    端点时会报 “View function mapping is overwriting an existing endpoint function”。
    """
    if bp_name in app.blueprints:
        del app.blueprints[bp_name]
    for rule in list(app.url_map.iter_rules()):
        if rule.endpoint == bp_name or rule.endpoint.startswith(bp_name + '.'):
            try:
                app.url_map._rules.remove(rule)
            except ValueError:
                pass
            app.url_map._rules_by_endpoint.pop(rule.endpoint, None)
            app.view_functions.pop(rule.endpoint, None)
    # 彻底重建内部索引，避免残留 endpoint 指向已删除的 rule
    # （werkzeug 的 get_default_redirect 会查 _rules_by_endpoint[endpoint]，
    #  若只 pop 了一半残留引用，请求该路径时会 KeyError 导致 500）
    app.url_map._rules_by_endpoint = {}
    for r in app.url_map._rules:
        app.url_map._rules_by_endpoint.setdefault(r.endpoint, []).append(r)
    app.url_map._remap = True


def _register_one(app, sc, mod, factory_attr='create_blueprint'):
    """从已 import 的模块构造并注册一个插件的 Blueprint。返回已注册的前缀列表。"""
    factory = getattr(mod, sc.get('backend', {}).get('factory', factory_attr))
    host = build_host(sc, app)
    result = factory(host)
    bps = result if isinstance(result, (list, tuple)) else [result]
    registered = []
    for bp in bps:
        if bp is None:
            continue
        # 显式传入 url_prefix（来自 manifest.backend.url_prefix 或 /api/ext/<key>），
        # 避免蓝图自身未声明 url_prefix 时注册到根路径导致前端 404。
        prefix = bp.url_prefix or host.url_prefix
        app.register_blueprint(bp, url_prefix=prefix)
        host.register_url(prefix)
        registered.append(prefix)
    return registered


def load_all_plugins(app: Flask, logger=None):
    """扫描并注册全部插件 Blueprint（启动时调用）。"""
    log = logger or logging.getLogger('plugin_loader')
    try:
        base = scripts_base_dir()
        scripts = load_all(base)
    except Exception as e:
        log.error('插件扫描失败: %s', e)
        return
    for sc in scripts.values():
        be = sc.get('backend')
        if not be:
            continue
        mod_path = be.get('module') or 'backend.server'
        try:
            mod = import_plugin_module(sc['id'], sc['_dir'], mod_path)
            prefixes = _register_one(app, sc, mod)
            log.info('插件已加载: %s (prefix=%s)', sc['id'], ','.join(prefixes))
        except Exception as e:
            log.error('插件 %s 加载失败: %s', sc.get('id'), e)


def reload_plugin(app: Flask, script_id: str, logger=None):
    """注销某插件的旧 Blueprint，重新 import 模块并注册。返回是否成功。"""
    log = logger or logging.getLogger('plugin_loader')
    try:
        base = scripts_base_dir()
        scripts = load_all(base)
    except Exception as e:
        log.error('重载前扫描失败: %s', e)
        return False
    sc = scripts.get(script_id)
    if not sc or not sc.get('backend'):
        log.warning('插件 %s 不存在或未声明 backend，跳过重载', script_id)
        return False

    # 1) 注销当前已注册、url_prefix 属于该插件的 Blueprint
    want_prefix = sc.get('backend', {}).get('url_prefix') or ('/api/ext/%s' % script_id)
    for bp_name in list(app.blueprints.keys()):
        bp = app.blueprints[bp_name]
        bp_prefix = getattr(bp, 'url_prefix', None) or ''
        if bp_prefix == want_prefix or bp_prefix.startswith(want_prefix + '/'):
            unregister_blueprint(app, bp_name)

    # 2) 从 sys.modules 剔除旧插件包，强制下一次 import 拿到新代码
    safe = re.sub(r'[^0-9A-Za-z_]', '_', script_id)
    sys.modules.pop('ext_%s' % safe, None)

    # 3) 重新 import + 注册
    mod_path = sc['backend'].get('module') or 'backend.server'
    try:
        mod = import_plugin_module(script_id, sc['_dir'], mod_path)
        prefixes = _register_one(app, sc, mod)
        log.info('插件已重载: %s (prefix=%s)', script_id, ','.join(prefixes))
        return True
    except Exception as e:
        log.error('插件 %s 重载失败: %s', script_id, e)
        return False


def reload_all_plugins(app: Flask, logger=None):
    """逐个重载全部有 backend 的插件。返回成功数量。"""
    log = logger or logging.getLogger('plugin_loader')
    try:
        base = scripts_base_dir()
        scripts = load_all(base)
    except Exception as e:
        log.error('重载扫描失败: %s', e)
        return 0
    ok = 0
    for sc in scripts.values():
        if not sc.get('backend'):
            continue
        if reload_plugin(app, sc['id'], logger=log):
            ok += 1
    return ok
