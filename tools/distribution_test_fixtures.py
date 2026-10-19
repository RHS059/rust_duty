"""Temporary compressed-cache fixtures from verified raw delivery companions."""
import gzip
import hashlib
import json

import package_game as package


def add_test_transports(root, folder):
    """Give a copied test pack both raw and gzip forms, preserving decoded pins.

    Direct-delivery artifacts can contain only raw companions. Compression tests
    create their own transports rather than requiring production to ship them.
    Only newly created fixture gzip bytes get new transport hashes and sizes;
    every decoded payload is first checked against the original manifest.
    """
    path = root / folder / 'manifest.json'
    manifest = json.loads(path.read_text())
    for name, transport in manifest['repository_transport'].items():
        data = package.companion_bytes(root, name, manifest, folder)
        raw = root / folder / name
        if not raw.exists():
            raw.write_bytes(data)
        compressed = root / folder / transport['file']
        if not compressed.exists():
            packed = gzip.compress(data, mtime=0)
            compressed.write_bytes(packed)
            transport.update(bytes=len(packed), sha256=hashlib.sha256(packed).hexdigest())
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest
