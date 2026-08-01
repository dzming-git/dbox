import os, sys, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src', 'web'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src', 'liblog'))
os.environ['DPLAYER_DEV_MODE'] = '1'
import web.main as m
from collections import defaultdict
groups = defaultdict(list)
for r in m.app.url_map.iter_rules():
    if r.endpoint == 'static':
        continue
    path = r.rule
    # take first meaningful segment
    seg = path.split('/')[1] if len(path.split('/')) > 1 else '(root)'
    groups[seg].append((path, r.endpoint))
for seg in sorted(groups):
    print(f'\n=== /{seg}  ({len(groups[seg])}) ===')
    for path, ep in groups[seg]:
        print(f'  {path}  ->  {ep}')
