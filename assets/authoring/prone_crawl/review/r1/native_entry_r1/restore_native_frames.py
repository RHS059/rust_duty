#!/usr/bin/env python3
"""Restore and validate the original native capture PNG archive from exact parts."""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import zipfile

def main():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root/'native_evidence.manifest.json').read_text())
    chunks = []
    for row in manifest['parts']:
        path = PurePosixPath(row['path'])
        assert not path.is_absolute() and '..' not in path.parts
        data = (root/path).read_bytes()
        assert len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
        chunks.append(data)
    archive = b''.join(chunks)
    assert len(archive) == manifest['archive_bytes']
    assert hashlib.sha256(archive).hexdigest() == manifest['archive_sha256']
    with zipfile.ZipFile(io.BytesIO(archive)) as zipper:
        assert set(zipper.namelist()) == {row['archive_member'] for row in manifest['members']}
        assert zipper.testzip() is None
        for row in manifest['members']:
            path = PurePosixPath(row['archive_member'])
            assert not path.is_absolute() and '..' not in path.parts
            data = zipper.read(row['archive_member'])
            assert len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256']
    target = root/manifest['archive']
    assert target.parent == root
    if target.exists():
        assert hashlib.sha256(target.read_bytes()).hexdigest() == manifest['archive_sha256']
    else:
        with target.open('xb') as stream: stream.write(archive)
    print('Verified 69 original PNGs:', target, manifest['archive_sha256'])

if __name__ == '__main__':
    main()
