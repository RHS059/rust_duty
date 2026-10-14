"""Source-free fail-closed tests for the explicit r6 paired FBX adapter.

These exercise the adapter's public Python functions. They do not import bpy,
run Blender, export FBX, inspect private source data, or prove native parity.
"""
import copy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import export_prone_pair as exporter
import prone_camera_pair
import vrpack


def config():
    path = Path(__file__).with_name('prone_pair_r6_export.json')
    return json.loads(path.read_text())


def translation(x, y, z):
    return (1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z, 0, 0, 0, 1)


def rows(matrix):
    return [list(matrix[i:i+4]) for i in range(0, 16, 4)]


def synthetic_inputs():
    """An independent translated/rotated camera with a known one-metre drop."""
    source_hash = hashlib.sha256(b'original synthetic paired source').hexdigest()
    fingerprints = {prone_camera_pair.RIG_ACTION: 'a' * 64,
                    prone_camera_pair.CAMERA_ACTION: 'b' * 64}
    initial = (0, -1, 0, 3, 1, 0, 0, 2, 0, 0, 1, 5, 0, 0, 0, 1)
    samples = []
    for i in range(545):
        camera = list(initial)
        camera[11] = 5 - i/544
        samples.append({'candidate_frame': 1 + i/8, 'time_seconds': i/480,
                        'camera_world': rows(camera),
                        'common_world_delta': rows(translation(0, 0, -i/544))})
    document = {
        'schema': prone_camera_pair.SIDECAR_SCHEMA,
        'candidate_sha256': source_hash, 'action_fingerprints': fingerprints,
        'units': 'metres and radians; Blender world +Z up',
        'camera_local_axes': '+X right, +Y up, -Z forward',
        'initial_camera_world': rows(initial), 'sample_hz': 480, 'fps': 60,
        'duration_key_span_seconds': 68/60, 'rows': samples,
    }
    data = json.dumps(document).encode()
    revised = config()
    revised.update(source_sha256=source_hash, action_fingerprints=fingerprints.copy(),
                   camera_sidecar_sha256=hashlib.sha256(data).hexdigest())
    return revised, source_hash, fingerprints, data


class ExportConfigTests(unittest.TestCase):
    def test_explicit_r6_config_passes_without_mutation(self):
        original = config()
        saved = copy.deepcopy(original)
        result = exporter.validate_config(original)
        self.assertIsInstance(result, dict)
        self.assertEqual(result, saved)
        self.assertEqual(original, saved)

    def test_schema_status_version_clock_and_clip_are_fixed(self):
        invalid = (
            ('schema', 'rust-duty-prone-isolated-export-handoff/v1'),
            ('status', 'approved'), ('blender_version', '4.4.0'),
            ('source_fps', 59.94), ('bake_hz', 60),
            ('candidate_frames', [1, 68]), ('native_crop', [0, 69]),
            ('candidate_frame_offset', 0), ('imported_frame_offset', 0),
            ('source_take', 'prone_crawl_enter_r5'),
            ('runtime_clip', 'prone_crawl_enter'),
            ('loop', True), ('hold_after_end', False),
        )
        for field, value in invalid:
            revised = config()
            revised[field] = value
            with self.subTest(field=field), self.assertRaises(vrpack.AssetError):
                exporter.validate_config(revised)

    def test_no_missing_pin_or_implicit_mapping_default(self):
        for field in ('source_sha256', 'camera_sidecar_sha256', 'action_fingerprints',
                      'candidate_frames', 'native_crop', 'candidate_frame_offset',
                      'imported_frame_offset', 'source_take', 'runtime_clip'):
            revised = config()
            del revised[field]
            with self.subTest(field=field), self.assertRaises(vrpack.AssetError):
                exporter.validate_config(revised)

    def test_boolean_or_nonfinite_clock_values_are_not_numbers(self):
        for field, value in (('candidate_frames', [True, 69]),
                             ('candidate_frame_offset', True),
                             ('imported_frame_offset', float('nan')),
                             ('bake_hz', float('inf'))):
            revised = config()
            revised[field] = value
            with self.subTest(field=field), self.assertRaises(vrpack.AssetError):
                exporter.validate_config(revised)

    def test_malformed_or_incomplete_identity_rejected(self):
        for field, value in (('source_sha256', 'short'),
                             ('camera_sidecar_sha256', 'F' * 64),
                             ('action_fingerprints', {}),
                             ('action_fingerprints', {prone_camera_pair.RIG_ACTION: 'a' * 64}),
                             ('action_fingerprints', {prone_camera_pair.RIG_ACTION: 'bad',
                                                      prone_camera_pair.CAMERA_ACTION: 'b' * 64})):
            revised = config()
            revised[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(vrpack.AssetError):
                exporter.validate_config(revised)

    def test_duplicate_or_overlapping_geometry_declarations_rejected(self):
        for field, value in (('skin_objects', ['skin', 'skin']),
                             ('rigid_actors', ['actor', 'actor']),
                             ('rigid_actors', config()['skin_objects'][:1]),
                             ('deform_bone_count', 71)):
            revised = config()
            revised[field] = value
            with self.subTest(field=field), self.assertRaises(vrpack.AssetError):
                exporter.validate_config(revised)


class ExportInputTests(unittest.TestCase):
    def test_separately_pinned_revised_source_is_supported(self):
        args = synthetic_inputs()
        contract = exporter.validate_inputs(*args)
        self.assertIsInstance(contract, prone_camera_pair.CameraPair)
        self.assertEqual(contract.candidate_sha256, args[1])
        self.assertEqual(contract.action_fingerprints, args[2])
        self.assertEqual(contract.delta_at(68), translation(0, 0, -1))

    def test_wrong_source_fingerprint_or_sidecar_bytes_rejected(self):
        cfg, source, fingerprints, sidecar = synthetic_inputs()
        cases = (
            (cfg, 'c' * 64, fingerprints, sidecar),
            (cfg, source, {prone_camera_pair.RIG_ACTION: 'a' * 64}, sidecar),
            (cfg, source, dict(fingerprints, **{prone_camera_pair.CAMERA_ACTION: 'c' * 64}), sidecar),
            (cfg, source, fingerprints, sidecar + b' '),
        )
        for arguments in cases:
            with self.subTest(source=arguments[1], fingerprints=arguments[2]), self.assertRaises(vrpack.AssetError):
                exporter.validate_inputs(*arguments)

    def test_repaired_sidecar_hash_does_not_bypass_wrong_content(self):
        for mutate in (
            lambda d: d.update(candidate_sha256='f' * 64),
            lambda d: d['action_fingerprints'].update({prone_camera_pair.CAMERA_ACTION: 'f' * 64}),
            lambda d: d['rows'][100]['common_world_delta'][0].__setitem__(3, .25),
            lambda d: d['rows'].pop(),
        ):
            cfg, source, fingerprints, data = synthetic_inputs()
            document = json.loads(data)
            mutate(document)
            altered = json.dumps(document).encode()
            cfg['camera_sidecar_sha256'] = hashlib.sha256(altered).hexdigest()
            with self.assertRaises(vrpack.AssetError):
                exporter.validate_inputs(cfg, source, fingerprints, altered)


class ExportSettingsTests(unittest.TestCase):
    def test_single_scene_bake_preserves_object_motion_and_full_sample_grid(self):
        destination = Path('/original-synthetic-output/prone_pair.fbx')
        settings = exporter.export_settings(config(), destination)
        self.assertEqual(settings['filepath'], str(destination))
        self.assertTrue(settings['use_selection'])
        self.assertEqual(settings['object_types'], {'ARMATURE', 'MESH'})
        self.assertTrue(settings['bake_anim'])
        self.assertFalse(settings['bake_anim_use_all_actions'])
        self.assertFalse(settings['bake_anim_use_nla_strips'])
        self.assertTrue(settings['bake_anim_use_all_bones'])
        self.assertTrue(settings['bake_anim_force_startend_keying'])
        self.assertEqual(settings['bake_anim_step'], .125)
        self.assertEqual(settings['bake_anim_simplify_factor'], 0)
        self.assertFalse(settings['bake_space_transform'])
        self.assertEqual(settings['armature_nodetype'], 'NULL')
        self.assertEqual(settings['global_scale'], 1)
        self.assertEqual(settings['apply_scale_options'], 'FBX_SCALE_UNITS')
        self.assertEqual((settings['axis_forward'], settings['axis_up']), ('-Z', 'Y'))
        self.assertFalse(settings['add_leaf_bones'])


class EvaluatedPairTests(unittest.TestCase):
    def setUp(self):
        self.arguments = synthetic_inputs()
        self.contract = exporter.validate_inputs(*self.arguments)
        self.initial_rig = translation(2, 3, 4)
        self.camera = (0, -1, 0, 3, 1, 0, 0, 2, 0, 0, 1, 4.5, 0, 0, 0, 1)
        self.rig = translation(2, 3, 3.5)

    def test_valid_paired_sample_returns_canonical_initial_rig(self):
        actual = exporter.validate_evaluated_sample(
            self.contract, Fraction(35), self.camera, self.rig, self.initial_rig)
        for value, expected in zip(actual, self.initial_rig):
            self.assertAlmostEqual(value, expected, places=8)

    def test_wrong_camera_missing_or_double_rig_motion_is_rejected(self):
        wrong_camera = list(self.camera)
        wrong_camera[11] += .1
        for camera, rig in ((wrong_camera, self.rig),
                            (self.camera, self.initial_rig),
                            (self.camera, translation(2, 3, 3)),
                            (self.camera, translation(2, 2.5, 4))):
            with self.subTest(camera=camera, rig=rig), self.assertRaises(vrpack.AssetError):
                exporter.validate_evaluated_sample(self.contract, 35, camera, rig, self.initial_rig)

    def test_out_of_range_or_unmeasured_subframe_is_rejected(self):
        for frame in (0, 70, Fraction(65, 64)):
            with self.subTest(frame=frame), self.assertRaises(vrpack.AssetError):
                exporter.validate_evaluated_sample(self.contract, frame, self.camera, self.rig, self.initial_rig)

    def test_nonfinite_or_nonrigid_camera_is_rejected(self):
        for index, value in ((3, float('nan')), (7, float('inf')), (0, 2), (12, .1)):
            camera = list(self.camera)
            camera[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(vrpack.AssetError):
                exporter.validate_evaluated_sample(self.contract, 35, camera, self.rig, self.initial_rig)


class ExportPathsTests(unittest.TestCase):
    def test_new_output_is_preflighted_without_creating_or_modifying_files(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root/'candidate.blend'
            source.write_bytes(b'original synthetic fixture')
            output = root/'new-output'
            actual = exporter.preflight_paths(source, output)
            self.assertEqual(actual, (source.resolve(), output.resolve()))
            self.assertFalse(output.exists())
            self.assertEqual(source.read_bytes(), b'original synthetic fixture')

    def test_existing_output_or_source_collision_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root/'candidate.blend'
            source.write_bytes(b'original fixture')
            existing = root/'existing'
            existing.mkdir()
            for output in (existing, source, root):
                with self.subTest(output=output), self.assertRaises(vrpack.AssetError):
                    exporter.preflight_paths(source, output)

    def test_missing_source_is_not_reported_as_ready(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises((vrpack.AssetError, FileNotFoundError)):
                exporter.preflight_paths(Path(root)/'missing.blend', Path(root)/'output')


class FakeObject:
    """Only the data API used by bound_pair; deliberately no Blender execution."""
    def __init__(self, name, animation_data=None):
        self.name = name
        self.animation_data = animation_data
        self.location = [1., 2., 3.]
        self.rotation_euler = [.1, .2, .3]
        self.rotation_quaternion = [1., 0., 0., 0.]
        self.rotation_axis_angle = [0., 0., 1., 0.]
        self.scale = [1., 1., 1.]
        self.selected = False
        self.hidden = False

    def animation_data_create(self):
        if self.animation_data is None:
            self.animation_data = SimpleNamespace(action=None, use_nla=True, nla_tracks=[])

    def animation_data_clear(self):
        self.animation_data = None

    def select_get(self):
        return self.selected

    def select_set(self, selected):
        self.selected = selected

    def hide_get(self):
        return self.hidden

    def hide_set(self, hidden):
        self.hidden = hidden


class FakeBone(FakeObject, dict):
    def __init__(self, name):
        FakeObject.__init__(self, name)
        dict.__init__(self, weapon_follow=1.0)


class FakeObjects(list):
    def __getitem__(self, key):
        if isinstance(key, str):
            return next(obj for obj in self if obj.name == key)
        return super().__getitem__(key)


def fake_blender():
    old_action = SimpleNamespace(name='original active Action')
    track = SimpleNamespace(mute=False, is_solo=True)
    rig = FakeObject('Arms', SimpleNamespace(action=old_action, use_nla=True, nla_tracks=[track]))
    rig.pose = SimpleNamespace(bones=[FakeBone('test bone')])
    camera = FakeObject('RD First Person Review')
    camera.hidden = True
    objects = FakeObjects([rig, camera])
    objects.active = camera
    rig.selected = True
    scene = SimpleNamespace(name='original scene', frame_start=10, frame_end=90,
                            frame_current=27, frame_subframe=.375, camera=camera,
                            render=SimpleNamespace(fps=24, fps_base=1.001))
    def frame_set(frame, subframe=0.):
        scene.frame_current, scene.frame_subframe = frame, subframe
    scene.frame_set = frame_set
    actions = {name: SimpleNamespace(name=name) for name in
               (prone_camera_pair.RIG_ACTION, prone_camera_pair.CAMERA_ACTION, config()['base_action'])}
    bpy = SimpleNamespace(
        data=SimpleNamespace(objects=objects, actions=actions,
                             images=[SimpleNamespace(filepath_raw='//original.png')]),
        context=SimpleNamespace(scene=scene,
            view_layer=SimpleNamespace(objects=objects, update=lambda: None),
            evaluated_depsgraph_get=lambda: SimpleNamespace(update=lambda: None)))
    return bpy


def binding_snapshot(bpy):
    props = ('location', 'rotation_euler', 'rotation_quaternion', 'rotation_axis_angle', 'scale')
    objects = {}
    for obj in bpy.data.objects:
        animation = obj.animation_data
        objects[obj.name] = {
            'props': {k: list(getattr(obj, k)) for k in props},
            'animation': None if animation is None else
                (animation.action.name if animation.action else None, animation.use_nla,
                 [(t.mute, t.is_solo) for t in animation.nla_tracks]),
            'selected': obj.selected, 'hidden': obj.hidden,
        }
    scene = bpy.context.scene
    return {
        'objects': objects,
        'bones': [{**{k: list(getattr(b, k)) for k in props}, 'custom': dict(b)}
                  for b in bpy.data.objects['Arms'].pose.bones],
        'scene': (scene.name, scene.frame_start, scene.frame_end, scene.frame_current,
                  scene.frame_subframe, scene.camera.name, scene.render.fps, scene.render.fps_base),
        'images': [image.filepath_raw for image in bpy.data.images],
        'active': bpy.context.view_layer.objects.active.name,
    }


class PairBindingRestorationTests(unittest.TestCase):
    def test_active_pair_and_scene_clock_restored_after_success(self):
        bpy = fake_blender()
        before = binding_snapshot(bpy)
        with exporter.bound_pair(bpy, config()) as (rig, camera):
            self.assertEqual(rig.animation_data.action.name, prone_camera_pair.RIG_ACTION)
            self.assertEqual(camera.animation_data.action.name, prone_camera_pair.CAMERA_ACTION)
            self.assertFalse(rig.animation_data.use_nla)
            self.assertTrue(all(t.mute and not t.is_solo for t in rig.animation_data.nla_tracks))
            self.assertEqual(bpy.context.scene.name, config()['source_take'])
            self.assertEqual((bpy.context.scene.frame_start, bpy.context.scene.frame_end), (1, 69))
            self.assertEqual((bpy.context.scene.render.fps, bpy.context.scene.render.fps_base), (60, 1))
        self.assertEqual(binding_snapshot(bpy), before)

    def test_export_failure_restores_bindings_pose_selection_and_image_paths(self):
        bpy = fake_blender()
        before = binding_snapshot(bpy)
        with self.assertRaisesRegex(RuntimeError, 'simulated export failure'):
            with exporter.bound_pair(bpy, config()) as (rig, camera):
                rig.location = [9., 8., 7.]
                rig.pose.bones[0].rotation_euler = [1., 1., 1.]
                rig.pose.bones[0]['weapon_follow'] = 0.
                rig.select_set(False)
                camera.hide_set(False)
                camera.select_set(True)
                bpy.context.view_layer.objects.active = rig
                bpy.data.images[0].filepath_raw = '/temporary/export/texture.png'
                bpy.context.scene.frame_set(69)
                raise RuntimeError('simulated export failure')
        self.assertEqual(binding_snapshot(bpy), before)


if __name__ == '__main__':
    unittest.main()
