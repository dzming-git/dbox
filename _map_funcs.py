import ast, os
src = open('src/web/main.py', encoding='utf-8').read()
tree = ast.parse(src)

# top-level names defined in main.py
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

# also names imported at top level (these are accessible via main too)
imported = set()
for node in tree.body:
    if isinstance(node, ast.Import):
        for n in node.names:
            imported.add(n.asname or n.name.split('.')[0])
    elif isinstance(node, ast.ImportFrom):
        for n in node.names:
            imported.add(n.asname or n.name)

print('TOP_NAMES', len(top_names))
print(sorted(top_names))
print('IMPORTED', len(imported))
print(sorted(imported))
