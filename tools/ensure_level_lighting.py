"""Reuse a committed lighting bake only when both inputs and output still match."""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CODE = ('src/static_lighting.rs', 'src/range_geometry.rs', 'src/sim.rs',
        'examples/bake_level_lighting.rs', 'src/scene_lighting.rs',
        'src/city_level.rs', 'src/draw/mod.rs')
OPTIMIZER = ('src/lighting_mesh.rs', 'examples/compact_level_lighting.rs')

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def inputs(root, level):
    paths = list(CODE)
    if level == 'cedar_junction':
        paths += ['assets/levels/cedar_junction/' + name for name in ('level.json', 'meshes.bin')]
    return {name: digest(root / name) for name in paths}

def optimization(root):
    return {name: digest(root / name) for name in OPTIMIZER}

def base_fresh(root, level):
    folder = root / 'assets/levels' / level
    try:
        record = json.loads((folder / 'lighting-cache.json').read_text())
        return (record['inputs'] == inputs(root, level)
                and record['output_sha256'] == digest(folder / 'lighting.bin'))
    except (OSError, ValueError, KeyError):
        return False

def fresh(root, level):
    try:
        cached = json.loads((root / 'assets/levels' / level / 'lighting-cache.json').read_text())
        return base_fresh(root, level) and cached.get('optimization') == optimization(root)
    except (OSError, ValueError, KeyError):
        return False

def record(root, level, expected_inputs):
    if inputs(root, level) != expected_inputs:
        raise RuntimeError('Lighting inputs changed during baking; refusing to cache')
    folder = root / 'assets/levels' / level
    (folder / 'lighting-cache.json').write_text(json.dumps({
        'schema': 'rust-duty-lighting-cache/v1', 'inputs': expected_inputs,
        'optimization': optimization(root),
        'output_sha256': digest(folder / 'lighting.bin')}, indent=2) + '\n')

def main():
    for level in ('range', 'cedar_junction'):
        if fresh(ROOT, level):
            print(f'{level}: verified committed bake; no rebuild needed', flush=True)
            continue
        before = inputs(ROOT, level)
        optimizer_before = optimization(ROOT)
        cache_path = ROOT / "assets/levels" / level / "lighting-cache.json"
        try:
            prior_optimization = json.loads(cache_path.read_text()).get("optimization")
        except (OSError, ValueError):
            prior_optimization = None
        if not base_fresh(ROOT, level) or prior_optimization is not None:
            subprocess.run(['cargo', 'run', '--locked', '--release', '--no-default-features',
                            '--example', 'bake_level_lighting', level], cwd=ROOT, check=True)
        subprocess.run(['cargo', 'run', '--locked', '--release', '--no-default-features',
                        '--example', 'compact_level_lighting', level], cwd=ROOT, check=True)
        if optimization(ROOT) != optimizer_before:
            raise RuntimeError('Lighting optimizer changed during processing')
        record(ROOT, level, before)

if __name__ == '__main__':
    main()
