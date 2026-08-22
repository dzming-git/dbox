"""脚本清单（manifest）加载：扫描 extensions/ 下所有脚本包。

目录约定（纯插件布局）：
    extensions/
        <plugin_a>/          # 每个子目录即一个自包含插件
            manifest.json
            backend/  ui/  workflows/  ...（插件私有，框架不关心内部结构）
        <plugin_b>/
        ...

框架只扫描 extensions/ 一级子目录，读取其 manifest.*；不关心插件内部实现，
也不在任何框架源码中硬编码插件 id——插件是否启用、如何挂载 UI、是否暴露独立
路由、是否轮询忙碌态，全部由 manifest 字段声明（详见 docs/development/plugin_architecture.md）。
"""
import os
import json

try:
    import yaml  # 可选依赖；未安装时仅支持 manifest.json
    _HAVE_YAML = True
except Exception:  # pragma: no cover
    _HAVE_YAML = False


def scripts_base_dir():
    """extensions/ 目录（位于项目根目录下），所有插件平铺于此。

    本包位于 <root>/src/extensions_host，故从包目录向上 2 级到达项目根。
    """
    pkg_dir = os.path.dirname(os.path.abspath(__file__))        # src/extensions_host
    project_root = os.path.dirname(os.path.dirname(pkg_dir))      # 向上两级 -> 项目根 (dbox)
    return os.path.join(project_root, 'extensions')


def _load_one(ms_dir):
    candidates = ['manifest.json']
    if _HAVE_YAML:
        candidates += ['manifest.yaml', 'manifest.yml']
    for name in candidates:
        p = os.path.join(ms_dir, name)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f) if name.endswith('.json') else yaml.safe_load(f)
            if not isinstance(data, dict):
                return {'_dir': ms_dir, 'id': os.path.basename(ms_dir),
                        '_error': 'manifest 根节点必须是对象'}
            data['_dir'] = ms_dir
            data.setdefault('id', os.path.basename(ms_dir))
            data.setdefault('enabled', False)
            data.setdefault('interface', 1)
            data.setdefault('runtime', 'executable')
            data.setdefault('timeout', 0)
            # 透传 settings 段（插件独立设置页 schema）；框架按 schema 动态渲染表单。
            # 每项: {key, label, type, default, options?, required?, description?, group?}
            # type ∈ switch | text | number | radio | checkbox | select
            data.setdefault('settings', [])
            return data
        except Exception as e:
            return {'_dir': ms_dir, 'id': os.path.basename(ms_dir), '_error': str(e)}
    return None


def load_all(base=None):
    base = base or scripts_base_dir()
    scripts = {}
    if not os.path.isdir(base):
        return scripts
    for entry in sorted(os.listdir(base)):
        ms_dir = os.path.join(base, entry)
        if not os.path.isdir(ms_dir):
            continue
        m = _load_one(ms_dir)
        if m and 'id' in m:
            scripts[m['id']] = m
    return scripts
