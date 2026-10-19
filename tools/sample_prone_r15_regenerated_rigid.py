#!/usr/bin/env python3
"""Read-only private rigid oracle from a proven-equivalent regenerated r15 scene.

This script contains no geometry. Its output is private and must not be committed.
Evaluated local vertices and polygon topology must remain constant at every
independently prescribed source time before a rigid-motion witness is accepted.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prone_camera_pair as pair
import prone_r15_regenerated_contract as contract
from export_prone_pair import bound_pair, action_fingerprint

GRID_SHA = 'f47bb34d734b7e5bf01806530c23367a45214e9037ea445c102e9405db9ff1e4'
ACTORS = ('hk416_weapon', 'hk416_magazine', 'hk416_magazine_outgoing')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def main():
    import bpy
    p = argparse.ArgumentParser()
    p.add_argument('--grid', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--source-equivalence', type=Path, required=True)
    p.add_argument('--source-equivalence-sha256', required=True)
    args = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    assert not args.output.exists(), 'Fresh output required'
    source = Path(bpy.data.filepath)
    source_sha = digest(source.read_bytes())
    proof = contract.descriptor(args.source_equivalence, args.source_equivalence_sha256, source)
    assert bpy.app.background and bpy.app.version_string == '4.3.2'
    assert not bpy.context.preferences.filepaths.use_scripts_auto_execute
    grid_bytes = args.grid.read_bytes()
    assert digest(grid_bytes) == GRID_SHA
    grid = json.loads(grid_bytes)
    assert len(grid) == 1944 and grid == sorted(set(grid)) and grid[0] == 1 and grid[-1] == 69
    for name, expected in pair.R15_FINGERPRINTS.items():
        assert action_fingerprint(bpy.data.actions[name]) == expected
    scene = bpy.context.scene
    assert (scene.render.fps, scene.render.fps_base) == (60, 1.)
    config = {'armature': 'Arms', 'camera': 'RD First Person Review',
              'base_action': 'RD_00_Supplied_Base_Guarded_Recovered',
              'source_take': pair.R15_RIG_ACTION, 'camera_action': pair.R15_CAMERA_ACTION}
    actors = {}
    samples = []
    with bound_pair(bpy, config):
        for index, frame in enumerate(grid):
            scene.frame_set(math.floor(frame), subframe=frame - math.floor(frame))
            bpy.context.view_layer.update()
            deps = bpy.context.evaluated_depsgraph_get()
            deps.update()
            sample = {'source_frame': frame, 'actors': {}}
            for name in ACTORS:
                obj = bpy.data.objects[name].evaluated_get(deps)
                mesh = obj.to_mesh()
                try:
                    vertices = [[float(v) for v in vertex.co] for vertex in mesh.vertices]
                    polygons = [list(poly.vertices) for poly in mesh.polygons]
                    assert vertices and polygons and all(math.isfinite(v) for row in vertices for v in row)
                    geometry = {'vertices_local': vertices, 'polygons': polygons}
                    fingerprint = digest(json.dumps(geometry, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
                    if index == 0:
                        actors[name] = {**geometry, 'geometry_sha256': fingerprint,
                                        'vertex_count': len(vertices), 'polygon_count': len(polygons),
                                        'world_at_frame1': [list(row) for row in obj.matrix_world]}
                    assert fingerprint == actors[name]['geometry_sha256'], (frame, name, 'not rigid')
                    sample['actors'][name] = {'geometry_sha256': fingerprint,
                                             'hide_render': bool(obj.hide_render)}
                finally:
                    obj.to_mesh_clear()
            samples.append(sample)
            if index % 256 == 0:
                print('R15_RIGID_ORACLE', index, len(grid), flush=True)
    assert digest(source.read_bytes()) == source_sha
    result = {'schema': 'rust-duty-private-prone-rigid-oracle/v1', 'passed': True,
              'source_sha256': source_sha, 'source_equivalence_descriptor': proof,
              'source_equivalence_sha256': args.source_equivalence_sha256, 'action_fingerprints': pair.R15_FINGERPRINTS,
              'sample_grid_sha256': GRID_SHA, 'source_frames': grid, 'sample_count': len(grid),
              'basis': 'Blender evaluated mesh local; world_at_frame1 is Blender world',
              'actors': actors, 'samples': samples,
              'scope': 'Private source geometry and rigidity oracle; no runtime validation claimed'}
    with args.output.open('x') as stream:
        json.dump(result, stream, sort_keys=True, separators=(',', ':'), allow_nan=False)
        stream.write('\n')
    print('R15_RIGID_ORACLE_COMPLETE', digest(args.output.read_bytes()), flush=True)

if __name__ == '__main__':
    main()
