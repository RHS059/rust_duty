#!/usr/bin/env python3
"""Compare exact city triangle content independently of record/triangle order.

Usage:
    python tools/verify_city_geometry.py old/meshes.bin new/meshes.bin
    python tools/verify_city_geometry.py old_city new_city --report parity.json

Each ordered triangle is hashed over its 120 original bytes: three vertices,
with position, normal and RGBA as ten f32 values each. Sorted BLAKE2b-128 digest
multisets preserve multiplicity and winding; no float tolerance or cyclic
normalization is used. The comparator reads one mesh record at a time and sorts
16-byte digests in temporary memory-mapped files. Hash collisions have a finite,
negligible probability; this is content-hash evidence rather than a direct
whole-triangle byte comparison.

Only complete RDCITY01/02/04 vertex records are supported. Compact lighting has
lost source normals/color precision and cannot prove this contract. This is a
geometry-preservation check; use validate_city.py for full structural/provenance
and walking-route validation. Vertex counts are reported separately because
rebatching may duplicate shared vertices without changing triangle geometry.

Directory inputs also compare the original level/layout placement fields,
ignoring added fields but preserving original values and list order. Changes to
mesh digests, render statistics and geometry-format declarations are expected.
Exit status is 0 for parity and 1 for changed geometry/placements or bad input.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import sys

import numpy as np

from validate_city import (MAX_INSTANCE_INDICES, MAX_INSTANCE_VERTICES, MAX_INSTANCES,
                           MAX_MESH_BYTES, MAX_METADATA_BYTES, parse_json, read_json,
                           require, verify_instance_metadata)


class MeshReader:
    """Bound total decoded input while retaining a streaming gzip reader."""
    def __init__(self, stream):
        self.stream = stream
        self.offset = 0

    def read(self, size):
        require(self.offset + size <= MAX_MESH_BYTES, 'decoded mesh exceeds size limit')
        data = self.stream.read(size)
        require(len(data) == size, 'truncated city geometry')
        self.offset += size
        return data


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            digest.update(block)
    return digest.hexdigest()


def triangle_hashes(path, destination):
    """Write/sort a winding-sensitive triangle digest multiset and report counts."""
    require(12 <= path.stat().st_size <= MAX_MESH_BYTES, 'mesh file outside bounded size')
    triangles = vertices = 0
    with path.open('rb') as raw, destination.open('wb') as hashes:
        signature = raw.read(2)
        raw.seek(0)
        stream = gzip.GzipFile(fileobj=raw) if signature == b'\x1f\x8b' else raw
        try:
            reader = MeshReader(stream)
            magic = reader.read(8)
            require(magic in (b'RDCITY01', b'RDCITY02', b'RDCITY03', b'RDCITY04'),
                    'unsupported city mesh format')
            require(magic != b'RDCITY03', 'compact geometry cannot prove complete vertex byte parity')
            metadata = None
            instanced = magic == b'RDCITY04'
            if instanced:
                flags, metadata_size = struct.unpack('<II', reader.read(8))
                require(flags in (0, 1, 3), 'invalid city instance flags')
                require(not flags & 2, 'compact geometry cannot prove complete vertex byte parity')
                require(0 < metadata_size <= MAX_METADATA_BYTES, 'invalid city instance metadata size')
                metadata = parse_json(reader.read(metadata_size).decode('utf-8'))
                verify_instance_metadata(metadata)
            count, = struct.unpack('<I', reader.read(4))
            require(0 < count <= (MAX_INSTANCES if instanced else 16384), 'invalid city mesh record count')
            require(metadata is None or len(metadata) == count, 'metadata/geometry count mismatch')
            index_type = '<u4' if instanced else '<u2'
            for _ in range(count):
                *bounds, vc, ic = struct.unpack('<6fII', reader.read(32))
                require(0 < vc <= (MAX_INSTANCE_VERTICES if instanced else 60000)
                        and 0 < ic <= (MAX_INSTANCE_INDICES if instanced else 360000)
                        and ic % 3 == 0, 'invalid vertex/index count')
                vertex_records = np.frombuffer(reader.read(vc * 40), dtype='V40')
                indices = np.frombuffer(reader.read(ic * np.dtype(index_type).itemsize), dtype=index_type)
                require(int(indices.max()) < vc, 'out of range city index')
                for start in range(0, ic, 3 * 16384):
                    ordered = memoryview(vertex_records[indices[start:start + 3 * 16384]].tobytes())
                    hashes.write(b''.join(hashlib.blake2b(ordered[offset:offset + 120], digest_size=16).digest()
                                          for offset in range(0, len(ordered), 120)))
                vertices += vc
                triangles += ic // 3
            require(stream.read(1) == b'', 'trailing city geometry data')
        finally:
            if stream is not raw:
                stream.close()
    values = np.memmap(destination, dtype='V16', mode='r+')
    values.sort()
    values.flush()
    digest = hashlib.sha256(memoryview(values)).hexdigest()
    del values
    return {'format': magic.decode('ascii'), 'records': count, 'vertices': vertices,
            'triangles': triangles, 'sorted_triangle_hashes_sha256': digest,
            'mesh_sha256': file_sha256(path)}


def original_fields_equal(original, current):
    """Permit new metadata keys while requiring all original content unchanged."""
    if isinstance(original, dict):
        return isinstance(current, dict) and all(
            key in current and original_fields_equal(value, current[key])
            for key, value in original.items())
    if isinstance(original, list):
        return isinstance(current, list) and len(original) == len(current) and all(
            original_fields_equal(a, b) for a, b in zip(original, current))
    return original == current


def compare_city_geometry(baseline, candidate):
    baseline, candidate = Path(baseline), Path(candidate)
    baseline_mesh = baseline / 'meshes.bin' if baseline.is_dir() else baseline
    candidate_mesh = candidate / 'meshes.bin' if candidate.is_dir() else candidate
    with tempfile.TemporaryDirectory(prefix='city_triangle_parity_') as work:
        work = Path(work)
        old = triangle_hashes(baseline_mesh, work / 'baseline.hashes')
        new = triangle_hashes(candidate_mesh, work / 'candidate.hashes')
        left = np.memmap(work / 'baseline.hashes', dtype='V16', mode='r')
        right = np.memmap(work / 'candidate.hashes', dtype='V16', mode='r')
        same = bool(len(left) == len(right) and np.array_equal(left, right))
        del left, right
    checks = {'winding_sensitive_triangle_vertex_normal_rgba_multiset_equal': same}
    metadata_checked = baseline.is_dir() and candidate.is_dir()
    if metadata_checked:
        old_level, new_level = read_json(baseline / 'level.json'), read_json(candidate / 'level.json')
        old_layout, new_layout = read_json(baseline / 'layout.json'), read_json(candidate / 'layout.json')
        for field in ('colliders', 'buildings', 'spawn', 'supply_position', 'landmarks', 'bounds'):
            require(field in old_level and field in new_level, f'missing level field: {field}')
            checks[f'original_level_{field}_fields_equal'] = original_fields_equal(old_level[field], new_level[field])
        for field in ('buildings', 'instances'):
            require(field in old_layout and field in new_layout, f'missing layout field: {field}')
            checks[f'original_layout_{field}_fields_equal'] = original_fields_equal(old_layout[field], new_layout[field])
    return {'schema': 'rust-duty-city-geometry-parity/v1', 'baseline': old, 'candidate': new,
            'comparison': 'Sorted BLAKE2b-128 multiset over 120 raw bytes per ordered triangle: '
                          'positions, normals and RGBA. No winding normalization or float tolerance.',
            'vertex_count_equal': old['vertices'] == new['vertices'],
            'placement_metadata_checked': metadata_checked, 'checks': checks,
            'passed': all(checks.values())}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('baseline', type=Path, help='Original mesh file or city directory')
    parser.add_argument('candidate', type=Path, help='Candidate mesh file or city directory')
    parser.add_argument('--report', type=Path, help='Also save the JSON result to this path')
    args = parser.parse_args(argv)
    try:
        result = compare_city_geometry(args.baseline, args.candidate)
    except (OSError, EOFError, ValueError, RecursionError, struct.error) as error:
        result = {'schema': 'rust-duty-city-geometry-parity/v1', 'passed': False, 'error': str(error)}
    encoded = json.dumps(result, indent=2) + '\n'
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded, encoding='utf-8')
    print(encoded, end='')
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
