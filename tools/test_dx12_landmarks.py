"""Synthetic fixtures only; never evidence of a native Windows DX12 capture.

Positive fixtures carry explicit reviewer-measured coordinates. Negative fixtures
prove that missing, non-finite, out-of-bounds, ambiguous, overlay-derived or
mis-identified inputs keep the landmark review open, and that unmeasurable or
uncertain landmarks are never accepted.
"""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw

import review_dx12_landmarks as landmarks

ADS = 'ads-rear-aperture-center'
HIP = 'hip-front-sight-guard'
COMMIT = 'faeb58d3a7cbd5c98d563c27d78d8511a439d7ca'


def synthetic_frame(size=(960, 540), aperture=(481, 271), guard=(527, 281)):
    """Reference clear color with drawn stand-ins for the two features."""
    image = Image.new('RGBA', size, (36, 48, 61, 255))
    draw = ImageDraw.Draw(image)
    x, y = aperture
    draw.ellipse((x - 25, y - 25, x + 25, y + 25), outline=(20, 20, 20, 255), width=6)
    x, y = guard
    draw.rectangle((x - 3, y - 9, x + 3, y + 9), fill=(15, 15, 15, 255))
    return image


def png_bytes(image, fmt='PNG'):
    output = io.BytesIO()
    image.save(output, format=fmt)
    return output.getvalue()


def sha(data):
    return hashlib.sha256(data).hexdigest()


class LandmarkReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.review_dir = self.root / 'review'
        self.review_dir.mkdir()
        self.hip_png = png_bytes(synthetic_frame())
        self.ads_png = png_bytes(synthetic_frame(aperture=(479, 268)))
        (self.review_dir / 'dx12-hip-raw.png').write_bytes(self.hip_png)
        (self.review_dir / 'dx12-ads-raw.png').write_bytes(self.ads_png)

    def entry(self, landmark, point, image=None, data=None, **changes):
        pose = landmarks.LANDMARKS[landmark]['pose']
        image = image or f'review/dx12-{pose}-raw.png'
        data = data if data is not None else (self.ads_png if pose == 'ads' else self.hip_png)
        value = {
            'image': image, 'image_sha256': sha(data), 'image_size': [960, 540],
            'frame': {'source_frame': '0012.png' if pose == 'hip' else '0040.png',
                      'backend': 'dx12', 'pose': pose},
            'landmark': landmark, 'outcome': 'measured', 'measured_center': point,
            'reviewer': 'Synthetic Reviewer',
            'provenance': {'method': 'manual-raw-pixel', 'tool': 'synthetic fixture coordinates',
                           'image_role': 'raw', 'measured_at': '2026-10-05T16:30:00Z'},
            'target_values_not_used': True,
        }
        value.update(changes)
        return value

    def document(self, *entries):
        return {'schema': landmarks.MEASUREMENT_SCHEMA,
                'evidence': {'repository': 'RHS059/rust_duty', 'run_id': '1',
                             'run_attempt': '1', 'source_commit': COMMIT},
                'measurements': list(entries)}

    def valid(self):
        return self.document(self.entry(ADS, [479, 268]), self.entry(HIP, [527, 281]))

    def run_review(self, document, **kwargs):
        return landmarks.review(document, self.root, **kwargs)

    def assert_invalid(self, document, fragment, **kwargs):
        report = self.run_review(document, **kwargs)
        self.assertEqual(report['status'], 'invalid', report)
        self.assertEqual(report['automated_landmark_gate'], 'open')
        self.assertFalse(report['acceptance_complete'])
        self.assertTrue(any(fragment in error for error in report['errors']), report['errors'])
        return report

    def assert_human_gates_open(self, report):
        self.assertEqual(report['human_m2_approval'], 'open')
        self.assertEqual(report['human_m4_approval'], 'open')
        self.assertFalse(report['acceptance_complete'])

    # Positive fixtures -------------------------------------------------------

    def test_explicit_measurements_within_tolerance(self):
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.review_dir.iterdir()}
        report = self.run_review(self.valid())
        self.assertEqual(report['status'], 'within-tolerance', report)
        self.assertEqual(report['automated_landmark_gate'], 'measured-within-tolerance')
        self.assert_human_gates_open(report)
        deltas = {r['landmark']: r['delta'] for r in report['results']}
        self.assertEqual((deltas[ADS]['dx'], deltas[ADS]['dy']), (-1.0, -2.0))
        self.assertEqual((deltas[HIP]['dx'], deltas[HIP]['dy']), (1.0, 1.0))
        after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.review_dir.iterdir()}
        self.assertEqual(before, after, 'raw images must stay untouched')

    def test_four_pixel_boundary_is_inclusive_and_subpixel_beyond_fails(self):
        report = self.run_review(self.document(self.entry(ADS, [484, 266]),
                                               self.entry(HIP, [522.0, 284.0])))
        self.assertEqual(report['status'], 'within-tolerance', report)
        report = self.run_review(self.document(self.entry(ADS, [484.01, 270.5]),
                                               self.entry(HIP, [527, 281])))
        self.assertEqual(report['status'], 'outside-tolerance')
        self.assertEqual(report['automated_landmark_gate'], 'failed')
        self.assert_human_gates_open(report)

    def test_per_axis_tolerance_not_only_euclidean(self):
        report = self.run_review(self.document(self.entry(ADS, [480, 275]),
                                               self.entry(HIP, [527, 281])))
        self.assertEqual(report['status'], 'outside-tolerance')

    # Unaccepted outcomes ----------------------------------------------------

    def test_unmeasurable_and_uncertain_stay_unaccepted(self):
        for outcome in ('unmeasurable', 'uncertain'):
            hip = self.entry(HIP, None, outcome=outcome, reason='guard occluded by hand')
            del hip['measured_center']
            report = self.run_review(self.document(self.entry(ADS, [479, 268]), hip))
            self.assertEqual(report['status'], 'open', report)
            self.assertEqual(report['automated_landmark_gate'], 'open')
            result = next(r for r in report['results'] if r['landmark'] == HIP)
            self.assertFalse(result['accepted'])
            self.assertIsNone(result['measured_center'])
            self.assertEqual(result['status'], f'unaccepted-{outcome}')

    def test_uncertain_entry_with_coordinates_is_ambiguous(self):
        hip = self.entry(HIP, [527, 281], outcome='uncertain', reason='maybe')
        self.assert_invalid(self.document(self.entry(ADS, [479, 268]), hip), 'must not carry')

    def test_unmeasurable_needs_reason(self):
        hip = self.entry(HIP, None, outcome='unmeasurable')
        self.assert_invalid(self.document(self.entry(ADS, [479, 268]), hip), 'reason')

    def test_explicit_zero_error_measurements_are_within_tolerance(self):
        # Known synthetic feature locations are explicit measurements, not values
        # filled in by the validator. These files are not native evidence.
        self.ads_png = png_bytes(synthetic_frame(aperture=(480, 270)))
        self.hip_png = png_bytes(synthetic_frame(guard=(526, 280)))
        (self.review_dir / 'dx12-ads-raw.png').write_bytes(self.ads_png)
        (self.review_dir / 'dx12-hip-raw.png').write_bytes(self.hip_png)
        report = self.run_review(self.document(self.entry(ADS, [480, 270]),
                                               self.entry(HIP, [526, 280])))
        self.assertEqual(report['status'], 'within-tolerance', report)
        self.assertEqual(report['automated_landmark_gate'], 'measured-within-tolerance')
        for result in report['results']:
            self.assertEqual(result['delta'], {'dx': 0.0, 'dy': 0.0, 'euclidean': 0.0})
            self.assertEqual(result['status'], 'within-tolerance')
            self.assertTrue(result['accepted'])
        self.assert_human_gates_open(report)

    def test_zero_error_does_not_bypass_declared_measurement_requirements(self):
        for changes, message in (
                ({'target_values_not_used': False}, 'target_values_not_used'),
                ({'measured_center': None}, 'needs measured_center')):
            with self.subTest(changes=changes):
                ads = self.entry(ADS, [480, 270], **changes)
                self.assert_invalid(self.document(ads, self.entry(HIP, [526, 280])), message)
        ads = self.entry(ADS, [480, 270])
        ads['provenance']['method'] = 'copied-calibration-target'
        self.assert_invalid(self.document(ads, self.entry(HIP, [526, 280])), 'is not a raw-pixel measurement')

    def test_missing_required_landmark_stays_open(self):
        report = self.run_review(self.document(self.entry(ADS, [479, 268])))
        self.assertEqual(report['status'], 'open')
        self.assertEqual(report['missing'], [f'dx12 {HIP}'])

    def test_required_legacy_backend(self):
        report = self.run_review(self.valid(), require_backends=('dx12', 'legacy'))
        self.assertEqual(report['status'], 'open')
        self.assertEqual(len(report['missing']), 2)

    # Missing / non-finite / out-of-bounds -----------------------------------

    def test_measured_without_center_never_substitutes_target(self):
        ads = self.entry(ADS, None)
        self.assert_invalid(self.document(ads, self.entry(HIP, [527, 281])), 'never substituted')
        del ads['measured_center']
        report = self.assert_invalid(self.document(ads, self.entry(HIP, [527, 281])),
                                     'needs measured_center')
        self.assertTrue(all(r['measured_center'] != [480, 270] for r in report['results']))

    def test_non_finite_json_is_rejected_at_parse(self):
        for literal in ('NaN', 'Infinity', '-Infinity'):
            path = self.root / f'{literal}.json'
            text = json.dumps(self.valid()).replace('[479, 268]', f'[{literal}, 268]')
            path.write_text(text, encoding='utf-8')
            with self.assertRaisesRegex(landmarks.ReviewError, 'non-finite'):
                landmarks.load_json(path)

    def test_non_finite_python_values_are_rejected(self):
        for value in (float('nan'), float('inf')):
            self.assert_invalid(self.document(self.entry(ADS, [value, 268])), 'finite')

    def test_non_numeric_coordinates_are_rejected(self):
        for point in (['479', 268], [True, 268], [479, None], {'x': 479, 'y': 268}):
            self.assert_invalid(self.document(self.entry(ADS, point)), 'measured_center')

    def test_out_of_bounds_coordinates_are_rejected(self):
        for point in ([960, 270], [-0.5, 270], [480, 540], [480, -1], [959.5, 10]):
            self.assert_invalid(self.document(self.entry(ADS, point)), 'outside the 960x540')

    def test_multiple_candidates_are_ambiguous(self):
        for point in ([[479, 268], [481, 270]], [479, 268, 0], [479]):
            self.assert_invalid(self.document(self.entry(ADS, point)), 'ambiguous')

    def test_duplicate_annotations_for_one_landmark_are_ambiguous(self):
        report = self.assert_invalid(
            self.document(self.entry(ADS, [479, 268]), self.entry(ADS, [479, 268]),
                          self.entry(HIP, [527, 281])), 'ambiguous: dx12 ' + ADS)
        self.assertEqual(report['automated_landmark_gate'], 'open')

    def test_one_image_claiming_two_frame_identities_is_ambiguous(self):
        other = self.entry(ADS, [479, 268])
        other['frame'] = dict(other['frame'], backend='legacy', source_frame='0041.png')
        self.assert_invalid(self.document(self.entry(ADS, [479, 268]), other,
                                          self.entry(HIP, [527, 281])), 'claims frame identities')

    def test_duplicate_json_keys_are_rejected(self):
        path = self.root / 'dup.json'
        path.write_text('{"schema": "a", "schema": "b"}', encoding='utf-8')
        with self.assertRaisesRegex(landmarks.ReviewError, 'duplicate JSON key'):
            landmarks.load_json(path)

    # Image identity -----------------------------------------------------------

    def test_sha_mismatch_is_rejected(self):
        ads = self.entry(ADS, [479, 268], image_sha256='0' * 64)
        self.assert_invalid(self.document(ads), 'does not match annotation')

    def test_scaled_or_wrong_extent_image_is_rejected(self):
        data = png_bytes(synthetic_frame(size=(1920, 1080)))
        (self.review_dir / 'big.png').write_bytes(data)
        ads = self.entry(ADS, [479, 268], image='review/big.png', data=data)
        self.assert_invalid(self.document(ads), 'not unscaled 960x540')
        self.assert_invalid(self.document(self.entry(ADS, [479, 268], image_size=[1920, 1080])),
                            'image_size')

    def test_non_png_is_rejected(self):
        data = png_bytes(synthetic_frame().convert('RGB'), 'JPEG')
        (self.review_dir / 'frame.png').write_bytes(data)
        # Framing runs before Pillow, so a JPEG named .png fails as not a PNG.
        self.assert_invalid(self.document(self.entry(ADS, [479, 268], image='review/frame.png',
                                                     data=data)), 'expected PNG format')
        (self.review_dir / 'broken.png').write_bytes(b'\x89PNG\r\n\x1a\nnope')
        self.assert_invalid(self.document(self.entry(ADS, [479, 268], image='review/broken.png',
                                                     data=b'\x89PNG\r\n\x1a\nnope')),
                            'framed PNG')

    def test_paths_outside_root_are_rejected(self):
        outside = self.root.parent / f'{self.root.name}-outside.png'
        outside.write_bytes(self.ads_png)
        self.addCleanup(outside.unlink)
        for image in (f'../{outside.name}', str(outside), 'review\\dx12-ads-raw.png'):
            self.assert_invalid(self.document(self.entry(ADS, [479, 268], image=image)),
                                'relative path inside')
        self.assert_invalid(self.document(self.entry(ADS, [479, 268], image='review/none.png')),
                            'not an existing regular file')

    def test_symlinked_image_is_rejected(self):
        link = self.review_dir / 'link.png'
        try:
            os.symlink(self.review_dir / 'dx12-ads-raw.png', link)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks unavailable on this runner')
        self.assert_invalid(self.document(self.entry(ADS, [479, 268], image='review/link.png')),
                            'symlink')

    # Provenance and overlays -----------------------------------------------

    def test_reviewer_and_provenance_are_required(self):
        for change in ({'reviewer': ''}, {'reviewer': None}, {'target_values_not_used': False}):
            self.assert_invalid(self.document(self.entry(ADS, [479, 268], **change)), '')
        ads = self.entry(ADS, [479, 268])
        del ads['provenance']['tool']
        self.assert_invalid(self.document(ads), 'missing')
        ads = self.entry(ADS, [479, 268])
        ads['provenance']['measured_at'] = '2026-10-05T16:30:00'
        self.assert_invalid(self.document(ads), 'timezone')
        doc = self.valid()
        doc['evidence']['source_commit'] = 'faeb58d'
        self.assert_invalid(doc, 'source_commit')

    def test_overlay_target_or_inferred_methods_are_rejected(self):
        for method in ('overlay', 'guide-box-center', 'calibration-target', 'projection',
                       'inferred-from-overlay', 'detector', 'raw-pixel'):
            ads = self.entry(ADS, [479, 268])
            ads['provenance']['method'] = method
            self.assert_invalid(self.document(ads), 'not a raw-pixel measurement')
        ads = self.entry(ADS, [479, 268])
        ads['provenance']['image_role'] = 'guide'
        self.assert_invalid(self.document(ads), 'image_role')

    def test_guide_overlay_files_are_rejected(self):
        guide = synthetic_frame()
        ImageDraw.Draw(guide).rectangle((476, 266, 484, 274), outline='#ffcf40')
        data = png_bytes(guide)
        (self.review_dir / 'dx12-ads-guide.png').write_bytes(data)
        self.assert_invalid(self.document(self.entry(ADS, [480, 270],
                                                     image='review/dx12-ads-guide.png', data=data)),
                            'guide overlay')
        # A renamed guide is still caught when the packet lists it.
        (self.review_dir / 'renamed.png').write_bytes(data)
        packet = self.packet()
        packet['records'][0]['guide'] = 'review/dx12-ads-guide.png'
        self.assert_invalid(self.document(self.entry(ADS, [481, 271], image='review/renamed.png',
                                                     data=data)), 'guide overlay', packet=packet)

    # Landmark and frame identity ------------------------------------------

    def test_landmark_identity_is_strict(self):
        for name, fragment in (('front-sight', 'unknown'),
                               ('hip-rear-aperture-center', '(~625,293)'),
                               ('ads-aiming-post', 'aiming post'), ('crosshair', 'crosshair')):
            ads = self.entry(ADS, [479, 268])
            ads['landmark'] = name
            self.assert_invalid(self.document(ads), fragment)
        hip_on_ads_frame = self.entry(HIP, [527, 281])
        hip_on_ads_frame['frame']['pose'] = 'ads'
        self.assert_invalid(self.document(hip_on_ads_frame), 'belongs to pose')

    def test_frame_identity_fields_are_strict(self):
        for change in ({'source_frame': 'frame.png'}, {'backend': 'vulkan'}):
            ads = self.entry(ADS, [479, 268])
            ads['frame'].update(change)
            self.assert_invalid(self.document(ads), 'frame')
        ads = self.entry(ADS, [479, 268])
        ads['frame']['adapter'] = 'WARP'
        self.assert_invalid(self.document(ads), 'unknown fields')
        self.assert_invalid(self.document(self.entry(ADS, [479, 268], extra=1)), 'unknown fields')

    def packet(self):
        def record(pose, feature, center, data, frame):
            return {'backend': 'dx12', 'pose': pose, 'source_frame': frame,
                    'raw': f'dx12-{pose}-raw.png', 'raw_sha256': sha(data),
                    'guide': f'dx12-{pose}-guide.png', 'feature': feature,
                    'calibrated_center': center, 'tolerance_px': 4,
                    'measured_center': None, 'projected_center': None}
        return {'status': 'open', 'automated_landmark_gate': 'open',
                'records': [record('ads', 'rear-aperture center', [480, 270], self.ads_png,
                                   '0040.png'),
                            record('hip', 'front-sight guard', [526, 280], self.hip_png,
                                   '0012.png')]}

    def test_packet_cross_check(self):
        report = self.run_review(self.valid(), packet=self.packet())
        self.assertEqual(report['status'], 'within-tolerance', report)
        self.assert_human_gates_open(report)
        packet = self.packet()
        packet['records'][1]['source_frame'] = '0013.png'
        self.assert_invalid(self.valid(), 'source_frame', packet=packet)
        packet = self.packet()
        del packet['records'][0]
        self.assert_invalid(self.valid(), 'not a raw record', packet=packet)
        packet = self.packet()
        packet['records'][0]['calibrated_center'] = [481, 270]
        self.assert_invalid(self.valid(), 'calibrated_center', packet=packet)

    MISSING = object()

    def write_sequence(self, folder, backend='Dx12', hip_route='ready', ads=1,
                       metadata=None, hip_ads=0.0, ads_ads=1.0, ads_gameplay=None,
                       ads_gameplay_text=None, pngs=None):
        folder.mkdir()
        hip_png, ads_png = pngs or (self.hip_png, self.ads_png)
        stationary = {'route': 'ads.hold', 'simulation_ads': ads, 'run_weight': 0, 'speed': 0}
        for key, value in (ads_gameplay or {}).items():
            if value is self.MISSING:
                stationary.pop(key, None)
            else:
                stationary[key] = value
        for name, data, gameplay, pose_ads in (
                ('0012.png', hip_png, {'route': hip_route}, hip_ads),
                ('0040.png', ads_png, stationary, ads_ads)):
            (folder / name).write_bytes(data)
            side = {'backend': backend, 'width': 960, 'height': 540, 'ads': pose_ads}
            if metadata:
                side.update(metadata)
            (folder / f'{name}.json').write_text(json.dumps(side), encoding='utf-8')
            text = json.dumps(gameplay)
            if name == '0040.png' and ads_gameplay_text is not None:
                text = ads_gameplay_text
            (folder / f'{name}.gameplay.json').write_text(text, encoding='utf-8')

    def test_frame_source_ties_bytes_and_telemetry(self):
        self.write_sequence(self.root / 'captures')
        frames = {'dx12': self.root / 'captures'}
        report = self.run_review(self.valid(), frames=frames)
        self.assertEqual(report['status'], 'within-tolerance', report)
        for name, kwargs, fragment in (('wrong-backend', {'backend': 'OpenGl'}, 'backend'),
                                       ('not-ready', {'hip_route': 'walk'}, 'route'),
                                       ('partial-ads', {'ads': 0.5}, 'simulation_ads')):
            self.write_sequence(self.root / name, **kwargs)
            self.assert_invalid(self.valid(), fragment, frames={'dx12': self.root / name})
        swapped = self.root / 'swapped'
        self.write_sequence(swapped)
        (swapped / '0012.png').write_bytes(self.ads_png)
        self.assert_invalid(self.valid(), 'not byte-identical', frames={'dx12': swapped})
        (self.root / 'captures' / '0012.png.gameplay.json').unlink()
        self.assert_invalid(self.valid(), 'missing sidecar', frames=frames)

    def test_frames_require_stationary_fully_held_ads(self):
        """ADS binds only to the harness's stationary fully held selection.

        Integer and float zero run_weight/speed (and 1 / 1.0 simulation_ads) are
        positive controls; missing, null, boolean, string, nonfinite and nonzero
        values keep the review invalid, matching run_dx12_authored.py.
        """
        for index, values in enumerate(({'run_weight': 0, 'speed': 0},
                                        {'run_weight': 0.0, 'speed': -0.0, 'simulation_ads': 1.0})):
            folder = self.root / f'stationary-{index}'
            self.write_sequence(folder, ads_gameplay=values)
            report = self.run_review(self.valid(), frames={'dx12': folder})
            self.assertEqual(report['status'], 'within-tolerance', report)
            self.assert_human_gates_open(report)
        cases = []
        for key in ('run_weight', 'speed'):
            cases += [(f'{key}-missing', {key: self.MISSING}, f'missing {key}'),
                      (f'{key}-null', {key: None}, key),
                      (f'{key}-false', {key: False}, key),
                      (f'{key}-true', {key: True}, key),
                      (f'{key}-string', {key: '0'}, key),
                      (f'{key}-list', {key: [0]}, key),
                      (f'{key}-moving', {key: 0.25}, key),
                      (f'{key}-negative', {key: -1}, key),
                      (f'{key}-tiny', {key: 1e-9}, key),
                      (f'{key}-overflow-int', {key: 10 ** 400}, 'finite float range')]
        cases += [('simulation_ads-missing', {'simulation_ads': self.MISSING},
                   'missing simulation_ads'),
                  ('simulation_ads-true', {'simulation_ads': True}, 'simulation_ads')]
        for name, values, fragment in cases:
            folder = self.root / name
            self.write_sequence(folder, ads_gameplay=values)
            with self.subTest(case=name):
                self.assert_invalid(self.valid(), fragment, frames={'dx12': folder})
        # Nonfinite values: 1e400 parses to inf; NaN/Infinity literals are refused at parse.
        stationary = '{"route": "ads.hold", "simulation_ads": 1, "run_weight": %s, "speed": %s}'
        for name, text, fragment in (
                ('run_weight-inf', stationary % ('1e400', '0'), 'run_weight'),
                ('speed-neg-inf', stationary % ('0', '-1e400'), 'speed'),
                ('run_weight-nan', stationary % ('NaN', '0'), 'NaN'),
                ('speed-infinity', stationary % ('0', 'Infinity'), 'Infinity')):
            folder = self.root / name
            self.write_sequence(folder, ads_gameplay_text=text)
            with self.subTest(case=name):
                self.assert_invalid(self.valid(), fragment, frames={'dx12': folder})

    def test_stationary_ads_gate_holds_for_required_legacy_frames(self):
        legacy_hip = png_bytes(synthetic_frame(guard=(526, 280)))
        legacy_ads = png_bytes(synthetic_frame(aperture=(480, 270)))
        (self.review_dir / 'legacy-hip-raw.png').write_bytes(legacy_hip)
        (self.review_dir / 'legacy-ads-raw.png').write_bytes(legacy_ads)

        def legacy(landmark, point):
            pose = landmarks.LANDMARKS[landmark]['pose']
            item = self.entry(landmark, point, image=f'review/legacy-{pose}-raw.png',
                              data=legacy_ads if pose == 'ads' else legacy_hip)
            item['frame'] = dict(item['frame'], backend='legacy')
            return item

        document = self.document(self.entry(ADS, [479, 268]), self.entry(HIP, [527, 281]),
                                 legacy(ADS, [479, 268]), legacy(HIP, [527, 281]))
        self.write_sequence(self.root / 'dx12-ok')
        self.write_sequence(self.root / 'legacy-ok', backend='OpenGl',
                            pngs=(legacy_hip, legacy_ads))
        report = self.run_review(document, require_backends=('dx12', 'legacy'),
                                 frames={'dx12': self.root / 'dx12-ok',
                                         'legacy': self.root / 'legacy-ok'})
        self.assertEqual(report['status'], 'within-tolerance', report)
        self.assert_human_gates_open(report)
        self.write_sequence(self.root / 'legacy-moving', backend='OpenGl',
                            ads_gameplay={'speed': 3.5}, pngs=(legacy_hip, legacy_ads))
        self.assert_invalid(document, 'speed', require_backends=('dx12', 'legacy'),
                            frames={'dx12': self.root / 'dx12-ok',
                                    'legacy': self.root / 'legacy-moving'})

    # Aella follow-up probes (2026-10-05) ----------------------------------------

    def test_frames_reject_raw_and_wrongly_typed_target_metadata(self):
        """Raw-associated sidecars and mistyped flags must not measure-within-tolerance.

        Opaque-display metadata remains a valid positive control. String "true"
        for diagnostic_raw_target and string "1" for ads / simulation_ads are
        rejected; typed raw/display, actual-backend, and numeric-ADS controls
        cover the accepted and rejected shapes.
        """
        display = {
            'diagnostic_raw_target': False,
            'alpha_representation': landmarks.DISPLAY_ALPHA,
        }
        self.write_sequence(self.root / 'display', metadata=display)
        frames = {'dx12': self.root / 'display'}
        report = self.run_review(self.valid(), frames=frames)
        self.assertEqual(report['status'], 'within-tolerance', report)
        self.assertEqual(report['automated_landmark_gate'], 'measured-within-tolerance')
        self.assert_human_gates_open(report)

        # Typed raw target metadata: boolean true plus raw alpha label.
        self.write_sequence(self.root / 'raw-flag', metadata={
            'diagnostic_raw_target': True,
            'alpha_representation': landmarks.RAW_ALPHA,
        })
        self.assert_invalid(self.valid(), 'diagnostic_raw_target',
                            frames={'dx12': self.root / 'raw-flag'})

        # Typed raw alpha label alone (even with diagnostic_raw_target false).
        self.write_sequence(self.root / 'raw-alpha', metadata={
            'diagnostic_raw_target': False,
            'alpha_representation': landmarks.RAW_ALPHA,
        })
        self.assert_invalid(self.valid(), 'raw-associated-emissive-rgba8',
                            frames={'dx12': self.root / 'raw-alpha'})

        # Wrongly typed: string "true" for diagnostic_raw_target.
        self.write_sequence(self.root / 'string-true', metadata={
            'diagnostic_raw_target': 'true',
            'alpha_representation': landmarks.DISPLAY_ALPHA,
        })
        self.assert_invalid(self.valid(), 'JSON boolean',
                            frames={'dx12': self.root / 'string-true'})

        # Wrongly typed: string "1" for numeric ads in the capture sidecar.
        self.write_sequence(self.root / 'string-ads', metadata=display, hip_ads='1')
        self.assert_invalid(self.valid(), 'must be a JSON number',
                            frames={'dx12': self.root / 'string-ads'})

        # Wrongly typed: string "1" for simulation_ads in gameplay telemetry.
        self.write_sequence(self.root / 'string-sim-ads', metadata=display, ads='1')
        self.assert_invalid(self.valid(), 'simulation_ads',
                            frames={'dx12': self.root / 'string-sim-ads'})

        # Actual-backend control still rejects non-Dx12 for the dx12 backend.
        self.write_sequence(self.root / 'gl-backend', backend='OpenGl', metadata=display)
        self.assert_invalid(self.valid(), 'backend',
                            frames={'dx12': self.root / 'gl-backend'})

        # Numeric-ADS control: wrong numeric ads for the pose is rejected.
        self.write_sequence(self.root / 'wrong-ads', metadata=display, hip_ads=1.0)
        self.assert_invalid(self.valid(), 'ads=',
                            frames={'dx12': self.root / 'wrong-ads'})

    def write_siblings(self, metadata):
        for pose in ('hip', 'ads'):
            side = {'backend': 'Dx12', 'width': 960, 'height': 540,
                    'ads': 1.0 if pose == 'ads' else 0.0}
            side.update(metadata)
            (self.review_dir / f'dx12-{pose}-raw.png.json').write_text(json.dumps(side),
                                                                       encoding='utf-8')

    def test_sibling_sidecar_is_checked_without_frames(self):
        """An annotated PNG's own <image>.json gets the typed raw/display checks.

        Without --frames, a sibling marked diagnostic_raw_target=true with the
        raw-associated alpha label must not measure-within-tolerance; an opaque
        display sibling stays a valid control. Source-frame identity checks still
        apply when --frames is supplied.
        """
        self.write_siblings({'diagnostic_raw_target': False,
                             'alpha_representation': landmarks.DISPLAY_ALPHA})
        report = self.run_review(self.valid())
        self.assertEqual(report['status'], 'within-tolerance', report)
        self.assertEqual(report['automated_landmark_gate'], 'measured-within-tolerance')
        self.assert_human_gates_open(report)

        self.write_siblings({'diagnostic_raw_target': True,
                             'alpha_representation': landmarks.RAW_ALPHA})
        self.assert_invalid(self.valid(), 'dx12-hip-raw.png.json marks diagnostic_raw_target=true')
        self.assert_invalid(self.valid(), 'dx12-ads-raw.png.json marks diagnostic_raw_target=true')

        self.write_siblings({'diagnostic_raw_target': 'true',
                             'alpha_representation': landmarks.DISPLAY_ALPHA})
        self.assert_invalid(self.valid(), 'JSON boolean')

        # A raw sibling is still rejected when --frames points at a clean display
        # sequence, and the frames identity check still runs alongside it.
        self.write_siblings({'diagnostic_raw_target': True,
                             'alpha_representation': landmarks.RAW_ALPHA})
        self.write_sequence(self.root / 'clean', metadata={
            'diagnostic_raw_target': False, 'alpha_representation': landmarks.DISPLAY_ALPHA})
        self.assert_invalid(self.valid(), 'diagnostic_raw_target',
                            frames={'dx12': self.root / 'clean'})
        self.write_siblings({'diagnostic_raw_target': False,
                             'alpha_representation': landmarks.DISPLAY_ALPHA})
        report = self.run_review(self.valid(), frames={'dx12': self.root / 'clean'})
        self.assertEqual(report['status'], 'within-tolerance', report)
        (self.root / 'clean' / '0040.png').write_bytes(self.hip_png)
        self.assert_invalid(self.valid(), 'not byte-identical',
                            frames={'dx12': self.root / 'clean'})

    def test_landmark_list_and_overflow_coordinates_are_invalid_reports(self):
        """landmark:[] and 10**400 must become documented invalid reports, not crashes."""
        doc = self.valid()
        doc['measurements'][0]['landmark'] = []
        report = self.assert_invalid(doc, 'must be a string landmark id')
        self.assertEqual(report['status'], 'invalid')
        self.assertFalse(report['acceptance_complete'])
        self.assert_human_gates_open(report)

        doc = self.valid()
        doc['measurements'][0]['measured_center'] = [10 ** 400, 268]
        report = self.assert_invalid(doc, 'finite float range')
        self.assertEqual(report['status'], 'invalid')
        self.assert_human_gates_open(report)

        # CLI path: exit 2, invalid report on stdout, no uncaught Type/OverflowError.
        path = self.root / 'overflow.json'
        path.write_text(json.dumps(doc), encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = landmarks.main(['review', str(path), '--root', str(self.root)])
        self.assertEqual(code, 2)
        printed = json.loads(stdout.getvalue())
        self.assertEqual(printed['status'], 'invalid')
        self.assert_human_gates_open(printed)

    def test_png_missing_only_final_iend_crc_is_rejected(self):
        """Pillow verify/load accepts a PNG missing only its final IEND CRC; we must not."""
        path = self.review_dir / 'dx12-ads-raw.png'
        original = path.read_bytes()
        self.assertEqual(original[-8:-4], b'IEND')
        path.write_bytes(original[:-1])  # drop the final CRC byte only
        truncated_sha = sha(path.read_bytes())
        doc = self.valid()
        # Point the ADS entry at the truncated bytes (hip untouched).
        doc['measurements'][0]['image_sha256'] = truncated_sha
        report = self.assert_invalid(doc, 'framed PNG')
        self.assertTrue(any('CRC' in error or 'framed PNG' in error
                            for error in report['errors']), report['errors'])
        self.assert_human_gates_open(report)

    def test_invalid_utf8_with_existing_output_refuses_without_clobber(self):
        """Parse-error reports use the protected writer; existing files stay untouched."""
        bad = self.root / 'bad-utf8.json'
        bad.write_bytes(b'\xff\xfe not valid utf-8 at all')
        output = self.root / 'existing-report.json'
        marker = b'DO-NOT-CLOBBER'
        output.write_bytes(marker)
        with contextlib.redirect_stdout(io.StringIO()) as stdout, \
                contextlib.redirect_stderr(io.StringIO()) as stderr:
            code = landmarks.main(['review', str(bad), '--root', str(self.root),
                                   '--output', str(output)])
        self.assertEqual(code, 2)
        self.assertEqual(output.read_bytes(), marker)
        self.assertIn('refusing to overwrite', stderr.getvalue())
        printed = json.loads(stdout.getvalue())
        self.assertEqual(printed['status'], 'invalid')
        self.assertTrue(any('UTF-8' in error or 'utf-8' in error or 'codec' in error
                            for error in printed['errors']), printed['errors'])
        self.assert_human_gates_open(printed)

    # Schema and CLI ------------------------------------------------------------

    def test_schema_and_shape(self):
        for document in ({}, [], {'schema': 'x', 'evidence': {}, 'measurements': []}):
            self.assertEqual(self.run_review(document)['status'], 'invalid')
        doc = self.valid()
        doc['measurements'] = []
        self.assert_invalid(doc, 'non-empty')
        self.assertEqual(landmarks.review(self.valid(), self.root / 'absent')['status'], 'invalid')

    def test_template_is_blank_and_rejected_unchanged(self):
        packet = self.packet()
        skeleton = landmarks.template(packet, self.review_dir)
        for entry in skeleton['measurements']:
            self.assertIsNone(entry['measured_center'])
            self.assertIsNone(entry['outcome'])
        self.assertEqual(landmarks.review(skeleton, self.review_dir)['status'], 'invalid')

    def test_cli_exit_codes_and_no_overwrite(self):
        measurements = self.root / 'measurements.json'
        measurements.write_text(json.dumps(self.valid()), encoding='utf-8')
        output = self.root / 'report.json'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(landmarks.main(['review', str(measurements), '--root', str(self.root),
                                             '--output', str(output)]), 0)
        report = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(report['status'], 'within-tolerance')
        self.assert_human_gates_open(report)
        original = output.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(landmarks.main(['review', str(measurements), '--root',
                                             str(self.root), '--output', str(output)]), 2)
        self.assertIn('refusing to overwrite', stderr.getvalue())
        self.assertEqual(output.read_bytes(), original)
        far = self.root / 'far.json'
        doc = self.valid()
        doc['measurements'][1]['measured_center'] = [540, 280]
        far.write_text(json.dumps(doc), encoding='utf-8')
        bad = self.root / 'bad.json'
        bad.write_text(json.dumps(self.valid()).replace('[479, 268]', '[NaN, 268]'),
                       encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(landmarks.main(['review', str(far), '--root', str(self.root)]), 1)
            self.assertEqual(landmarks.main(['review', str(bad), '--root', str(self.root)]), 2)
            self.assertEqual(landmarks.main(['review', str(measurements), '--root',
                                             str(self.root), '--frames', 'vulkan=x']), 2)
        self.assertIn('non-finite', stdout.getvalue())


if __name__ == '__main__':
    unittest.main()
