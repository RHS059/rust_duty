"""Reuse a committed lighting bake only when both inputs and output still match."""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CODE = ('src/static_lighting.rs', 'src/range_geometry.rs', 'src/sim.rs',
        'examples/bake_level_lighting.rs', 'src/scene_lighting.rs',
        'src/city_level.rs', 'src/draw/mod.rs')

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

def fresh(root, level):
    folder = root / 'assets/levels' / level
    try:
        record = json.loads((folder / 'lighting-cache.json').read_text())
        return (record['inputs'] == inputs(root, level)
                and record['output_sha256'] == digest(folder / 'lighting.bin'))
    except (OSError, ValueError, KeyError):
        return False

def record(root, level, expected_inputs):
    if inputs(root, level) != expected_inputs:
        raise RuntimeError('Lighting inputs changed during baking; refusing to cache')
    folder = root / 'assets/levels' / level
    (folder / 'lighting-cache.json').write_text(json.dumps({
        'schema': 'rust-duty-lighting-cache/v1', 'inputs': expected_inputs,
        'output_sha256': digest(folder / 'lighting.bin')}, indent=2) + '\n')

def main():
    for level in ('range', 'cedar_junction'):
        if fresh(ROOT, level):
            print(f'{level}: verified committed bake; no rebuild needed', flush=True)
            continue
        before = inputs(ROOT, level)
        subprocess.run(['cargo', 'run', '--locked', '--release', '--no-default-features',
                        '--example', 'bake_level_lighting', level], cwd=ROOT, check=True)
        record(ROOT, level, before)

if __name__ == '__main__':
    main()
