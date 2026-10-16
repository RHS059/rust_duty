import csv
import json
import hashlib
from pathlib import Path
import unittest

ROOT = Path(__file__).parent


class UploadedInventory(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((ROOT / 'uploaded_references_inventory.json').read_text())

    def test_six_pinned_sources_and_complete_observed_pts(self):
        entries = self.catalog['sources']
        self.assertEqual([s['id'] for s in entries], [f'U{i}' for i in range(1, 7)])
        self.assertEqual(sum(s['decoded_frame_count'] for s in entries), 14017)
        for s in entries:
            self.assertEqual(s['source_commit'], 'e14e5f7b14216f2e90ea8791a0b58c65638ea7a6')
            self.assertEqual(len(s['sha256']), 64)
            with (ROOT / s['frame_pts_csv']).open() as f:
                rows = list(csv.DictReader(f))
            n = s['decoded_frame_count']
            self.assertEqual(len(rows), n)
            self.assertEqual([(int(r['source_frame']), int(r['pts_ticks']), r['time_base']) for r in rows],
                             [(i, i * 256, '1/15360') for i in range(n)])
            probe = json.loads((ROOT / s['native_probe']).read_text())
            self.assertEqual(probe['decoded_frame_count'], n)
            self.assertEqual(probe['stream']['duration_ts'], n * 256)
            self.assertEqual(s['end_pts_ticks_exclusive'], n * 256)

    def test_coarse_windows_partition_source_without_claiming_cuts(self):
        for s in self.catalog['sources']:
            cursor = 0
            for w in s['catalog_windows']:
                self.assertEqual(w['start_frame'], cursor)
                self.assertGreater(w['end_frame_exclusive'], cursor)
                self.assertEqual(w['kind'], 'coarse search window, not action cut')
                cursor = w['end_frame_exclusive']
            self.assertEqual(cursor, s['decoded_frame_count'])

    def test_every_native_overlap_comparison_is_recorded(self):
        overlap = json.loads((ROOT / 'uploaded/decoded_pixel_overlap.json').read_text())
        self.assertEqual(len(overlap['comparisons']), 18)
        self.assertEqual({(r['uploaded_source_id'], r['prior_source_id']) for r in overlap['comparisons']},
                         {(f'U{i}', f'R{j}') for i in range(1, 7) for j in range(1, 4)})
        for row in overlap['comparisons']:
            self.assertEqual(row['exact_equal_decoded_frame_count'], 0)
            self.assertEqual(row['matching_frame_pairs'], [])

    def test_prone_handoff_matches_sidecars_and_keeps_seams_provisional(self):
        handoff = json.loads((ROOT / 'prone_source_handoff.json').read_text())
        self.assertEqual(len(handoff['clips']), 4)
        for row in handoff['clips']:
            data = (ROOT / row['verification_sidecar']).read_bytes()
            self.assertEqual(row['verification_sidecar_sha256'], hashlib.sha256(data).hexdigest())
            side = json.loads(data)
            self.assertEqual(row['cut_sha256'], side['sha256'])
            self.assertEqual(row['start_frame'], side['start_frame'])
            self.assertEqual(row['end_frame_exclusive'], side['end_frame_exclusive'])
            self.assertFalse(row['exact_outer_endpoints_are_loop_seams'])
            eligibility = row['cycle_eligibility']
            for a, b in eligibility.get('native_neighborhoods_inspected_half_open', []):
                self.assertLessEqual(row['start_frame'], a)
                self.assertLess(a, b)
                self.assertLessEqual(b, row['end_frame_exclusive'])
            if row['direction'] == 'left':
                self.assertEqual(row['frame_count'], 55)
                self.assertTrue(eligibility['status'].startswith('segment-only'))


if __name__ == '__main__':
    unittest.main()
