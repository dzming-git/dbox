import ast, os, re

MAIN = 'src/web/main.py'
OUTDIR = 'src/web/backend/api'
src = open(MAIN, encoding='utf-8').read()
tree = ast.parse(src)
lines = src.splitlines()

top_names = set()
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        top_names.add(node.name)
    elif isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name):
                top_names.add(t.id)
    elif isinstance(node, ast.AnnAssign):
        if isinstance(node.target, ast.Name):
            top_names.add(node.target.id)
imported = set()
for node in tree.body:
    if isinstance(node, ast.Import):
        for n in node.names:
            imported.add(n.asname or n.name.split('.')[0])
    elif isinstance(node, ast.ImportFrom):
        for n in node.names:
            imported.add(n.asname or n.name)
main_symbols = top_names | imported

# locate route funcs
route_funcs = {}
for node in tree.body:
    if isinstance(node, ast.FunctionDef):
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                if isinstance(dec.func.value, ast.Name) and dec.func.value.id == 'app':
                    if dec.func.attr in ('route','get','post','put','delete','patch'):
                        end = len(lines) + 1
                        for n2 in tree.body:
                            if isinstance(n2, (ast.FunctionDef, ast.ClassDef)) and n2.lineno > node.lineno:
                                end = n2.lineno
                                break
                        route_funcs[node.name] = (node.lineno, end - 1)
                        break

GROUPS = {
    'video_api': ['get_videos','get_video','get_videos_by_hashes','like_video','toggle_favorite',
        'get_favorites','get_likes','get_disliked','batch_interact','toggle_dislike','delete_video',
        'increment_view_count','play_video','set_video_tags','remove_video_tag','update_video_info',
        'upload_video','batch_delete_videos','stats_overview','search_tags','scan_videos','get_tags','get_all_tags'],
    'tag_api': ['create_tag','add_tag','update_tag','update_tag_post','delete_tag'],
    'collection_api': ['list_favorite_collections','create_favorite_collection','delete_favorite_collection',
        'list_collection_videos','add_to_collection','remove_from_collection'],
    'watch_later_api': ['get_watch_later','add_watch_later','remove_watch_later','clear_watch_later'],
    'library_api': ['get_libraries','get_my_libraries','create_library','get_library','update_library',
        'delete_library','get_library_folders','test_add_folder','add_library_folder','update_folder',
        'delete_folder','set_default_folder','list_system_folders','create_system_folder','scan_library',
        'get_library_scan_status','scan_all_libraries','get_scan_all_status','get_library_permissions',
        'add_library_permission','update_library_permission','delete_library_permission','scan_folder',
        'import_videos','browse_folders','get_user_libraries','switch_user_library','get_user_groups',
        'create_user_group','delete_user_group','add_user_to_group','remove_user_from_group',
        'get_library_audit_logs','admin_list_resources','admin_update_resource','admin_delete_resource',
        'admin_trash_list','admin_trash_restore','admin_trash_purge','admin_trash_empty'],
    'thumbnail_api': ['get_thumbnail','get_thumbnail_status','delete_thumbnail','regenerate_thumbnail',
        'get_thumbnail_config','update_thumbnail_config','generate_missing_thumbnails','get_auto_generate_status','stop_auto_generate'],
    'system_api': ['system_shutdown','system_shutdown_cancel','api_get_settings','api_save_settings',
        'get_system_config','update_system_config','get_config','update_config','status','get_services',
        'control_service','get_system_logs','get_admin_users','create_admin_user','update_admin_user','delete_admin_user'],
    'post_resource_api': ['get_posts','create_post','get_post','update_post','delete_post','add_post_ref',
        'remove_post_ref','resource_index_pool','set_resource_modes','collections_api','texts_api',
        'text_item_api','available_modes','repoint_resource_index','set_resource_index_hidden'],
    'serve_api': ['serve_local_video','health'],
}

def referenced_main_symbols(funcname):
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == funcname)
    refs = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in main_symbols:
            refs.add(n.id)
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id in main_symbols:
            refs.add(dec.id)
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id in main_symbols:
            refs.add(dec.func.id)
    return refs

os.makedirs(OUTDIR, exist_ok=True)
all_grouped = [f for v in GROUPS.values() for f in v]
registrations = []
for fname, funcs in GROUPS.items():
    blocks = []
    symbols = set()
    for fn in funcs:
        s, e = route_funcs[fn]
        block = '\n'.join(lines[s-1:e])
        # replace decorator @app.X( -> @bp.X(
        block = re.sub(r'@app\.(route|get|post|put|delete|patch)\(', lambda m: f'@bp.{m.group(1)}(', block)
        block = block.replace('app.', 'current_app.')
        blocks.append(block)
        symbols |= referenced_main_symbols(fn)
    symbols.discard('app')
    flask_imports = ('from flask import Blueprint, request, jsonify, send_file, send_from_directory, '
                     'session, g, abort, Response, current_app')
    sym_list = sorted(symbols)
    main_import_block = 'from main import (\n    ' + ',\n    '.join(sym_list) + ',\n)'
    bp_tag = fname.replace('_api','')
    header = (
        f'"""Auto-split blueprint: {fname} (moved from main.py)."""\n'
        f'{flask_imports}\n'
        f'{main_import_block}\n\n'
        f"bp = Blueprint('{bp_tag}', __name__)\n\n"
    )
    content = header + '\n\n'.join(blocks) + '\n'
    open(os.path.join(OUTDIR, fname + '.py'), 'w', encoding='utf-8').write(content)
    registrations.append((fname, bp_tag))
    print(f'WROTE {fname}.py: {len(funcs)} funcs, {len(sym_list)} symbols')

# delete route func blocks from main.py (descending)
delete_ranges = sorted([route_funcs[f] for f in all_grouped], reverse=True)
new_lines = lines[:]
for s, e in delete_ranges:
    del new_lines[s-1:e]
open(MAIN, 'w', encoding='utf-8').write('\n'.join(new_lines) + '\n')
print(f'DELETED {len(delete_ranges)} blocks from main.py')

print('\n=== ADD TO main.py (blueprint registration) ===')
for fname, bp_tag in registrations:
    print(f'from backend.api.{fname} import bp as {bp_tag}_bp')
    print(f"app.register_blueprint({bp_tag}_bp)")
