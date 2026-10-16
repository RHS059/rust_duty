"""CPU-only transparent-source transport and adversarial assembly tests."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prone_r15_source_delta as delta
import prone_r15_delta_transport as transport
from test_prone_r15_source_delta import DEFAULTS, curve, evidence_fixture, key, record


def recipe_fixture():
    recipe = evidence_fixture()[3]
    base = record(); target = copy.deepcopy(base)
    target["curves"][0]["keys"] = [key(1 + i / 8, i / 512, "LINEAR") for i in range(65)]
    target["curves"][0]["keys"][0]["co"][1] = -0.0
    target["curves"][0]["keys"][0]["co_ui"][1] = -0.0
    target["curves"][0]["keys"][0]["period"] = -0.0
    rig = delta.build_action_delta(base, target, DEFAULTS, "rig")
    rig["target_fingerprint"] = delta.RIG_FINGERPRINT; rig["base_fingerprint"] = delta.BASE_FINGERPRINT
    camera_record = delta.empty_action(); camera_record["curves"] = [curve("location", 0)]
    camera = delta.build_action_delta(delta.empty_action(), camera_record, DEFAULTS, "camera")
    camera["target_fingerprint"] = delta.CAMERA_FINGERPRINT
    recipe["actions"] = {"rig": rig, "camera": camera}
    return recipe


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.source = self.root / "original.json"
        self.source.write_bytes(transport.canonical(recipe_fixture()))
        self.original_sha = delta.sha(self.source)
        self.package = self.root / "package"
        transport.write_package(self.source, self.original_sha, self.package, target_bytes=8192)
        self.manifest_path = self.package / "manifest.json"

    def tearDown(self): self.temp.cleanup()

    def assemble(self): return transport.assemble_bytes(self.manifest_path, delta.sha(self.manifest_path))

    def manifest(self): return json.loads(self.manifest_path.read_text())

    def save_manifest(self, value): self.manifest_path.write_bytes(transport.canonical(value))

    def rewrite_part(self, descriptor, document):
        data = transport.canonical(document)
        (self.package / descriptor["file"]).write_bytes(data)
        descriptor.update(bytes=len(data), sha256=transport.bytes_sha(data))

    def test_exact_bytes_preserve_negative_zero_and_original_identity(self):
        result = self.assemble()
        self.assertEqual(result, self.source.read_bytes())
        self.assertIn(b"-0.0", result)
        self.assertEqual(transport.bytes_sha(result), self.original_sha)

    def test_deterministic_partition_and_manifest(self):
        other = self.root / "second"
        transport.write_package(self.source, self.original_sha, other, target_bytes=8192)
        self.assertEqual(sorted(p.name for p in other.iterdir()), sorted(p.name for p in self.package.iterdir()))
        for path in self.package.iterdir(): self.assertEqual(path.read_bytes(), (other / path.name).read_bytes())

    def test_every_file_is_plain_json_under_200kib(self):
        for path in self.package.iterdir():
            self.assertLess(path.stat().st_size, 200 * 1024)
            value = json.loads(path.read_text())
            self.assertIsInstance(value, dict)
            if "keys" in value: self.assertIsInstance(value["keys"][0], dict)

    def test_existing_package_never_overwritten(self):
        with self.assertRaises(FileExistsError):
            transport.write_package(self.source, self.original_sha, self.package, target_bytes=8192)

    def test_wrong_source_pin_rejected(self):
        with self.assertRaisesRegex(ValueError, "source delta"):
            transport.write_package(self.source, "0" * 64, self.root / "wrong")

    def test_noncanonical_source_is_not_silently_reformatted(self):
        self.source.write_text(json.dumps(recipe_fixture()))
        with self.assertRaisesRegex(ValueError, "canonical"):
            transport.write_package(self.source, delta.sha(self.source), self.root / "wrong")

    def test_modified_shard_bytes_rejected(self):
        part = self.package / self.manifest()["files"][-1]["file"]
        part.write_bytes(part.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "bytes/hash"): self.assemble()

    def test_missing_shard_rejected(self):
        (self.package / self.manifest()["files"][-1]["file"]).unlink()
        with self.assertRaisesRegex(ValueError, "not closed"): self.assemble()

    def test_omitted_key_part_fails_coverage(self):
        manifest = self.manifest(); removed = manifest["files"].pop(); (self.package / removed["file"]).unlink(); self.save_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "missing key"): self.assemble()

    def test_duplicate_descriptor_rejected(self):
        manifest = self.manifest(); manifest["files"].append(manifest["files"][-1]); self.save_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "duplicate"): self.assemble()

    def test_path_traversal_rejected(self):
        manifest = self.manifest(); manifest["files"][-1]["file"] = "../original.json"; self.save_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "unsafe"): self.assemble()

    def test_duplicate_key_ranges_rejected_even_with_updated_file_hash(self):
        manifest = self.manifest()
        descriptor = next(d for d in reversed(manifest["files"]) if d["file"].startswith("keys-rig"))
        document = json.loads((self.package / descriptor["file"]).read_text()); document["key_start"] = 0
        self.rewrite_part(descriptor, document); self.save_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "duplicate key"): self.assemble()

    def test_altered_authored_delta_fails_original_source_hash(self):
        manifest = self.manifest()
        descriptor = next(d for d in manifest["files"] if d["file"].startswith("keys-rig"))
        document = json.loads((self.package / descriptor["file"]).read_text())
        op = next(k for k in document["keys"] if k["op"] in ("add", "replace"))
        op["settings"]["period"] = 17.0
        self.rewrite_part(descriptor, document); self.save_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "original bytes"): self.assemble()

    def test_raw_inherited_curve_payload_rejected(self):
        recipe = recipe_fixture()
        reference = next(c for c in recipe["actions"]["rig"]["curves"] if c["op"] == "reference")
        reference["keys"] = [key(1, 1)]
        with self.assertRaisesRegex(ValueError, "inherited data"): transport.audit_scope(recipe)

    def test_geometry_payload_rejected(self):
        recipe = recipe_fixture(); recipe["mesh_vertices"] = [[0., 0., 0.]]
        with self.assertRaisesRegex(ValueError, "unexpected recipe"): transport.audit_scope(recipe)

    def test_header_must_precede_other_parts(self):
        manifest = self.manifest(); manifest["files"][0], manifest["files"][1] = manifest["files"][1], manifest["files"][0]
        self.save_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "before header"): self.assemble()

    def test_unlisted_sibling_file_rejected(self):
        (self.package / "unlisted-private.blend").write_text("synthetic placeholder")
        with self.assertRaisesRegex(ValueError, "not closed"): self.assemble()

    def test_unlisted_sibling_directory_rejected(self):
        (self.package / "unlisted-directory").mkdir()
        with self.assertRaisesRegex(ValueError, "not closed"): self.assemble()

    def test_declared_symlink_rejected(self):
        part = self.package / self.manifest()["files"][-1]["file"]
        part.unlink(); part.symlink_to(self.source)
        with self.assertRaisesRegex(ValueError, "regular files"): self.assemble()

    def test_symlinked_manifest_rejected(self):
        manifest = self.manifest_path.read_bytes()
        external = self.root / "external.json"; external.write_bytes(manifest)
        self.manifest_path.unlink(); self.manifest_path.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "ordinary manifest"): self.assemble()

    def test_nested_curve_settings_rejected(self):
        for name in ("group", "mute", "extrapolation", "color", "auto_smoothing"):
            with self.subTest(name=name):
                recipe = recipe_fixture(); recipe["actions"]["camera"]["curves"][0]["settings"][name] = {"private": [1, 2, 3]}
                with self.assertRaises(ValueError): transport.audit_scope(recipe)

    def test_group_and_enum_bounds_rejected(self):
        for name, value in (("group", "x" * 64), ("group", "bad\nname"), ("group", ""),
                            ("extrapolation", "UNRECOGNIZED"), ("color_mode", 3), ("auto_smoothing", ["NONE"])):
            with self.subTest(name=name, value=value):
                recipe = recipe_fixture(); recipe["actions"]["camera"]["curves"][0]["settings"][name] = value
                with self.assertRaises(ValueError): transport.audit_scope(recipe)

    def test_color_requires_three_finite_bounded_nonboolean_numbers(self):
        for color in ([0., 0.], [0., 0., 0., 0.], [0., {}, 0.], [0., float("nan"), 0.],
                      [0., float("inf"), 0.], [0., True, 0.], [0., 1.001, 0.], [0., -0.01, 0.]):
            with self.subTest(color=color):
                recipe = recipe_fixture(); recipe["actions"]["camera"]["curves"][0]["settings"]["color"] = color
                with self.assertRaises(ValueError): transport.audit_scope(recipe)

    def test_nested_and_mistyped_action_settings_rejected(self):
        for name, value in (("frame_start", {"private": [1]}), ("frame_end", [69]),
                            ("use_frame_range", 1), ("use_cyclic", "false"),
                            ("frame_start", -1), ("frame_end", 70), ("frame_start", float("nan"))):
            with self.subTest(name=name):
                recipe = recipe_fixture(); recipe["actions"]["rig"]["settings"][name] = value
                with self.assertRaises(ValueError): transport.audit_scope(recipe)

    def test_nested_and_mistyped_key_settings_rejected(self):
        for name, value in (("period", {"private": [1]}), ("amplitude", [1]), ("back", float("inf")),
                            ("period", 1e100), ("select_control_point", 1), ("interpolation", "UNKNOWN"),
                            ("handle_left_type", ["AUTO"]), ("easing", {"private": "value"})):
            with self.subTest(name=name):
                recipe = recipe_fixture(); recipe["actions"]["camera"]["curves"][0]["keys"][0]["settings"][name] = value
                with self.assertRaises(ValueError): transport.audit_scope(recipe)

    def test_nested_delta_and_zero_sign_payloads_rejected(self):
        for field, value in (("delta", {"co": {"private": [1]}}), ("delta", {"co": [0, {"private": 1}]}),
                             ("zero_signs", [{"private": [1]}]), ("co_ui_present", {"private": 1}),
                             ("frame", {"private": 1}), ("before_sha256", {"private": 1})):
            with self.subTest(field=field):
                recipe = recipe_fixture(); recipe["actions"]["camera"]["curves"][0]["keys"][0][field] = value
                with self.assertRaises(ValueError): transport.audit_scope(recipe)

    def test_hash_metadata_cannot_carry_nested_data(self):
        recipe = recipe_fixture(); recipe["base_actions_sha256"] = {"private": [1, 2, 3]}
        with self.assertRaises(ValueError): transport.audit_scope(recipe)
        recipe = recipe_fixture(); recipe["actions"]["camera"]["target_complete_sha256"] = {"private": [1]}
        with self.assertRaises(ValueError): transport.audit_scope(recipe)

    def test_valid_scalar_settings_still_accepted(self):
        recipe = recipe_fixture()
        recipe["actions"]["rig"]["settings"] = {"frame_start": 0.0, "frame_end": 69.0,
                                                   "use_frame_range": False, "use_cyclic": False}
        recipe["actions"]["camera"]["curves"][0]["settings"].update(group=None, color=[0.0, .5, 1.0])
        self.assertEqual(transport.audit_scope(recipe)["camera"]["add_curve"], 1)

    def test_no_native_or_network_modules_used(self):
        self.assertNotIn("bpy", sys.modules)


if __name__ == "__main__": unittest.main()
