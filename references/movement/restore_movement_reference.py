#!/usr/bin/env python3
"""Reassemble the exact user-supplied movement-reference MP4 from GitHub parts.

Uses the Python standard library. No network access, credentials, or conversion.
Every part and the complete output must match their recorded SHA-256 hashes.
An existing output is verified and left untouched; differing bytes are rejected.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def restore(manifest_path, output=None):
    manifest_path = manifest_path.resolve()
    base = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest['schema'] != 'rust-duty-reference-binary-parts/v1':
        raise ValueError('Unsupported manifest schema')
    output = Path(output).resolve() if output else base / manifest['output']
    if Path(manifest['output']).name != manifest['output']:
        raise ValueError('Manifest output must be a filename')
    expected_size, expected_hash = manifest['bytes'], manifest['sha256']
    if output.exists():
        if output.is_file() and output.stat().st_size == expected_size and digest(output) == expected_hash:
            print(f'Already verified: {output}\nSHA256 {expected_hash}')
            return output
        raise FileExistsError(f'Refusing to overwrite a different existing output: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    total, full_hash = 0, hashlib.sha256()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=output.name + '.', suffix='.partial',
                                         dir=output.parent, delete=False) as destination:
            temporary = Path(destination.name)
            for row in manifest['parts']:
                source = (base / row['path']).resolve()
                if not source.is_relative_to(base):
                    raise ValueError('Part path escapes reference directory')
                size, part_hash = 0, hashlib.sha256()
                with source.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        destination.write(chunk)
                        part_hash.update(chunk)
                        full_hash.update(chunk)
                        size += len(chunk)
                if size != row['bytes'] or part_hash.hexdigest() != row['sha256']:
                    raise ValueError(f'Part size/hash mismatch: {row["path"]}')
                total += size
            destination.flush()
            os.fsync(destination.fileno())
        if total != expected_size or full_hash.hexdigest() != expected_hash:
            raise ValueError('Full reference size/hash mismatch')
        # Atomically create the final filename without ever replacing an existing file.
        os.link(temporary, output)
        print(f'Restored {total} bytes: {output}\nSHA256 {expected_hash}')
        return output
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path,
                        default=here / 'modern_warfare_2022_movement_reference.manifest.json')
    parser.add_argument('--output', type=Path, help='Optional new output path')
    args = parser.parse_args()
    restore(args.manifest, args.output)


if __name__ == '__main__':
    main()
