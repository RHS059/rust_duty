#!/usr/bin/env python3
"""Independently check Cedar Junction geometry, provenance, and walking routes.

This is a CPU structural/clearance check, not visual or real-GPU acceptance.
The route probe uses the game's standing player dimensions and step limit.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re
import struct
import subprocess

CITY_DIR = Path('assets/levels/cedar_junction')
RADIUS = .381
HEIGHT = 1.778
STEP = .4573
EPS = .0001
MAX_MESH_BYTES = 768 * 1024**2
MAX_METADATA_BYTES = 32 * 1024**2
MAX_INSTANCES = 262144
MAX_INSTANCE_VERTICES = 4_000_000
MAX_INSTANCE_INDICES = 12_000_000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def vector(value, label):
    require(isinstance(value, list) and len(value) == 3
            and all(type(v) in (int, float) and math.isfinite(v) for v in value),
            f'{label}: expected three finite numbers')
    return value


def parse_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f'duplicate JSON key: {key}')
            result[key] = value
        return result
    data = json.loads(text, object_pairs_hook=unique)
    json.dumps(data, allow_nan=False)
    return data


def read_json(path):
    return parse_json(path.read_text(encoding='utf-8'))


def verify_instance_metadata(metadata):
    require(isinstance(metadata, list) and 0 < len(metadata) <= MAX_INSTANCES,
            'invalid city instance metadata array')
    for index, row in enumerate(metadata):
        label = f'instance {index}'
        # Generated lighting panels have no authored source identity. The Rust
        # writer also emits explicit null for absent optional fields.
        if row is None:
            continue
        require(isinstance(row, dict), f'{label}: metadata must be an object')
        require(type(row.get('id')) is int and 0 <= row['id'] <= 0xffffffff,
                f'{label}: invalid source instance id')
        require(isinstance(row.get('asset'), str)
                and 0 < len(row['asset'].encode('utf-8')) <= 512,
                f'{label}: missing asset identity')
        if row.get('building') is not None:
            require(isinstance(row['building'], str)
                    and 0 < len(row['building'].encode('utf-8')) <= 128,
                    f'{label}: invalid building identity')
        distance = row.get('max_distance')
        if distance is None:
            distance = 0.
        require(type(distance) in (int, float) and 0 <= distance <= 400
                and math.isfinite(distance),
                f'{label}: invalid maximum draw distance')
    # Baking can split one authored source identity into several mesh records.
    # Repeated IDs are intentional and are not a duplicate-object error.


def verify_mesh(path):
    size = path.stat().st_size
    require(12 <= size <= MAX_MESH_BYTES, 'mesh file outside bounded size')
    packed = path.read_bytes()
    if packed[:2] == b'\x1f\x8b':
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:
                data = stream.read(MAX_MESH_BYTES + 1)
        except (OSError, EOFError) as error:
            raise ValueError('invalid compressed city mesh') from error
        require(len(data) <= MAX_MESH_BYTES, 'decoded mesh exceeds size limit')
    else:
        data = packed
    size = len(data)
    require(size >= 12, 'truncated city mesh header')
    magic = data[:8]
    require(magic in (b'RDCITY01', b'RDCITY02', b'RDCITY03', b'RDCITY04'),
            'wrong city mesh signature')
    instanced = magic == b'RDCITY04'
    metadata = None
    offset = 8
    if instanced:
        require(offset + 8 <= size, 'truncated city instance header')
        flags, metadata_bytes = struct.unpack_from('<II', data, offset)
        offset += 8
        require(flags in (0, 1, 3), 'invalid city instance flags')
        require(0 < metadata_bytes <= MAX_METADATA_BYTES,
                'invalid city instance metadata size')
        require(offset + metadata_bytes + 4 <= size, 'truncated city instance metadata')
        try:
            metadata = parse_json(data[offset:offset + metadata_bytes].decode('utf-8'))
        except (UnicodeError, ValueError, RecursionError) as error:
            raise ValueError(f'invalid city instance metadata: {error}') from error
        verify_instance_metadata(metadata)
        offset += metadata_bytes
        compact = bool(flags & 2)
        prelit = bool(flags & 1)
    else:
        compact = magic == b'RDCITY03'
        prelit = magic != b'RDCITY01'
    chunks, = struct.unpack_from('<I', data, offset)
    offset += 4
    require(0 < chunks <= (MAX_INSTANCES if instanced else 16384),
            'invalid city mesh chunk count')
    if metadata is not None:
        require(len(metadata) == chunks, 'city instance metadata/geometry count mismatch')
    vertex_stride = 16 if compact else 40
    index_stride = 4 if instanced else 2
    vertex_limit = MAX_INSTANCE_VERTICES if instanced else 60000
    index_limit = MAX_INSTANCE_INDICES if instanced else 360000
    vertices, triangles = 0, 0
    for chunk in range(chunks):
        require(offset + 32 <= size, 'truncated mesh chunk header')
        *bounds, vc, ic = struct.unpack_from('<6fII', data, offset)
        offset += 32
        require(all(math.isfinite(n) for n in bounds), 'nonfinite mesh bounds')
        require(all(bounds[n] <= bounds[n + 3] for n in range(3)), 'inverted mesh bounds')
        require(0 < vc <= vertex_limit and 0 < ic <= index_limit and ic % 3 == 0,
                f'chunk {chunk}: invalid vertex/index count')
        vertex_end = offset + vc * vertex_stride
        index_end = vertex_end + ic * index_stride
        require(index_end <= size, 'truncated mesh chunk data')
        for row in struct.iter_unpack('<3f4B' if compact else '<10f', data[offset:vertex_end]):
            require(all(math.isfinite(n) for n in row), f'chunk {chunk}: nonfinite vertex')
            require(all(bounds[n] - .01 <= row[n] <= bounds[n + 3] + .01 for n in range(3)),
                    f'chunk {chunk}: vertex outside bounds')
            if not compact:
                require(all(0 <= n <= 1 for n in row[6:]), f'chunk {chunk}: color outside range')
                normal_length = sum(n * n for n in row[3:6]) ** .5
                require(.9 <= normal_length <= 1.1, f'chunk {chunk}: non-unit normal')
        offset = vertex_end
        for index, in struct.iter_unpack('<I' if instanced else '<H', data[offset:index_end]):
            require(index < vc, f'chunk {chunk}: out of range index')
        offset = index_end
        vertices += vc
        triangles += ic // 3
    require(offset == size, 'trailing mesh data')
    return {'chunks': chunks, 'vertices': vertices, 'triangles': triangles,
            'format': magic.decode('ascii'), 'prelit': prelit, 'compact': compact,
            'bytes': len(packed), 'decoded_bytes': size, 'sha256': hashlib.sha256(packed).hexdigest()}


def horizontal_overlap(point, box):
    return all(point[n] + RADIUS > box['min'][n] + EPS
               and point[n] - RADIUS < box['max'][n] - EPS for n in (0, 2))


class CollisionIndex:
    """Spatial lookup only; all acceptance still uses the original AABBs."""
    def __init__(self, boxes):
        self.cells = defaultdict(list)
        self.wide = []
        for i, box in enumerate(boxes):
            x0, x1 = (math.floor((box[key][0] + sign * RADIUS) / 4) for key, sign in (('min', -1), ('max', 1)))
            z0, z1 = (math.floor((box[key][2] + sign * RADIUS) / 4) for key, sign in (('min', -1), ('max', 1)))
            if (x1 - x0 + 1) * (z1 - z0 + 1) > 4096:
                self.wide.append((i, box))
                continue
            for x in range(x0, x1 + 1):
                for z in range(z0, z1 + 1):
                    self.cells[x, z].append((i, box))

    def near(self, point):
        return self.cells.get((math.floor(point[0] / 4), math.floor(point[2] / 4)), []) + self.wide


def nearby(colliders, point):
    return colliders.near(point) if isinstance(colliders, CollisionIndex) else enumerate(colliders)


def body_clear(point, colliders):
    for i, box in nearby(colliders, point):
        if (horizontal_overlap(point, box) and point[1] + HEIGHT > box['min'][1] + EPS
                and point[1] < box['max'][1] - EPS):
            return False, i
    return True, None


def floor_at(point, colliders, max_y):
    # The engine's continuous ground plane is at y=0.
    return max([0.] + [box['max'][1] for _, box in nearby(colliders, point)
                      if horizontal_overlap(point, box) and box['max'][1] <= max_y + EPS])


def walk_route(points, colliders, label):
    require(isinstance(points, list) and len(points) >= 2, f'{label}: route needs two points')
    points = [vector(p, label) for p in points]
    previous = list(points[0])
    support = floor_at(previous, colliders, previous[1] + .02)
    require(abs(support - previous[1]) <= .025, f'{label}: start lacks floor support')
    clear, blocker = body_clear(previous, colliders)
    require(clear, f'{label}: start blocked by collider {blocker} at {previous}')
    samples, largest_rise, lowest_headroom = 1, 0., None
    for target in points[1:]:
        begin = previous.copy()
        distance = math.hypot(target[0] - begin[0], target[2] - begin[2])
        require(distance > EPS or abs(target[1] - begin[1]) <= .025,
                f'{label}: vertical teleport in path')
        count = max(1, math.ceil(distance / .08))
        for j in range(1, count + 1):
            f = j / count
            current = [begin[0] + (target[0] - begin[0]) * f,
                       previous[1], begin[2] + (target[2] - begin[2]) * f]
            support = floor_at(current, colliders, previous[1] + STEP)
            rise = support - previous[1]
            require(abs(rise) <= STEP + EPS,
                    f'{label}: unsupported step/drop {rise:.3f} m at {current}')
            current[1] = support
            clear, blocker = body_clear(current, colliders)
            require(clear, f'{label}: blocked by collider {blocker} at {current}')
            overhead = [box['min'][1] - support for _, box in nearby(colliders, current)
                        if horizontal_overlap(current, box) and box['min'][1] > support + EPS]
            if overhead:
                headroom = min(overhead)
                lowest_headroom = headroom if lowest_headroom is None else min(lowest_headroom, headroom)
            largest_rise = max(largest_rise, rise)
            samples += 1
            previous = current
        # Stair-front overlap raises the game collider before its center reaches
        # a tread. Permit one step difference at intermediate stair witnesses.
        require(abs(previous[1] - target[1]) <= STEP + EPS,
                f'{label}: route height differs from supporting geometry at {target}, got {previous[1]}')
    require(abs(previous[1] - points[-1][1]) <= .025,
            f'{label}: final floor does not match declared destination')
    return {'name': label, 'samples': samples, 'largest_step': round(largest_rise, 6),
            'minimum_headroom': None if lowest_headroom is None else round(lowest_headroom, 6)}


def verify_level(level, mesh_file):
    require(level.get('schema') == 'rust-duty-city/v1', 'wrong city level schema')
    require(isinstance(level.get('name'), str) and level['name'].strip(), 'city name missing')
    require(level.get('mesh_file') == mesh_file, 'unexpected city mesh path')
    spawn = vector(level.get('spawn', {}).get('position'), 'spawn')
    yaw = level.get('spawn', {}).get('yaw_degrees')
    require(type(yaw) in (int, float) and math.isfinite(yaw), 'invalid spawn yaw')
    boxes = level.get('colliders')
    require(isinstance(boxes, list) and 0 < len(boxes) < 200000, 'invalid colliders')
    for i, box in enumerate(boxes):
        low, high = vector(box.get('min'), f'collider {i} min'), vector(box.get('max'), f'collider {i} max')
        require(all(a < b for a, b in zip(low, high)), f'collider {i}: inverted/flat bounds')
        require(type(box.get('kind', 0)) is int and 0 <= box.get('kind', 0) <= 255,
                f'collider {i}: invalid kind')
    collider_count = len(boxes)
    boxes = CollisionIndex(boxes)
    clear, blocker = body_clear(spawn, boxes)
    require(clear, f'spawn blocked by collider {blocker}')
    require(abs(floor_at(spawn, boxes, spawn[1] + .02) - spawn[1]) <= .025, 'spawn lacks support')
    buildings = level.get('buildings')
    require(isinstance(buildings, list) and len(buildings) >= 3, 'expected multiple enterable buildings')
    routes, doors, stairs, multistory = [], 0, 0, 0
    names = set()
    for building in buildings:
        name = building.get('id', building.get('name'))
        require(isinstance(name, str) and name not in names, 'missing/duplicate building id')
        names.add(name)
        floors = building.get('floor_levels')
        require(isinstance(floors, list) and floors and all(type(f) in (int, float) and math.isfinite(f) for f in floors)
                and all(a < b for a, b in zip(floors, floors[1:])), f'{name}: invalid floor levels')
        require(building.get('stories') == len(floors), f'{name}: stories/floor count mismatch')
        multistory += len(floors) > 1
        entrances = building.get('entrances')
        require(isinstance(entrances, list) and entrances, f'{name}: no entrances')
        for i, entrance in enumerate(entrances):
            p = vector(entrance.get('position'), f'{name} entrance')
            inward = vector(entrance.get('inward'), f'{name} entrance inward')
            require(abs(inward[1]) <= EPS and abs(math.hypot(inward[0], inward[2]) - 1) <= EPS,
                    f'{name}: invalid entrance direction')
            require(entrance.get('width', 0) >= 2 * RADIUS + .1 and entrance.get('height', 0) >= HEIGHT + .1,
                    f'{name}: entrance insufficient standing clearance')
            points = [[p[k] + sign * 1.2 * inward[k] for k in range(3)] for sign in (-1, 1)]
            routes.append(walk_route(points, boxes, f'{name}/entrance-{i}'))
            doors += 1
        flights = building.get('stairs', [])
        pairs = set()
        for i, stair in enumerate(flights):
            lower, upper = stair.get('from_floor'), stair.get('to_floor')
            require(type(lower) is int and type(upper) is int and 0 <= lower < upper < len(floors),
                    f'{name}: invalid stair floors')
            require(0 < stair.get('rise', 0) <= STEP and stair.get('tread', 0) > .15
                    and stair.get('width', 0) >= 2 * RADIUS + .1, f'{name}: invalid stair dimensions')
            path = stair.get('path')
            require(isinstance(path, list) and len(path) >= 2, f'{name}: stair route missing')
            require(abs(path[0][1] - floors[lower]) < .025 and abs(path[-1][1] - floors[upper]) < .025,
                    f'{name}: stair route does not reach its floors')
            routes.append(walk_route(path, boxes, f'{name}/stairs-{i}'))
            routes.append(walk_route(list(reversed(path)), boxes, f'{name}/stairs-{i}-descent'))
            pairs.add((lower, upper))
            stairs += 1
        require(all((i, i + 1) in pairs for i in range(len(floors) - 1)), f'{name}: an upper floor lacks stairs')
        for i, route in enumerate(building.get('routes', [])):
            path = route.get('path') if isinstance(route, dict) else route
            routes.append(walk_route(path, boxes, f'{name}/interior-{i}'))
    require(multistory >= 2, 'expected multiple buildings with reachable upper floors')
    for i, route in enumerate(level.get('routes', [])):
        path = route.get('path') if isinstance(route, dict) else route
        routes.append(walk_route(path, boxes, f'city/route-{i}'))
    return {'name': level['name'], 'colliders': collider_count, 'buildings': len(buildings),
            'entrances': doors, 'stair_connections': stairs, 'multistory_buildings': multistory,
            'route_count': len(routes), 'route_samples': sum(r['samples'] for r in routes), 'routes': routes}


def verify_provenance(root, level, source=None):
    lock = read_json(root / 'tools/city_source_lock.json')
    require(lock.get('repository') == 'RHS059/low_poly_items', 'unexpected city source repository')
    commit = lock.get('commit')
    require(isinstance(commit, str) and re.fullmatch('[0-9a-f]{40}', commit), 'source commit is not pinned')
    assets = lock.get('assets')
    require(isinstance(assets, list) and assets, 'no source assets pinned')
    ids, paths = set(), set()
    for record in assets:
        asset_id, relative, sha = record.get('id'), record.get('path'), record.get('sha256')
        require(isinstance(asset_id, str) and asset_id and asset_id not in ids, 'missing/duplicate source asset id')
        require(isinstance(relative, str) and re.fullmatch(r'[A-Za-z0-9_./-]+\.glb', relative)
                and not Path(relative).is_absolute() and '..' not in Path(relative).parts
                and relative not in paths, 'unsafe/duplicate source GLB path')
        require(isinstance(sha, str) and re.fullmatch('[0-9a-f]{64}', sha), 'source asset SHA-256 missing')
        ids.add(asset_id)
        paths.add(relative)
        if source is not None:
            path = source / relative
            require(path.is_file() and not path.is_symlink(), f'missing source GLB: {relative}')
            require(hashlib.sha256(path.read_bytes()).hexdigest() == sha, f'source GLB digest differs: {relative}')
    layout = read_json(root / CITY_DIR / 'layout.json')
    instances = layout.get('instances')
    require(isinstance(instances, list) and instances, 'asset placement inventory missing')
    used = {row.get('asset') for row in instances}
    require(used == ids, 'source lock/placed asset inventory mismatch')
    require(layout.get('buildings') == level['buildings'], 'layout/level building metadata differ')
    for i, row in enumerate(instances):
        vector(row.get('position'), f'instance {i} position')
        scale = vector(row.get('scale'), f'instance {i} scale')
        require(all(v > 0 for v in scale), f'instance {i}: invalid scale')
        require(type(row.get('yaw')) in (int, float) and math.isfinite(row['yaw']), f'instance {i}: invalid yaw')
    if source is not None:
        head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        require(head == commit, 'source checkout commit differs from provenance pin')
    return {'repository': lock['repository'], 'commit': commit, 'unique_assets': len(ids),
            'asset_instances': len(instances), 'source_bytes_checked': source is not None,
            'source_lock_sha256': hashlib.sha256((root / 'tools/city_source_lock.json').read_bytes()).hexdigest()}


def verify(root, source=None):
    root = Path(root)
    folder = root / CITY_DIR
    level = read_json(folder / 'level.json')
    result = verify_level(level, 'meshes.bin')
    result['schema'] = 'rust-duty-city-validation/v1'
    result['level_sha256'] = hashlib.sha256((folder / 'level.json').read_bytes()).hexdigest()
    result['mesh'] = verify_mesh(folder / 'meshes.bin')
    require(level.get('mesh_sha256') == result['mesh']['sha256'], 'level/mesh SHA-256 mismatch')
    if 'geometry_format' in level:
        require(level['geometry_format'] == result['mesh']['format'],
                'level/mesh geometry format mismatch')
    result['provenance'] = verify_provenance(root, level, Path(source) if source else None)
    expected = {key: result[key] for key in ('buildings', 'colliders')}
    expected.update({key: result['provenance'][key] for key in ('unique_assets', 'asset_instances')})
    expected.update({'render_chunks': result['mesh']['chunks'], 'vertices': result['mesh']['vertices'],
                     'triangles': result['mesh']['triangles']})
    require(level.get('statistics') == expected, 'level statistics differ from actual geometry/inventory')
    result['passed'] = True
    result['scope'] = 'CPU geometry and standing route clearance; no native visual acceptance'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--source', type=Path, help='Optional local low_poly_items checkout for digest verification')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = json.dumps(verify(args.root, args.source), indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result, encoding='utf-8')
    else:
        print(result, end='')


if __name__ == '__main__':
    main()
