"""Discriminating fixtures for the real city triangle-preservation CLI."""
import contextlib
import gzip
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

import verify_city_geometry as parity


def write_mesh(path, chunks, version, compressed=True):
    data = bytearray(f'RDCITY0{version}'.encode('ascii'))
    if version == 4:
        metadata = json.dumps([{'id': i, 'asset': 'original fixture'}
                               for i in range(len(chunks))]).encode('utf-8')
        data.extend(struct.pack('<II', 0, len(metadata)))
        data.extend(metadata)
    data.extend(struct.pack('<I', len(chunks)))
    for vertices, indices in chunks:
        vertices = np.asarray(vertices, dtype='<f4')
        data.extend(struct.pack('<6fII', *vertices[:, :3].min(axis=0), *vertices[:, :3].max(axis=0),
                                len(vertices), len(indices)))
        data.extend(vertices.tobytes())
        data.extend(np.asarray(indices, dtype='<u4' if version == 4 else '<u2').tobytes())
    path.write_bytes(gzip.compress(data, mtime=0) if compressed else data)


class CityGeometryParityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.baseline, self.candidate = self.root / 'old.bin', self.root / 'new.bin'
        self.vertices = np.asarray([[*p, 0, 0, 1, .25, .5, .75, 1]
                                    for p in ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0))], dtype='<f4')
        self.indices = [0, 1, 2, 0, 2, 3]
        write_mesh(self.baseline, [(self.vertices, self.indices)], 1)

    def rebatched(self):
        # Reverse triangle order and split the shared vertices across records.
        return [(self.vertices[[0, 2, 3]].copy(), [0, 1, 2]),
                (self.vertices[[0, 1, 2]].copy(), [0, 1, 2])]

    def test_rebatched_reordered_geometry_preserves_exact_triangle_multiset(self):
        write_mesh(self.candidate, self.rebatched(), 4, compressed=False)
        result = parity.compare_city_geometry(self.baseline, self.candidate)
        self.assertTrue(result['passed'])
        self.assertFalse(result['vertex_count_equal'])
        self.assertEqual(result['baseline']['triangles'], 2)
        self.assertEqual(result['baseline']['sorted_triangle_hashes_sha256'],
                         result['candidate']['sorted_triangle_hashes_sha256'])

    def test_changed_winding_color_normal_or_triangle_multiplicity_fails(self):
        changes = ('winding', 'color', 'normal', 'multiplicity')
        for change in changes:
            with self.subTest(change=change):
                chunks = self.rebatched()
                if change == 'winding':
                    chunks[0] = (chunks[0][0], [0, 2, 1])
                elif change == 'color':
                    chunks[0][0][0, 6] = .125
                elif change == 'normal':
                    chunks[0][0][0, 3:6] = [0, 1, 0]
                else:
                    chunks.append(chunks[0])
                write_mesh(self.candidate, chunks, 4)
                self.assertFalse(parity.compare_city_geometry(self.baseline, self.candidate)['passed'])

    def test_cli_writes_success_and_failure_reports(self):
        report = self.root / 'reports/parity.json'
        write_mesh(self.candidate, self.rebatched(), 4)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(parity.main([str(self.baseline), str(self.candidate), '--report', str(report)]), 0)
        self.assertTrue(json.loads(report.read_text())['passed'])
        self.candidate.write_bytes(b'bad geometry')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(parity.main([str(self.baseline), str(self.candidate), '--report', str(report)]), 1)
        self.assertFalse(json.loads(report.read_text())['passed'])
        self.assertIn('error', json.loads(report.read_text()))

    def test_directory_check_preserves_original_fields_but_allows_added_metadata(self):
        old, new = self.root / 'old', self.root / 'new'
        old.mkdir()
        new.mkdir()
        write_mesh(old / 'meshes.bin', [(self.vertices, self.indices)], 1)
        write_mesh(new / 'meshes.bin', self.rebatched(), 4)
        level = {'colliders': [{'min': [0, 0, 0], 'max': [1, 1, 1]}],
                 'buildings': [{'id': 'B01', 'name': 'fixture'}],
                 'spawn': {'position': [0, 0, 0], 'yaw_degrees': 0},
                 'supply_position': [1, 0, 0], 'landmarks': [],
                 'bounds': {'min': [0, 0, 0], 'max': [1, 1, 1]}}
        layout = {'buildings': level['buildings'], 'instances': [{'asset': 'fixture', 'position': [0, 0, 0]}]}
        for folder in (old, new):
            (folder / 'level.json').write_text(json.dumps(level))
            (folder / 'layout.json').write_text(json.dumps(layout))
        layout['instances'][0]['id'] = 14
        (new / 'layout.json').write_text(json.dumps(layout))
        self.assertTrue(parity.compare_city_geometry(old, new)['passed'])
        level['colliders'][0]['max'][1] = 2
        (new / 'level.json').write_text(json.dumps(level))
        result = parity.compare_city_geometry(old, new)
        self.assertTrue(result['placement_metadata_checked'])
        self.assertFalse(result['passed'])
        self.assertFalse(result['checks']['original_level_colliders_fields_equal'])


if __name__ == '__main__':
    unittest.main()
