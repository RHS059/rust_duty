"""Synthetic CPU-only rigid witness boundary regressions; never imports bpy.

The three geometry helpers below execute unchanged, hash-checked fragments.
The fake scene supplies only frame/update methods; rigid_stage, write_new,
strict_json, FilePin verification and full geometry equality run for real.
"""
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as N
import unittest
from unittest.mock import patch

HERE = Path(__file__).absolute().parent
OLD_READ = "baseline=ctx.cc.strict_json(ctx.pin('rigid_frame1').verify())"
NEW_READ = "baseline=ctx.cc.strict_json(ctx.pin('rigid_frame1').verify(),32*MIB)"
PREDECESSOR_NATIVE_SHA = 'ecc58db55b78c9a178fa3bbbd07baa6fb5398dc961cbb636b4fa42fa27e1367d'


def original_native_stages_bytes():
    raw = (HERE / 'native_stages.py').read_bytes()
    assert raw.count(NEW_READ.encode()) == 1
    assert OLD_READ.encode() not in raw
    return raw.replace(NEW_READ.encode(), OLD_READ.encode())


def original_native_stages_sha():
    return hashlib.sha256(original_native_stages_bytes()).hexdigest()


class RigidJsonBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import numpy as np
        import pinned_code as p
        import native_stages as n
        import stage_context as s
        import planner
        cls.np, cls.p, cls.n, cls.s, cls.planner = np, p, n, s, planner
        root = HERE.parent / 'windows-context-preparation-v3'
        if not root.is_dir():
            root = HERE.parent / 'context-v3'
        cls.cc = p.load_context(root)
        cls.helpers = {'np': np, 'hashlib': hashlib, 'math': math, 'json': json}
        # GeometryBytes has a dataclass decorator, supplied exactly as helpers().
        from dataclasses import dataclass
        cls.helpers['dataclass'] = dataclass
        for name in ('GeometryBytes', 'canonical_buffers', 'geometry_record'):
            p.execute(name, cls.helpers)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).absolute()
        self.clock = N(frame=1.)
        def frame_set(frame, subframe=0.):
            self.clock.frame = frame + subframe
        update = lambda: None
        self.actor_objects = {name: N(hide_render=False, matrix_world=self.np.eye(4))
                              for name in self.n.ACTORS}
        scene = N(frame_set=frame_set)
        bpy = N(data=N(objects=self.actor_objects), context=N(
            view_layer=N(update=update), evaluated_depsgraph_get=lambda: N(update=update)))
        self.e = {'bpy': bpy, 'A': N(update_tag=update), 'C': N(update_tag=update),
                  'S': scene, 'mat': lambda matrix: matrix.tolist(),
                  'geometry_record': self.helpers['geometry_record']}
        self.cc = type(self).cc
        self.files = {}
        self.ctx = N(stage='rigid-frame1', output=self.root, cc=self.cc,
                     binding={'candidate_id': 'synthetic-rigid-cap'},
                     action_hashes=(('legacy', 'a' * 64),), frames=lambda: [1.],
                     pin=self.pin)
        source = self.root / 'synthetic-source-id'
        source.write_bytes(b'CPU fixture only; not a Blender file')
        self.files['generated_source'] = self.cc.FilePin('generated_source', source,
                                                         self.p.file_sha(source))
        self.geometry(3)

    def tearDown(self):
        self.tmp.cleanup()

    def pin(self, role):
        return self.files[role]

    def geometry(self, count):
        self.vertices = self.np.tile([0.123456789012345, -0.234567890123456,
                                      0.345678901234567], (count, 1))
        starts = self.np.arange(0, count, 3, dtype=self.np.int64)
        sizes = self.np.full(len(starts), 3, dtype=self.np.int64)
        indices = self.np.arange(count, dtype=self.np.int64)
        self.buffers = self.helpers['canonical_buffers'](self.vertices, starts, sizes, indices)
        self.e['geometry'] = lambda name, graph: (self.vertices, self.buffers)

    def produce(self):
        result = self.n.rigid_stage(self.ctx, self.e)
        path = self.root / 'rigid-frame1.json'
        self.files['rigid_frame1'] = self.cc.FilePin('rigid_frame1', path, self.p.file_sha(path))
        return path, result

    def consume(self, stage='rigid-focus', frames=None):
        self.ctx.stage = stage
        self.ctx.frames = lambda: list(self.cc.FOCUS) if frames is None else frames
        return self.n.rigid_stage(self.ctx, self.e)

    def rebind(self, raw):
        path = self.root / 'rigid-frame1.json'
        path.write_bytes(raw)
        self.files['rigid_frame1'] = self.cc.FilePin('rigid_frame1', path, self.p.file_sha(path))
        return path

    def test_exact_one_call_predecessor_reconstruction(self):
        self.assertEqual(original_native_stages_sha(), PREDECESSOR_NATIVE_SHA)

    def test_every_other_production_file_is_exact_v7(self):
        old = json.loads((HERE / 'RIGID_JSON_CAP_PREDECESSOR.json').read_bytes())
        for name, wanted in old['files'].items():
            if name.endswith('.py') and not name.startswith('test_'):
                actual = original_native_stages_sha() if name == 'native_stages.py' else self.p.file_sha(HERE / name)
                self.assertEqual(actual, wanted, name)
        self.assertEqual(self.p.file_sha(HERE / 'AUDITED_FRAGMENTS.json'), old['files']['AUDITED_FRAGMENTS.json'])

    def test_read_bound_matches_existing_writer_and_stage_cap(self):
        self.assertEqual(self.cc.strict_json.__defaults__, (2 * 1024**2,))
        self.assertEqual(self.s.write_new.__defaults__, (32 * 1024**2,))
        self.assertEqual(self.planner.output_cap(self.ctx), 32 * 1024**2)

    def test_actual_large_roundtrip_focus_and_chunk(self):
        self.geometry(24000)
        path, first = self.produce()
        self.assertGreater(path.stat().st_size, 2 * 1024**2)
        self.assertLess(path.stat().st_size, 32 * 1024**2)
        with self.assertRaisesRegex(ValueError, 'JSON byte cap exceeded'):
            self.cc.strict_json(path)
        for stage, frames in [('rigid-focus', list(self.cc.FOCUS)),
                              ('rigid-chunk', [1. + i / 256 for i in range(64)])]:
            with self.subTest(stage=stage):
                result = self.consume(stage, frames)
                self.assertEqual(result['source_frames'], frames)
                self.assertEqual(len(result['samples']), len(frames))
                self.assertEqual(result['frame1_buffer_digests'], first['frame1_buffer_digests'])
                self.assertTrue(result['full_float64_and_topology_bytes_compared'])

    def test_exact_cap_is_accepted_without_removing_geometry_checks(self):
        path, _ = self.produce()
        raw = path.read_bytes()
        self.rebind(raw + b' ' * (32 * 1024**2 - len(raw)))
        self.assertEqual(len(self.consume()['samples']), 9)

    def test_one_byte_over_cap_rejected_by_actual_stage(self):
        self.rebind(b'{}' + b' ' * (32 * 1024**2 - 1))
        with self.assertRaisesRegex(ValueError, 'JSON byte cap exceeded'):
            self.consume()

    def test_original_writer_rejects_one_byte_over_cap(self):
        # JSON string quotes plus its output newline add three bytes.
        with self.assertRaisesRegex(ValueError, 'bounded JSON output exceeded'):
            self.s.write_new(self.root / 'oversize.json', 'x' * (32 * 1024**2 - 2))
        self.assertFalse((self.root / 'oversize.json').exists())

    def test_metadata_default_remains_two_mib(self):
        path = self.root / 'metadata.json'
        path.write_bytes(b'{}' + b' ' * (2 * 1024**2 - 1))
        with self.assertRaisesRegex(ValueError, 'JSON byte cap exceeded'):
            self.cc.strict_json(path)

    def test_pin_mismatch_rejected_before_json_parse(self):
        path, _ = self.produce()
        path.write_bytes(b'not json')
        with patch.object(self.cc, 'strict_json', wraps=self.cc.strict_json) as read:
            with self.assertRaisesRegex(ValueError, 'pinned bytes differ: rigid_frame1'):
                self.consume()
            read.assert_not_called()

    def test_unknown_role_is_not_a_cap_bypass(self):
        self.produce()
        self.files['unrecognized_geometry'] = self.files.pop('rigid_frame1')
        with self.assertRaises(KeyError):
            self.consume()

    def test_symlink_is_rejected(self):
        path, _ = self.produce()
        real = self.root / 'real-witness.json'
        path.rename(real)
        path.symlink_to(real)
        with self.assertRaisesRegex(ValueError, 'symlink/reparse'):
            self.consume()

    def test_duplicate_fields_rejected(self):
        self.rebind(b'{"actors":{},"actors":{}}')
        with self.assertRaisesRegex(ValueError, 'duplicate JSON field'):
            self.consume()

    def test_nonfinite_tokens_rejected(self):
        for token in (b'NaN', b'Infinity', b'-Infinity'):
            with self.subTest(token=token):
                self.rebind(b'{"actors":' + token + b'}')
                with self.assertRaisesRegex(ValueError, 'nonfinite JSON number'):
                    self.consume()

    def test_invalid_utf8_and_truncated_json_rejected(self):
        for raw in (b'{"actors":', b'\xff'):
            with self.subTest(raw=raw):
                self.rebind(raw)
                with self.assertRaisesRegex(ValueError, 'invalid strict JSON'):
                    self.consume()

    def test_rehashed_geometry_mutation_still_rejected(self):
        path, _ = self.produce()
        value = json.loads(path.read_bytes())
        value['actors'][self.n.ACTORS[0]]['vertices_local'][0][0] += 0.01
        self.rebind((json.dumps(value) + '\n').encode())
        with self.assertRaisesRegex(ValueError, 'frame1 geometry differs'):
            self.consume()

    def test_rehashed_binding_mutation_still_rejected(self):
        path, _ = self.produce()
        value = json.loads(path.read_bytes())
        value['binding']['candidate_id'] = 'other-candidate'
        self.rebind((json.dumps(value) + '\n').encode())
        with self.assertRaisesRegex(ValueError, 'fresh same-target frame1'):
            self.consume()

    def test_full_sampled_geometry_bytes_still_checked(self):
        self.produce()
        original = self.buffers
        from dataclasses import replace
        changed = replace(original, vertices=b'\0' + original.vertices[1:])
        self.assertNotEqual(changed, original)
        self.e['geometry'] = lambda name, graph: (self.vertices, original if self.clock.frame == 1. else changed)
        with self.assertRaisesRegex(ValueError, 'rigid full float64/topology bytes changed'):
            self.consume()

    def test_full_sampled_topology_bytes_still_checked(self):
        self.produce()
        original = self.buffers
        from dataclasses import replace
        changed = replace(original, indices=original.indices[8:16] + original.indices[:8] + original.indices[16:])
        self.e['geometry'] = lambda name, graph: (self.vertices, original if self.clock.frame == 1. else changed)
        with self.assertRaisesRegex(ValueError, 'rigid full float64/topology bytes changed'):
            self.consume()

    def test_original_4240_and_offkey_contract_unchanged(self):
        self.assertEqual(self.cc.INVARIANTS['source_samples'], 4240)
        self.assertEqual(self.cc.INVARIANTS['runtime_chunks'], 67)
        self.assertEqual(len(self.cc.FOCUS), 9)
        self.assertEqual(sum(f * 256 != int(f * 256) for f in self.cc.FOCUS), 4)
        self.assertEqual(self.cc.INVARIANTS['matrix_position_strict_max'], 1e-4)
        self.assertEqual(self.cc.INVARIANTS['projection_strict_max'], 1e-5)
        self.assertNotIn('bpy', sys.modules)


if __name__ == '__main__':
    sys.path.insert(0, str(HERE))
    unittest.main(verbosity=2)
