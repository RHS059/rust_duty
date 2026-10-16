"""Synthetic proof-route/adapter regressions, never native parity evidence."""
from __future__ import annotations
import ast
import copy
import hashlib
import json
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import prone_camera_pair as pair
import prone_r15_regenerated_contract as contract
import produce_prone_r15_regenerated_runtime as adapter
import verify_prone_r15_runtime as verifier


def report_fixture(source_sha):
    value = copy.deepcopy(pair.R15_EQUIVALENCE_CONTRACT)
    value.update(schema="rust-duty-prone-r15-source-equivalence/v1", generated_source_sha256=source_sha,
        passed=True, exact_complete_actions_proved=True, non_action_preservation_proved=True,
        evaluated_pair_equivalence_proved=True, source_byte_identity_with_approved=False,
        runtime_equivalence_proved=False, rendered=False, rig_action=contract.ACTION, camera_action=contract.CAMERA_ACTION,
        rig_action_fingerprint=contract.delta.RIG_FINGERPRINT, camera_action_fingerprint=contract.delta.CAMERA_FINGERPRINT,
        delta_sha256=value["recipe_sha256"], evidence_sha256={"delta": value["recipe_sha256"],
        "approved_witness": value["approved_witness_sha256"], "regenerated_witness": "3" * 64, "replay_receipt": "4" * 64})
    return value


def provenance_fixture(root):
    source = root / "synthetic.blend"
    source.write_bytes(b"synthetic test bytes, not a Blender input")
    report_path = root / "equivalence.json"
    report_path.write_text(json.dumps(report_fixture(contract.sha(source))))
    proof_sha = contract.sha(report_path)
    descriptor = contract.descriptor(report_path, proof_sha, source)
    value = {"schema": "rust-duty-prone-r15-regenerated-runtime-provenance/v1",
        "generated_source_sha256": contract.sha(source), "approved_source_sha256": contract.delta.APPROVED_SHA,
        "source_equivalence_sha256": proof_sha, "source_equivalence_descriptor": descriptor,
        "source_witness_sha256": "5" * 64, "source_witness_source_sha256": contract.sha(source),
        "source_fbx_sha256": "6" * 64, "camera_sidecar_sha256": "7" * 64, "rigid_witness_sha256": "8" * 64,
        "export_evidence_sha256": {name: "9" * 64 for name in contract.EVIDENCE_FILES},
        "producer_sha256": contract.code_hashes()}
    return source, report_path, value


def dense_fixture(provenance):
    shared = {"source_sha256": provenance["generated_source_sha256"], "fbx_sha256": provenance["source_fbx_sha256"],
        "source_equivalence_sha256": provenance["source_equivalence_sha256"],
        "source_equivalence_descriptor": provenance["source_equivalence_descriptor"],
        "sample_grid_sha256": contract.GRID_SHA, "fbx_bake_step": 1/64}
    receipt = {**shared, "source_sample_count": 1944, "frames": [1, 69], "fps": [60, 1], "export_bind_frame": 1,
        "selected": contract.SELECTED, "settings": {k: sorted(v) if isinstance(v, set) else v for k, v in contract.DENSE_SETTINGS.items()},
        "source_bytes_unchanged": True, "in_memory_source_state_restored": True, "source_saved": False, "rendered": False}
    checks = contract.ERROR_FIELDS | {"bone_inventory", "hierarchy", "animated_camera_bound", "animated_rig_bound",
        "single_exact_take", "finite_bones", "skin_topology", "camera_projection_rays", "camera_type", "single_native_clock",
        "fps", "source_unchanged", "fbx_unchanged"}
    parity = {**shared, "passed": True, "samples": 1944, "source_total_bones_including_helpers": 148,
        "skin_vertex_samples": 1944 * 10234, "checks": {key: True for key in checks},
        "maxima": {key: 0. for key in contract.ERROR_FIELDS}, "camera_projection_ray_error": 0.,
        "camera_included_and_measured": True, "camera_relative_geometry_measured": True, "subframe_parity": True}
    return receipt, parity


class ProvenanceTests(unittest.TestCase):
    def test_original_constants_and_thresholds_remain_strict(self):
        self.assertEqual(verifier.SOURCE_SHA, contract.delta.APPROVED_SHA)
        self.assertEqual(verifier.FBX_SHA, "f025876ede4ec28098337ea645da679765678d75d94fdcf51965a92eba4e4a02")
        self.assertEqual(verifier.ORACLE_SHA, contract.ORIGINAL_ORACLE_SHA)
        self.assertEqual(verifier.POSITION_LIMIT, 1e-4)
        self.assertEqual(verifier.MATRIX_LIMIT, 1e-4)
        self.assertEqual(len(contract.grid()), 1944)

    def test_complete_provenance_validates_actual_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, report, value = provenance_fixture(root)
            path = root / "provenance.json"
            path.write_text(json.dumps(value))
            actual = contract.load_runtime_provenance(path, contract.sha(path), source, report, contract.sha(report))
            self.assertEqual(actual, value)
            source.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "source provenance"):
                contract.load_runtime_provenance(path, contract.sha(path), source, report, contract.sha(report))

    def test_forged_pass_flag_is_insufficient(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.blend"; source.write_bytes(b"synthetic")
            report = root / "proof.json"; report.write_text('{"passed":true}')
            with self.assertRaises(ValueError):
                contract.descriptor(report, contract.sha(report), source)

    def test_original_and_base_bytes_cannot_claim_generated_role(self):
        with patch.object(contract, "sha", return_value=contract.delta.APPROVED_SHA):
            with self.assertRaisesRegex(ValueError, "distinct"):
                contract.descriptor("proof", "1" * 64, "source")
        with patch.object(contract, "sha", return_value=contract.delta.BASE_SHA):
            with self.assertRaisesRegex(ValueError, "distinct"):
                contract.descriptor("proof", "1" * 64, "source")

    def test_regenerated_provenance_rejects_wrong_oracle_origin_and_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source, report, value = provenance_fixture(root)
            for field, bad in (("approved_source_sha256", "0" * 64), ("source_witness_source_sha256", "0" * 64),
                               ("producer_sha256", {}), ("export_evidence_sha256", {})):
                broken = copy.deepcopy(value); broken[field] = bad
                path = root / "provenance.json"; path.write_text(json.dumps(broken))
                with self.subTest(field=field), self.assertRaises(ValueError):
                    contract.load_runtime_provenance(path, contract.sha(path), source, report, contract.sha(report))

    def test_original_oracle_reuse_requires_original_index_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source, report, value = provenance_fixture(root)
            value["source_witness_source_sha256"] = contract.delta.APPROVED_SHA
            path = root / "provenance.json"; path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "immutable identity"):
                contract.load_runtime_provenance(path, contract.sha(path), source, report, contract.sha(report))
            value["source_witness_sha256"] = contract.ORIGINAL_ORACLE_SHA
            path.write_text(json.dumps(value))
            self.assertEqual(contract.load_runtime_provenance(path, contract.sha(path), source, report, contract.sha(report)), value)

    def test_full_dense_fixture_passes_but_failures_and_threshold_changes_do_not(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, _, value = provenance_fixture(Path(temporary))
            receipt, parity = dense_fixture(value)
            contract.validate_dense_evidence(receipt, parity, value)
            for key, bad in (("samples", 1943), ("source_total_bones_including_helpers", 72),
                             ("skin_vertex_samples", 1944), ("camera_relative_geometry_measured", False),
                             ("passed", 1)):
                other = copy.deepcopy(parity); other[key] = bad
                with self.subTest(key=key), self.assertRaises(ValueError):
                    contract.validate_dense_evidence(receipt, other, value)
            for bad in (1e-4, float("nan"), float("inf"), -1., True):
                other = copy.deepcopy(parity); other["maxima"]["skin_world_m"] = bad
                with self.subTest(value=bad), self.assertRaises(ValueError):
                    contract.validate_dense_evidence(receipt, other, value)
            other = copy.deepcopy(parity); del other["checks"]["animated_camera_bound"]
            with self.assertRaises(ValueError):
                contract.validate_dense_evidence(receipt, other, value)

    def test_export_must_include_camera_all_actors_and_dense_unretimed_clock(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, _, value = provenance_fixture(Path(temporary)); receipt, parity = dense_fixture(value)
            for key, bad in (("selected", contract.SELECTED[:-1]), ("frames", [1, 68]), ("export_bind_frame", 69),
                             ("fbx_bake_step", 1/8), ("source_saved", True), ("rendered", True)):
                other = copy.deepcopy(receipt); other[key] = bad
                with self.subTest(key=key), self.assertRaises(ValueError):
                    contract.validate_dense_evidence(other, parity, value)


class InvocationTests(unittest.TestCase):
    def test_grid_writer_is_exact_lf_bytes_on_every_platform(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "grid.json"
            adapter.write_grid(path)
            self.assertEqual(contract.sha(path), contract.GRID_SHA)
            self.assertNotIn(b"\r", path.read_bytes())
            with self.assertRaises(FileExistsError):
                adapter.write_grid(path)

    def test_dense_index_paths_are_portable_on_windows(self):
        source = Path(adapter.__file__).with_name("export_prone_r15_regenerated_dense.py").read_text()
        expressions = {}
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value in ("row_path", "skin_path"):
                        expressions[key.value] = value
        env = {"P": PureWindowsPath("C:/private/dense"),
               "rp": PureWindowsPath("C:/private/dense/sample-rows/0000.json"),
               "sp": PureWindowsPath("C:/private/dense/skin-rows/0000.npz")}
        for key, expected in (("row_path", "sample-rows/0000.json"), ("skin_path", "skin-rows/0000.npz")):
            value = eval(compile(ast.Expression(expressions[key]), "dense-index", "eval"), {}, env)
            self.assertEqual(value, expected)

    def test_adoption_checks_complete_dense_identity_without_native_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source, proof, provenance = provenance_fixture(root)
            dense = root / "existing-dense"; dense.mkdir()
            args = SimpleNamespace(root=Path(adapter.__file__).resolve().parent.parent, source=source,
                source_equivalence=proof, work=root / "fresh-work", existing_dense=dense, reference_oracle=None)
            for name in (contract.ACTION + ".fbx", "source-samples.json", "paired-camera-contract.json"):
                (dense / name).write_bytes(b"synthetic fixture")
            contract.write(dense / "fbx-take-contract.json", {"matches": True, "animation_stacks": [contract.ACTION],
                "expected_single_stack": contract.ACTION})
            provenance["source_fbx_sha256"] = contract.sha(dense / (contract.ACTION + ".fbx"))
            receipt, parity = dense_fixture(provenance)
            receipt.update(recipes={name: contract.sha(args.root / "tools" / name) for name in
                ("export_prone_r15_regenerated_dense.py", "prone_r15_regenerated_contract.py")},
                source_samples_sha256=contract.sha(dense / "source-samples.json"), oracle_source_sha256=contract.sha(source),
                evidence_sha256={name: contract.sha(dense / name) for name in ("paired-camera-contract.json", "fbx-take-contract.json")})
            contract.write(dense / "export-receipt.json", receipt); contract.write(dense / "fresh-import-parity.json", parity)
            with patch.object(adapter.subprocess, "run") as native:
                self.assertEqual(adapter.validate_existing_dense(args, provenance["source_equivalence_descriptor"]), dense)
                native.assert_not_called()
            for field, bad in (("recipes", {}), ("source_samples_sha256", "0" * 64), ("evidence_sha256", {}),
                               ("source_sha256", contract.delta.APPROVED_SHA)):
                broken = copy.deepcopy(receipt); broken[field] = bad
                (dense / "export-receipt.json").write_text(json.dumps(broken))
                with self.subTest(field=field), self.assertRaises(ValueError):
                    adapter.validate_existing_dense(args, provenance["source_equivalence_descriptor"])
            (dense / "export-receipt.json").write_text(json.dumps(receipt))
            parity["passed"] = False; (dense / "fresh-import-parity.json").write_text(json.dumps(parity))
            with self.assertRaisesRegex(ValueError, "coverage incomplete"):
                adapter.validate_existing_dense(args, provenance["source_equivalence_descriptor"])

    def test_native_invocation_is_background_single_thread_no_autoexec_or_render(self):
        command = adapter.native_command("blender", "export.py", ["export"], "candidate.blend")
        self.assertEqual(command[:7], ["blender", "--background", "--factory-startup", "--disable-autoexec", "--threads", "1", "candidate.blend"])
        self.assertIn("--python-exit-code", command)
        self.assertFalse(any(value in command for value in ("--render-frame", "--render-animation")))

    def test_conversion_keeps_actual_source_hash_and_full_pair(self):
        args = SimpleNamespace(source=Path("candidate.blend"), output=Path("runtime"))
        hashes = {"candidate.blend": "a" * 64, "candidate.fbx": "b" * 64, "camera.json": "c" * 64}
        with patch.object(contract, "sha", side_effect=lambda path: hashes[str(path)]):
            command = adapter.conversion_arguments(args, Path("candidate.fbx"), Path("camera.json"), Path("canonical.vra"))
        self.assertEqual(command[command.index("--source-sha256") + 1], "a" * 64)
        self.assertEqual(command[command.index("--subdivisions") + 1], "64")
        self.assertEqual(command[command.index("--native-end") + 1], "68")
        self.assertEqual(command.count("--actor"), 3)
        self.assertNotIn(contract.delta.APPROVED_SHA, command)

    def test_probe_batches_preserve_every_sample_and_fit_windows(self):
        times = [repr((frame - 1)/60) for frame in contract.grid()]
        commands = []
        def sample(command):
            commands.append(command)
            for value in command[3:-1]:
                yield {"requested": value}
        with patch.object(verifier, "rust_samples", side_effect=sample):
            rows = list(verifier.rust_sample_batches(["x" * 1500, "asset.vra", contract.ACTION], times, ["--clamp"]))
        self.assertEqual([row["requested"] for row in rows], times)
        self.assertEqual(len(commands), 8)
        for command in commands:
            units = len(verifier.subprocess.list2cmdline(command).encode("utf-16-le"))//2 + 1
            self.assertLessEqual(units, 24000)
            self.assertLessEqual(len(command) - 4, 256)

    def test_probe_batch_failure_is_not_partial_success(self):
        def sample(command):
            yield {"time": 0}
            raise verifier.VerificationError("failed batch")
        with patch.object(verifier, "rust_samples", side_effect=sample), self.assertRaisesRegex(ValueError, "failed batch"):
            list(verifier.rust_sample_batches(["sampler"], ["0", "1"]))

    def test_one_oversized_probe_is_rejected_before_execution(self):
        with patch.object(verifier, "rust_samples") as native, self.assertRaisesRegex(ValueError, "single probe"):
            list(verifier.rust_sample_batches(["x" * 24000], ["0"]))
        native.assert_not_called()

    def test_private_native_stage_failure_preserves_failure_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = SimpleNamespace(root=root, work=root, timeout_seconds=30, native_lock=root / "native.lock")
            with patch.object(adapter.subprocess, "run") as native:
                native.return_value.returncode = 9
                with self.assertRaisesRegex(ValueError, "failed"):
                    adapter.run_phase(args, "synthetic", ["never-executed"], native=True)
            receipt = contract.read(root / "synthetic.process.json")
            self.assertFalse(receipt["completed"])
            self.assertEqual(receipt["exit_code"], 9)
            self.assertFalse((root / "native.lock").exists())


if __name__ == "__main__":
    unittest.main()
