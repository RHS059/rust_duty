"""Resolve one frozen official Windows FBX profile without changing installed files.

Whole files and raw AST slices retain CRLF. inspect.getsource has a separate
loaded-source domain. Its hash is never accepted as a raw-file/slice alternative.
"""
from __future__ import annotations
import ast
import hashlib
import inspect
from pathlib import Path
from types import CodeType, ModuleType
from candidate_context import ContextError, exact_keys, file_sha, ordinary, require, sha, strict_json

PIN_FILE_SHA = '710ac9f97ba798dda2b4091232215bf0d973a03a07703448d184b420f5addb4f'
PROFILE_ID = 'blender-4.3.2-windows-x64-official-crlf-v1'
SCHEMA = 'rust-duty-windows-official-fbx-pins/v2'
DISTRIBUTION = {'filename': 'blender-4.3.2-windows-x64.zip', 'bytes': 405138423,
                'sha256': '933a62a770c941e316535f893629ff106ddd2aa5a956f0081ec557439073d4f6'}
HASH_DOMAINS = {
    'files': 'sha256(raw-file-bytes)',
    'raw_functions_sha256': 'sha256(utf8(raw-AST-function-slice-with-original-line-endings))',
    'loaded_functions_sha256': 'sha256(utf8(inspect.getsource(function)))',
}


def _validate_pins(data):
    exact_keys(data, ('schema', 'profile_id', 'blender_version', 'distribution', 'observation',
                     'hash_domains', 'files', 'file_metadata', 'raw_functions_sha256',
                     'loaded_functions_sha256'), 'addon pins')
    require(data['schema'] == SCHEMA, 'addon pin schema differs')
    require(data['profile_id'] == PROFILE_ID and data['blender_version'] == [4, 3, 2] and
            data['distribution'] == DISTRIBUTION, 'exact Windows distribution profile differs')
    require(data['hash_domains'] == HASH_DOMAINS, 'function hash domains differ')
    require(type(data['files']) is dict and data['files'], 'raw file inventory required')
    require(type(data['file_metadata']) is dict and set(data['file_metadata']) == set(data['files']),
            'complete raw file metadata required')
    for name, expected in data['files'].items():
        require(type(name) is str and Path(name).name == name and name.endswith('.py'),
                'unsafe logical addon filename')
        sha(expected)
        metadata = data['file_metadata'][name]
        exact_keys(metadata, ('bytes', 'crlf_count', 'bare_lf_count', 'bare_cr_count'), 'raw file metadata')
        require(all(type(n) is int for n in metadata.values()) and
                0 < metadata['bytes'] <= 1024 * 1024 and 0 < metadata['crlf_count'] <= metadata['bytes'] // 2 and
                metadata['bare_lf_count'] == metadata['bare_cr_count'] == 0, 'exact CRLF metadata differs')
    raw, loaded = data['raw_functions_sha256'], data['loaded_functions_sha256']
    require(type(raw) is dict and type(loaded) is dict and raw and set(raw) == set(loaded),
            'complete distinct function domains required')
    for name, functions in raw.items():
        require(name in data['files'] and type(functions) is dict and functions and
                type(loaded[name]) is dict and set(functions) == set(loaded[name]), 'function inventory differs')
        for function, expected in functions.items():
            require(type(function) is str and function.isidentifier(), 'invalid audited function name')
            sha(expected); sha(loaded[name][function])
    return data


def official_pins():
    path = Path(__file__).absolute().parent / 'OFFICIAL_ADDON_PINS.json'
    require(file_sha(path) == PIN_FILE_SHA, 'official Windows pin manifest differs')
    data = strict_json(path)
    require(file_sha(path) == PIN_FILE_SHA, 'official Windows pin manifest changed during read')
    return _validate_pins(data)


def _relative(value):
    require(type(value) is str and value and '\\' not in value, 'logical path must use ordinary / components')
    path = Path(value)
    require(not path.is_absolute() and all(p not in ('', '.', '..') and ':' not in p for p in value.split('/')),
            'unsafe logical addon path')
    return path


def _raw_metadata(raw):
    crlf = raw.count(b'\r\n')
    return {'bytes': len(raw), 'crlf_count': crlf,
            'bare_lf_count': raw.count(b'\n') - crlf, 'bare_cr_count': raw.count(b'\r') - crlf}


def _verified_raw(path, name, pins):
    path = ordinary(path, existing=True)
    require(file_sha(path) == pins['files'][name], 'official addon exact bytes differ: ' + name)
    with path.open('rb') as stream:
        raw = stream.read(pins['file_metadata'][name]['bytes'] + 1)
    require(hashlib.sha256(raw).hexdigest() == pins['files'][name], 'addon changed during raw read: ' + name)
    require(_raw_metadata(raw) == pins['file_metadata'][name], 'raw addon byte/newline metadata differs: ' + name)
    return raw


def resolve_addon(bundle_root, addon_relative):
    """Return exact-profile paths; this alone proves no host execution."""
    return _resolve(bundle_root, addon_relative, official_pins())


def _resolve(bundle_root, addon_relative, pins):
    """Private fixture seam; the production entry always loads the fixed manifest."""
    _validate_pins(pins)
    bundle = ordinary(bundle_root, existing=True)
    root = ordinary(bundle / _relative(addon_relative), existing=True)
    require(root.is_dir() and root.name == 'io_scene_fbx', 'inspected io_scene_fbx directory required')
    found, payloads = {}, {}
    for name in pins['files']:
        path = ordinary(root / name, existing=True)
        payloads[name] = _verified_raw(path, name, pins); found[name] = path
    # All whole raw files first, then exact raw AST slices. Never normalize.
    for name, functions in pins['raw_functions_sha256'].items():
        text = payloads[name].decode('utf-8'); lines = text.splitlines(keepends=True)
        nodes = {}
        for node in ast.parse(text, filename=str(found[name])).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                require(node.name not in nodes, 'duplicate function name'); nodes[node.name] = node
        for function, expected in functions.items():
            require(function in nodes, 'audited function absent: ' + function)
            node = nodes[function]; start = min([node.lineno, *[d.lineno for d in node.decorator_list]])
            source = ''.join(lines[start - 1:node.end_lineno]).encode('utf-8')
            require(hashlib.sha256(source).hexdigest() == expected, 'raw audited function source differs: ' + function)
    return found


def verify_loaded_modules(files, modules):
    """Recheck raw files, reject shadow origins, then verify inspect's own domain.

    Python's source loader supplies universal newlines to inspect.getsource.
    This function never rewrites installed bytes or relaxes the raw-file domain.
    """
    pins = official_pins()
    require(set(files) == set(pins['files']), 'complete pinned addon inventory required')
    raw_files = {name: _verified_raw(path, name, pins) for name, path in files.items()}
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
    # Compile exact verified source in THIS interpreter; never execute the module.
    # No persisted bytecode pins or cross-Python-version equality assumptions.
    compiled = compile(raw_files['import_fbx.py'], str(files['import_fbx.py']), 'exec',
                       dont_inherit=True, optimize=0)
    expected_codes = {}
    for code in compiled.co_consts:
        if isinstance(code, CodeType) and code.co_name in pins['loaded_functions_sha256']['import_fbx.py']:
            require(code.co_name not in expected_codes, 'duplicate compiled audited function')
            expected_codes[code.co_name] = code
    require(set(expected_codes) == set(pins['loaded_functions_sha256']['import_fbx.py']),
            'complete compiled audited function inventory required')
    for name, expected in pins['loaded_functions_sha256']['import_fbx.py'].items():
        function = getattr(importer, name, None)
        require(inspect.isfunction(function) and ordinary(function.__code__.co_filename, existing=True) == files['import_fbx.py'],
                'shadow or replaced importer function: ' + name)
        require(function.__code__ == expected_codes[name], 'live audited function code differs: ' + name)
        require(hashlib.sha256(inspect.getsource(function).encode('utf-8')).hexdigest() == expected,
                'live audited function source differs: ' + name)
    return {'profile_id': pins['profile_id'], 'files_sha256': dict(pins['files']),
            'raw_functions_sha256': pins['raw_functions_sha256'],
            'functions_sha256': pins['loaded_functions_sha256'], 'hash_domains': pins['hash_domains'],
            'live_module_origins_checked': True, 'live_function_code_checked': True, 'windows_execution_proved': False}
