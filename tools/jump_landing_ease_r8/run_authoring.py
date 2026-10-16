"""Validate local inputs, then execute the byte-preserved original author script.

Use with Blender 4.3.2, factory startup and autoexec disabled. No inputs are
downloaded. Output must be a new directory; the private source is never replaced.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def sha(path):
    with Path(path).open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256')
    return digest.hexdigest()


def validate_inputs(inputs, output, provenance):
    if not __debug__:
        raise RuntimeError('Authoring requires Python assertions; do not use -O')
    inputs, output = Path(inputs).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError('Output must be a new directory')
    for row in provenance['inputs']:
        path = inputs / row['filename']
        if not path.is_file() or sha(path) != row['sha256']:
            raise ValueError('Missing or changed pinned input: ' + row['filename'])
    script = HERE / provenance['original_authoring_script']['path']
    if sha(script) != provenance['original_authoring_script']['sha256']:
        raise ValueError('Original authoring script hash mismatch')
    return inputs, output, script


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    provenance = json.loads((HERE / 'provenance.json').read_text())
    inputs, output, script = validate_inputs(args.inputs, args.output, provenance)
    import bpy
    if bpy.app.version_string != '4.3.2' or not bpy.app.background:
        raise RuntimeError('Use a quiet background Blender 4.3.2 session')
    # Claim the output exclusively after validation; never race another run's
    # report writes in the unchanged authoring script.
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.open_mainfile(filepath=str(inputs / 'halcyon_jump.blend'), load_ui=False, use_scripts=False)
    sys.argv = [str(script), '--', '--inputs', str(inputs), '--output', str(output)]
    namespace = {'__name__': '__main__', '__file__': str(script)}
    exec(compile(script.read_text(), str(script), 'exec'), namespace)


if __name__ == '__main__':
    main(sys.argv[sys.argv.index('--') + 1:])
