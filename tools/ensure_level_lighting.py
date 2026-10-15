"""Reuse a committed lighting bake only when both inputs and output still match.

Inputs are the level data plus explicit bake/optimizer versions, not source-file
hashes: refactors and lint fixes never trigger a rebake. Bump BAKE_VERSION (or
OPTIMIZER_VERSION) when the lighting algorithm's output actually changes.
Game builds run with --check and never bake; level-lighting.yml bakes on main.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BAKE_VERSION = 1
OPTIMIZER_VERSION = 1

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def inputs(root, level):
    # The range is built from src/range_geometry.rs: bump BAKE_VERSION when its layout changes.
    paths = []
    if level == 'cedar_junction':
        paths += ['assets/levels/cedar_junction/' + name for name in ('level.json', 'meshes.bin')]
    return {'bake_version': BAKE_VERSION, **{name: digest(root / name) for name in paths}}

def optimization(root):
    return {'optimizer_version': OPTIMIZER_VERSION}

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

def check(root):
    """Build-time gate: never bakes. Fails only if a committed bake is missing or damaged."""
    for level in ('range', 'cedar_junction'):
        folder = root / 'assets/levels' / level
        try:
            record = json.loads((folder / 'lighting-cache.json').read_text())
            intact = record['output_sha256'] == digest(folder / 'lighting.bin')
        except (OSError, ValueError, KeyError):
            intact = False
        if not intact:
            raise SystemExit(f'{level}: committed lighting.bin is missing or does not match lighting-cache.json')
        state = 'current' if fresh(root, level) else 'STALE (level-lighting.yml rebakes on main)'
        print(f'{level}: using committed bake, {state}', flush=True)

def main():
    if '--check' in sys.argv[1:]:
        check(ROOT)
        return
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
