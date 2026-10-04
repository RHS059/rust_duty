import copy
import hashlib
import json
import unittest
from pathlib import Path

import cut_reference as cut


class CutContract(unittest.TestCase):
    def test_half_open_bounds(self):
        self.assertEqual(cut.validate_cut({'start_frame': 10, 'end_frame_exclusive': 20}, 30), (10, 20))
        for a, b in [(3, 3), (-1, 5), (0, 31), (4, 1)]:
            with self.assertRaises(ValueError):
                cut.validate_cut({'start_frame': a, 'end_frame_exclusive': b}, 30)

    def test_pts_rejects_missing_last_decoded_frame(self):
        probe = {'streams': [{'time_base': '1/15360', 'avg_frame_rate': '60/1', 'duration_ts': 1024}],
                 'frames': [{'pts': x} for x in [0, 256, 512, 768]]}
        self.assertEqual(cut.validate_pts(probe, 4), [0, 256, 512, 768])
        missing = copy.deepcopy(probe)
        missing['frames'].pop()
        with self.assertRaises(ValueError):
            cut.validate_pts(missing, 4)

    def test_pts_rejects_wrong_final_duration_or_gap(self):
        probe = {'streams': [{'time_base': '1/15360', 'avg_frame_rate': '60/1', 'duration_ts': 768}],
                 'frames': [{'pts': x} for x in [0, 256, 512, 768]]}
        with self.assertRaises(ValueError):
            cut.validate_pts(probe, 4)
        probe['streams'][0]['duration_ts'] = 1024
        probe['frames'][2]['pts'] = 513
        with self.assertRaises(ValueError):
            cut.validate_pts(probe, 4)

    def test_prior149_preserved_exactly(self):
        here = Path(__file__).parent
        b = (here / 'prior/reference_annotation.json').read_bytes()
        self.assertEqual(hashlib.sha256(b).hexdigest(),
                         '490fbf8c2177ac45c0d59c651d7821ca813f9bfab9061c784bace8ef0e788122')
        p = json.loads(b)
        rows = [row for source in p['source_annotations'].values()
                for row in source.get('segments', source.get('intervals', []))]
        self.assertEqual(len(rows), 149)
        manifest = json.loads((here / 'source_map.json').read_text())
        preserved = manifest['prior_interval_refinement_status']
        self.assertEqual(len(preserved), 149)
        self.assertEqual([r['original_interval_sha256'] for r in preserved],
                         [hashlib.sha256(json.dumps(r, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                          for r in rows])

    def test_selected_excerpt_inclusive_end_is_explicit(self):
        p = json.loads((Path(__file__).parent / 'prior/reference_annotation.json').read_text())
        ranges = p['source_annotations']['5KM0XSKxTWw']['selected_excerpts']
        # The historical selected-excerpt table is not a half-open timeline.
        for row in ranges:
            if row.get('id') == 'GROUND_CRAWL_FORWARD':
                self.assertEqual(row['end_frame_inclusive'] + 1, 5173)
                break
        else:
            self.assertTrue(any('end_frame_inclusive' in row for row in ranges))

    def test_manifest_clips_have_exact_native_bounds(self):
        m = json.loads((Path(__file__).parent / 'source_map.json').read_text())
        ids = set()
        for row in m['clips']:
            self.assertNotIn(row['id'], ids)
            ids.add(row['id'])
            a, b = cut.validate_cut(row, m['sources'][row['source_id']]['frame_count'])
            self.assertEqual(row['start_pts_ticks'], a * 256)
            self.assertEqual(row['end_pts_ticks_exclusive'], b * 256)
            self.assertEqual(row['duration_frames'], b - a)


if __name__ == '__main__':
    unittest.main()
