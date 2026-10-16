"""Load unchanged pinned format helpers/assembler in an isolated import namespace.

Compile exact reviewed bytes; never rewrite functions/globals or route old
assemble() around its fixed approved-source contract. No Blender imports.
"""
import builtins
import hashlib
from pathlib import Path
import sys
from types import ModuleType
import uuid
from candidate_context import file_sha, ordinary, require

PINS = {
    'assemble_runtime': '01c4d5dd43b56607742ad2c5862c3185460dcb14b4cb5ef079301daae7f45e12',
    'vrpack': '28a23ed9a9b0fe0123405a9800473e57d04419596deae8789c66c744ad05b685',
    'vrskin': 'e6aff7f5278bb8e6dd09ca75e69b8761b1b71bd30b3feddf84f8380cd88a5e14',
    'vrview': 'eefd755f6ef0943a4d8bf443ddfec601bc1336ec90ece722d017c9c4b6d73568',
}


def load_assembler(assembler_package, tools_package):
    packages = {'assemble_runtime': ordinary(assembler_package, existing=True),
                **{name: ordinary(tools_package, existing=True) for name in ('vrpack', 'vrskin', 'vrview')}}
    paths = {name: packages[name] / (name + '.py') for name in PINS}
    raw = {}
    for name, path in paths.items():
        require(file_sha(path) == PINS[name], 'unchanged implementation pin differs: ' + name)
        raw[name] = path.read_bytes()
        require(hashlib.sha256(raw[name]).hexdigest() == PINS[name], 'implementation changed during read')
    # A shadow sys.modules['vrview'] or ambient VRVIEW_TOOLS_PATH cannot win.
    loaded = {}
    def private_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in PINS:
            require(level == 0 and name in loaded, 'unexpected dependency order or relative import')
            return loaded[name]
        return builtins.__import__(name, globals, locals, fromlist, level)
    token = uuid.uuid4().hex
    old_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        for name in ('vrpack', 'vrskin', 'vrview', 'assemble_runtime'):
            private_name = '_onehand_pinned_' + token + '_' + name
            module = ModuleType(private_name)
            module.__file__ = str(paths[name])
            module.__builtins__ = {**vars(builtins), '__import__': private_import}
            # dataclasses inspect their defining module while a class is built.
            sys.modules[private_name] = module
            try:
                exec(compile(raw[name], str(paths[name]), 'exec', dont_inherit=True), module.__dict__)
            finally:
                del sys.modules[private_name]
            loaded[name] = module
    finally:
        sys.dont_write_bytecode = old_bytecode
    for name, path in paths.items():
        require(file_sha(path) == PINS[name], 'implementation changed during import')
    return loaded['assemble_runtime']
