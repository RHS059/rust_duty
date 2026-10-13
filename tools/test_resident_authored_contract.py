"""Independent synthetic resident-loader report and retained-byte negatives.

No native process, GPU, authored asset or compiler is run. Retained-file tests
use a deliberately reduced synthetic extent, leaving production limits intact.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import performance_matrix as matrix
import run_resident_authored_contract as resident
import test_authored_loader_pair as old

RECEIPT = old.RECEIPT
STATS = ('draws', 'rigid_draws', 'skinned_draws', 'vertex_bytes_uploaded',
         'index_bytes_uploaded', 'uniform_bytes_uploaded', 'cache_hits',
         'cache_misses', 'transient_meshes', 'buffer_allocations', 'binding_allocations')
WARP = {'requested': 'dx12', 'backend': 'Dx12', 'adapter': 'Microsoft Basic Render Driver'}
A100 = {'requested': 'vulkan', 'backend': 'Vulkan', 'adapter': 'NVIDIA A100-SXM4-40GB'}


def chunks(case):
    alpha = int(case['metadata'].get('alpha', 1.) * 255. + 0.5)
    first = old.corner_bytes(alpha)
    second = bytearray(first)
    second[20] = 64  # Distinct second command; swapping chunks must be observable.
    return [first] if case['name'].startswith('rigid-alpha-') else [first, bytes(second)]


def fixture():
    report = old.report_fixture()
    report.update(schema=resident.SCHEMA, passed=True, backend=WARP.copy())
    for case in report['cases']:
        raw = chunks(case)
        commands = [copy.deepcopy(case['commands'][0]) for _ in raw]
        for index, (command, data) in enumerate(zip(commands, raw)):
            command['expanded_sha256'] = resident.pair.controls.digest(data)
            if index:
                command['texture']['rgba_sha256'] = 'c' * 64
        count = len(commands)
        stats = dict.fromkeys(STATS, 0)
        stats.update(draws=count, rigid_draws=1, skinned_draws=count-1,
                     vertex_bytes_uploaded=32*count, index_bytes_uploaded=8*count,
                     uniform_bytes_uploaded=240*count+16384, cache_misses=count,
                     buffer_allocations=2*count+2, binding_allocations=2)
        case.pop('commands')
        case.update(cpu_commands=commands, resident_commands=copy.deepcopy(commands),
                    cpu_paths=[count, 0, 0], resident_paths=[0, 1, count-1],
                    cpu_stats=dict.fromkeys(STATS, 0), resident_stats=stats,
                    expanded_equal=True, differing_pixels=0, maximum_channel_delta=0,
                    foreground_pixels=128,
                    cpu_expanded_sha256=resident.pair.controls.digest(b''.join(raw)),
                    resident_expanded_sha256=resident.pair.controls.digest(b''.join(raw)))
    return report


def write_outputs(directory, report):
    directory.mkdir()
    matrix.write_json(directory/'report.json', report)
    matrix.write_json(directory/'camera.json', report['camera'])
    image = Image.new('RGBA', tuple(resident.authored.EXTENT), (8, 16, 24, 255))
    for index in range(128):
        image.putpixel((index % image.width, index // image.width), (32+index % 8, 64, 96, 255))
    for case in report['cases']:
        for label in ('cpu', 'resident'):
            (directory/f'{case["name"]}-{label}.corners.bin').write_bytes(b''.join(chunks(case)))
            image.save(directory/f'{case["name"]}-{label}.png')


class ResidentAuthoredReportTests(unittest.TestCase):
    def reject(self, change):
        report = fixture()
        change(report)
        with self.assertRaises(ValueError):
            resident.validate_report(report, RECEIPT)

    def test_complete_report_uses_original_cpu_and_actual_rigid_skin_routes(self):
        report = fixture()
        before = copy.deepcopy(report)
        self.assertEqual(resident.validate_report(report, RECEIPT), before)
        self.assertEqual(report, before)
        self.assertEqual(set(resident.STATS), set(STATS))
        report['backend'] = A100.copy()
        self.assertIs(resident.validate_report(report, RECEIPT), report)

    def test_source_binding_schema_and_passed_are_explicit(self):
        for key, value in [('schema', 'older'), ('passed', False), ('passed', 1),
                           ('source_receipt_sha256', 'b'*64), ('source_receipt_sha256', None)]:
            with self.subTest(key=key, value=value):
                self.reject(lambda r: r.update({key: value}))
        for digest in ('A'*64, 'a'*63, None, 1):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                resident.validate_report(fixture(), digest)

    def test_case_inventory_is_ordered_closed_and_nonempty(self):
        for change in (lambda r: r['cases'].pop(), lambda r: r['cases'].append(r['cases'][0]),
                       lambda r: r['cases'].reverse(), lambda r: r.update(cases=[])):
            self.reject(change)

    def test_both_paths_cannot_silently_use_cpu_or_omit_either_actor_class(self):
        for key, counts in [('cpu_paths', [0, 1, 1]), ('resident_paths', [1, 1, 0]),
                            ('resident_paths', [0, 0, 2]), ('resident_paths', [0, 2, 0]),
                            ('resident_paths', [0, 1, 0]), ('resident_paths', [False, 1, 1]),
                            ('resident_paths', [0, 1, 2049])]:
            with self.subTest(key=key, counts=counts):
                self.reject(lambda r: r['cases'][1].update({key: counts}))
        self.reject(lambda r: r['cases'][20].update(resident_paths=[0, 0, 1]))

    def test_ordered_commands_and_material_snapshots_must_match(self):
        for key, value in [('expanded_sha256', 'f'*64), ('stored_vertices', 3),
                           ('model_bits', [0]*16), ('texture', None)]:
            with self.subTest(key=key):
                self.reject(lambda r: r['cases'][1]['resident_commands'][0].update({key: value}))
        self.reject(lambda r: r['cases'][1]['resident_commands'].reverse())
        self.reject(lambda r: r['cases'][1].update(expanded_equal=1))

    def test_old_loader_pose_camera_and_return_time_guards_remain_active(self):
        for change in (lambda r: r['camera'].update(extent=[1, 1]),
                       lambda r: r['camera']['view_projection_bits'].__setitem__(0, 0x7fc00000),
                       lambda r: r['cases'][1]['metadata'].update(fraction_tenths=True),
                       lambda r: r['cases'][1]['metadata'].update(time_bits=old.f32_bits(0.25)),
                       lambda r: r['cases'][1]['metadata'].update(clip='different_clip'),
                       lambda r: r['cases'][17]['metadata'].update(simulation_time_bits=0),
                       lambda r: r['cases'][17]['metadata'].update(warning='Authored WIP: changed')):
            self.reject(change)
        def changed_revisit(r):
            for label in ('cpu', 'resident'):
                r['cases'][3][label+'_commands'][0]['texture']['rgba_sha256'] = 'd'*64
        self.reject(changed_revisit)

    def test_counter_inventory_types_and_allocation_relationships_are_strict(self):
        for key, value in [('draws', 3), ('rigid_draws', 2), ('skinned_draws', 0),
                           ('cache_hits', 1), ('cache_misses', 1), ('transient_meshes', 3),
                           ('vertex_bytes_uploaded', 60), ('index_bytes_uploaded', 12),
                           ('uniform_bytes_uploaded', 480), ('buffer_allocations', 0),
                           ('binding_allocations', 0), ('draws', True), ('cache_hits', -1),
                           ('index_bytes_uploaded', 2**64)]:
            with self.subTest(key=key, value=value):
                self.reject(lambda r: r['cases'][1]['resident_stats'].update({key: value}))
        self.reject(lambda r: r['cases'][1]['resident_stats'].pop('cache_hits'))
        self.reject(lambda r: r['cases'][1]['resident_stats'].update(extra=0))
        self.reject(lambda r: r['cases'][1]['cpu_stats'].update(binding_allocations=2))

    def test_warm_geometry_still_retains_two_snapshot_buffers_and_bindings(self):
        report = fixture()
        for case in report['cases']:
            stats = case['resident_stats']
            stats.update(cache_hits=stats['draws'], cache_misses=0,
                         vertex_bytes_uploaded=0, index_bytes_uploaded=0,
                         buffer_allocations=2)
        resident.validate_report(report, RECEIPT)
        report['cases'][1]['resident_stats']['binding_allocations'] = 0
        with self.assertRaises(ValueError):
            resident.validate_report(report, RECEIPT)

    def test_combined_corner_hash_and_pixel_verdict_cannot_be_inferred(self):
        for key, value in [('cpu_expanded_sha256', 'bad'), ('resident_expanded_sha256', 'b'*64),
                           ('differing_pixels', 1), ('differing_pixels', False),
                           ('maximum_channel_delta', 1), ('maximum_channel_delta', False),
                           ('foreground_pixels', 100), ('foreground_pixels', True),
                           ('foreground_pixels', 960*540+1)]:
            with self.subTest(key=key, value=value):
                self.reject(lambda r: r['cases'][1].update({key: value}))

    def test_backend_report_rejects_unreviewed_or_mixed_identities(self):
        for backend in ({**WARP, 'requested': 'vulkan'}, {**WARP, 'adapter': 'hardware'},
                        {**A100, 'backend': 'Gl'}, {**A100, 'extra': True}, None):
            with self.subTest(backend=backend):
                self.reject(lambda r: r.update(backend=backend))


class ResidentAuthoredOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)/'captures'
        extent = patch.object(resident.authored, 'EXTENT', [64, 16])
        extent.start()
        self.addCleanup(extent.stop)
        self.report = fixture()
        write_outputs(self.directory, self.report)

    def validate(self):
        return resident.validate_outputs(self.directory, self.report, RECEIPT)

    def test_original_retained_bytes_prove_all_22_exact_pairs(self):
        before = resident.pair.controls.source_manifest(self.directory)
        result = self.validate()
        self.assertTrue(result['passed'])
        self.assertEqual(result['exact_authored_pairs'], 22)
        self.assertTrue(result['original_cpu_oracle'])
        self.assertTrue(result['actual_resident_commands'])
        self.assertEqual(resident.pair.controls.source_manifest(self.directory), before)

    def test_retained_report_and_camera_must_match_original(self):
        for name in ('report.json', 'camera.json'):
            with self.subTest(name=name):
                path = self.directory/name
                original = path.read_bytes()
                path.write_text('{}\n')
                with self.assertRaises(ValueError):
                    self.validate()
                path.write_bytes(original)

    def test_extra_file_directory_missing_input_and_symlink_are_rejected(self):
        extra = self.directory/'unexpected'
        extra.write_bytes(b'extra')
        with self.assertRaises(ValueError):
            self.validate()
        extra.unlink()
        extra.mkdir()
        with self.assertRaises(ValueError):
            self.validate()
        extra.rmdir()
        path = self.directory/'ready-0-cpu.corners.bin'
        original = path.read_bytes()
        path.unlink()
        with self.assertRaises(ValueError):
            self.validate()
        target = Path(self.temp.name)/'external.bin'
        target.write_bytes(original)
        try:
            path.symlink_to(target)
        except (OSError, NotImplementedError):
            path.write_bytes(original)
        else:
            with self.assertRaises(ValueError):
                self.validate()

    def test_mutated_corner_bytes_are_rejected_without_honest_hash(self):
        path = self.directory/'ready-1-resident.corners.bin'
        path.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.validate()

    def test_rehashed_combined_stream_cannot_hide_swapped_command_chunks(self):
        case = self.report['cases'][1]
        raw = b''.join(reversed(chunks(case)))
        for label in ('cpu', 'resident'):
            (self.directory/f'ready-1-{label}.corners.bin').write_bytes(raw)
            case[label+'_expanded_sha256'] = resident.pair.controls.digest(raw)
        (self.directory/'report.json').write_text(json.dumps(self.report, allow_nan=False)+'\n')
        resident.validate_report(self.report, RECEIPT)
        with self.assertRaisesRegex(ValueError, 'ordered raw corner chunk'):
            self.validate()

    def test_rehashed_trailing_corner_bytes_cannot_hide_wrong_extent(self):
        case = self.report['cases'][1]
        raw = b''.join(chunks(case))+b'padding'
        for label in ('cpu', 'resident'):
            (self.directory/f'ready-1-{label}.corners.bin').write_bytes(raw)
            case[label+'_expanded_sha256'] = resident.pair.controls.digest(raw)
        (self.directory/'report.json').write_text(json.dumps(self.report, allow_nan=False)+'\n')
        with self.assertRaisesRegex(ValueError, 'corner extent'):
            self.validate()

    def test_native_rgba_mismatch_is_detected_with_unchanged_foreground(self):
        path = self.directory/'ready-1-resident.png'
        with Image.open(path) as image:
            pixels = image.copy()
        pixels.putpixel((0, 0), (33, 64, 96, 255))
        pixels.save(path)
        with self.assertRaisesRegex(ValueError, 'actual native RGBA'):
            self.validate()

    def test_image_format_alpha_visibility_and_shading_remain_required(self):
        path = self.directory/'ready-0-cpu.png'
        original = path.read_bytes()
        for change in ('rgb', 'extent', 'alpha', 'empty', 'flat'):
            with self.subTest(change=change):
                with Image.open(path) as loaded:
                    pixels = loaded.copy()
                if change == 'rgb': pixels = pixels.convert('RGB')
                elif change == 'extent': pixels = pixels.crop((0, 0, 32, 16))
                elif change == 'alpha': pixels.putpixel((0, 0), (32, 64, 96, 254))
                elif change == 'empty': pixels = Image.new('RGBA', pixels.size, (8,16,24,255))
                else:
                    for i in range(128): pixels.putpixel((i%64, i//64), (64,64,64,255))
                pixels.save(path)
                with self.assertRaises(ValueError): self.validate()
                path.write_bytes(original)


class ResidentAuthoredDeviceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.log = Path(self.temp.name)/'stderr.log'

    def test_linux_requires_actual_a100_fingerprint_and_one_record(self):
        report = fixture()
        report['backend'] = A100.copy()
        evidence = {'backend':'Vulkan', 'name':A100['adapter'], 'device_type':'DiscreteGpu',
                    'vendor_id':4318, 'device_id':8368, 'force_fallback_requested':False}
        prefix = 'renderer graphics_device_evidence='
        with patch.object(resident.sys, 'platform', 'linux'):
            self.log.write_text(prefix+json.dumps(evidence)+'\n')
            self.assertEqual(resident.device_evidence(self.log, report), evidence)
            for key,value in [('backend','Gl'), ('name','other'), ('device_type','Cpu'),
                              ('vendor_id',0), ('device_id',0), ('force_fallback_requested',True)]:
                with self.subTest(key=key):
                    self.log.write_text(prefix+json.dumps({**evidence,key:value})+'\n')
                    with self.assertRaises(ValueError): resident.device_evidence(self.log, report)
            for text in ('', (prefix+json.dumps(evidence)+'\n')*2):
                self.log.write_text(text)
                with self.assertRaises(ValueError): resident.device_evidence(self.log, report)
            self.log.write_text(prefix+json.dumps(evidence)+'\n')
            report['backend'] = WARP.copy()
            with self.assertRaises(ValueError): resident.device_evidence(self.log, report)

    def test_windows_retains_headless_cpu_and_pinned_shader_compiler_checks(self):
        evidence = {'device_type':'Cpu', 'vendor_id':5140, 'device_id':140,
                    'driver':'', 'driver_info':'', 'present_mode':None,
                    'force_fallback_requested':True}
        prefix = 'renderer dx12_shader_compiler=Fxc\nrenderer device_evidence='
        with patch.object(resident.sys, 'platform', 'win32'):
            self.log.write_text(prefix+json.dumps(evidence)+'\n')
            self.assertEqual(resident.device_evidence(self.log, fixture()), evidence)
            for changed in ({**evidence,'device_type':'DiscreteGpu'},
                            {**evidence,'force_fallback_requested':False},
                            {**evidence,'present_mode':'Fifo'}):
                self.log.write_text(prefix+json.dumps(changed)+'\n')
                with self.assertRaises(ValueError): resident.device_evidence(self.log, fixture())
            self.log.write_text('renderer device_evidence='+json.dumps(evidence)+'\n')
            with self.assertRaises(ValueError): resident.device_evidence(self.log, fixture())


if __name__ == '__main__':
    unittest.main()
