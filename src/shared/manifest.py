"""脚本清单（manifest）加载：扫描 extensions/scripts/ 下所有脚本包。

本模块为中立能力，不依赖任何业务模块，仅做文件读取与数据归一化。
"""
import os
import json

try:
    import yaml  # 可选依赖；未安装时仅支持 manifest.json
    _HAVE_YAML = True
except Exception:  # pragma: no cover
    _HAVE_YAML = False


def scripts_base_dir():
    """extensions/scripts 目录（位于项目根目录下）。

    本包位于 <root>/src/shared，故从包目录向上 2 级到达项目根。
    """
    pkg_dir = os.path.dirname(os.path.abspath(__file__))        # src/shared
    project_root = os.path.dirname(os.path.dirname(pkg_dir))
    return os.path.join(project_root, 'extensions', 'scripts')


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
