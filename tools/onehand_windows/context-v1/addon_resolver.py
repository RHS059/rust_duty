"""Resolve logical official FBX files under an explicitly inspected bundle.

No import, package search, newline normalization, patching, Blender or rendering.
The optional live-module check must be called inside the future native wrapper.
"""
from __future__ import annotations
import ast
import hashlib
import inspect
from pathlib import Path
from types import ModuleType
from candidate_context import ContextError, exact_keys, file_sha, ordinary, require, strict_json

PIN_FILE_SHA = '2716811db4b591c14d0044458c608c961aa2dfcad5958f9da6d0b4da8d67dace'


def official_pins():
    path = Path(__file__).absolute().parent / 'OFFICIAL_ADDON_PINS.json'
    require(file_sha(path) == PIN_FILE_SHA, 'official logical pin manifest differs')
    data = strict_json(path)
    exact_keys(data, ('schema', 'blender_version', 'files', 'functions'), 'addon pins')
    require(data['schema'] == 'rust-duty-logical-official-fbx-pins/v1', 'addon pin schema differs')
    return data


def _relative(value):
    require(type(value) is str and value and '\\' not in value, 'logical path must use ordinary / components')
    path = Path(value)
    require(not path.is_absolute() and all(p not in ('', '.', '..') and ':' not in p for p in value.split('/')),
            'unsafe logical addon path')
    return path


def resolve_addon(bundle_root, addon_relative):
    """Return verified file paths, not an execution or official-host assertion."""
    pins = official_pins()
    return _resolve(bundle_root, addon_relative, pins)


def _resolve(bundle_root, addon_relative, pins):
    """Mechanism shared with tiny synthetic fixtures; production pins stay fixed."""
    bundle = ordinary(bundle_root, existing=True)
    root = ordinary(bundle / _relative(addon_relative), existing=True)
    require(root.is_dir() and root.name == 'io_scene_fbx', 'inspected io_scene_fbx directory required')
    found = {}
    for name, expected in pins['files'].items():
        require(Path(name).name == name and name.endswith('.py'), 'unsafe logical addon filename')
        path = ordinary(root / name, existing=True)
        require(file_sha(path) == expected, 'official addon exact bytes differ: ' + name)
        found[name] = path
    # Exact bytes first: no CRLF repair or source rewriting can preserve this pin.
    for name, functions in pins['functions'].items():
        require(name in found, 'function file not pinned')
        raw = found[name].read_bytes()
        text = raw.decode('utf-8')
        lines = text.splitlines(keepends=True)
        tree = ast.parse(text, filename=str(found[name]))
        nodes = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                require(node.name not in nodes, 'duplicate function name')
                nodes[node.name] = node
        for function, expected in functions.items():
            require(function in nodes, 'audited function absent: ' + function)
            node = nodes[function]
            start = min([node.lineno, *[d.lineno for d in node.decorator_list]])
            source = ''.join(lines[start - 1:node.end_lineno]).encode('utf-8')
            require(hashlib.sha256(source).hexdigest() == expected, 'audited function source differs: ' + function)
    return found


def verify_loaded_modules(files, modules):
    """Reject shadow imports in a future native Blender process. Never imports one."""
    pins = official_pins()
    require(set(files) == set(pins['files']), 'complete pinned addon inventory required')
    for name, path in files.items():
        ordinary(path, existing=True)
        require(file_sha(path) == pins['files'][name], 'addon changed after resolution')
    for module_name, module in modules.items():
        require(module_name == 'io_scene_fbx' or module_name.startswith('io_scene_fbx.'), 'unexpected addon module')
        require(isinstance(module, ModuleType), 'actual module object required')
        logical = '__init__.py' if module_name == 'io_scene_fbx' else module_name.split('.')[-1] + '.py'
        require(logical in files, 'unreviewed addon submodule')
        origin = ordinary(getattr(module, '__file__', ''), existing=True)
        require(origin == files[logical], 'shadow addon module: ' + module_name)
        spec = getattr(module, '__spec__', None)
        require(spec is not None and ordinary(spec.origin, existing=True) == origin, 'module spec origin differs')
    require('io_scene_fbx' in modules and 'io_scene_fbx.import_fbx' in modules, 'official package/importer must be observed')
    importer = modules['io_scene_fbx.import_fbx']
    for name, expected in pins['functions']['import_fbx.py'].items():
        function = getattr(importer, name, None)
        require(inspect.isfunction(function) and ordinary(function.__code__.co_filename, existing=True) == files['import_fbx.py'],
                'shadow or replaced importer function: ' + name)
        require(hashlib.sha256(inspect.getsource(function).encode('utf-8')).hexdigest() == expected,
                'live audited function source differs: ' + name)
    return {'files_sha256': dict(pins['files']), 'functions_sha256': pins['functions'],
            'live_module_origins_checked': True, 'windows_execution_proved': False}
