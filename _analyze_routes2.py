import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src', 'web'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src', 'liblog'))
os.environ['DPLAYER_DEV_MODE'] = '1'
import web.main as m
# bare endpoints = defined directly on app (not blueprint)
bare = []
for r in m.app.url_map.iter_rules():
    if r.endpoint == 'static':
        continue
    if '.' not in r.endpoint:
        bare.append((r.rule, r.endpoint, sorted(list(r.methods))))
print('BARE_COUNT', len(bare))
for rule, ep, methods in sorted(bare):
    print(f'{ep:35s} {methods} {rule}')
