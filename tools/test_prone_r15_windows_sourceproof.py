"""Synthetic orchestration tests only; no Blender, Cargo, game or network calls."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import run_prone_r15_windows_sourceproof as proof


class ProofContractTests(unittest.TestCase):
    def test_scaffold_is_explicitly_not_admitted(self):
        with patch.object(proof, "ADMISSION_SHA256", None), patch.object(proof.subprocess, "run") as native:
            with self.assertRaisesRegex(ValueError, "BLOCKED.*not admitted"):
                proof.preflight(Path("."))
            native.assert_not_called()

    def test_environment_cannot_enable_scaffold(self):
        with patch.object(proof, "ADMISSION_SHA256", None), patch.dict(os.environ, {"PRONE_R15_ADMITTED": "true", "ADMISSION_SHA256": "a" * 64}):
            with self.assertRaisesRegex(ValueError, "BLOCKED"):
                proof.preflight(Path("."))

    def test_preflight_cli_returns_failure_without_native_job(self):
        with patch.object(proof, "ADMISSION_SHA256", None), contextlib.redirect_stderr(io.StringIO()), patch.object(proof.subprocess, "run") as native:
            self.assertEqual(proof.main(["preflight"]), 1)
            native.assert_not_called()

    def test_run_cannot_be_claimed_on_non_windows(self):
        with patch.object(proof.sys, "platform", "linux"), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(proof.main(["run", "--base", "b", "--blender", "x", "--blender-receipt", "r",
                                        "--work", "w", "--evidence", "e"]), 1)

    def test_digest_and_path_rejections(self):
        for value in (None, True, "", "0" * 63, "A" * 64, "g" * 64):
            with self.subTest(value=value), self.assertRaises(ValueError):
                proof.digest(value)
        for value in ("/tmp/x", "../x", "a/../b", "a//b", "a/./b", "C:/secret", "a\\b", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                proof.relative(value)
        self.assertEqual(proof.relative("safe/source.json"), Path("safe/source.json"))

    def test_duplicate_keys_and_nonfinite_json_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.json"
            for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
                path.write_text(text)
                with self.subTest(text=text), self.assertRaises(ValueError):
                    proof.read(path)

    def test_file_pin_checks_actual_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "data.json"
            path.write_text('{"value":1}')
            pin = {"path": "data.json", "sha256": proof.sha(path)}
            self.assertEqual(proof.pinned(root, pin), path)
            path.write_text('{"value":2}')
            with self.assertRaisesRegex(ValueError, "pinned bytes differ"):
                proof.pinned(root, pin)

    def test_linked_parent_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "real").mkdir()
            (root / "real/data.json").write_text("{}")
            try:
                (root / "link").symlink_to(root / "real", target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation not permitted on this host")
            with self.assertRaisesRegex(ValueError, "linked"):
                proof.regular(root / "link/data.json")

    def test_runtime_capture_is_actual_dx12_native_gameplay(self):
        for hz, count in ((60, 283), (30, 142)):
            self.assertEqual(proof.RATES[hz], count)
            command = proof.capture_command("game.exe", "isolated/animations.cfg", "capture", hz, "a" * 64)
            for flag in ("--renderer=dx12", "--force-fallback-adapter", "--capture-native-window",
                         "--capture-sequence=gameplay-prone", "--no-update", f"--capture-hz={hz}"):
                self.assertIn(flag, command)
            self.assertNotIn("--reference-viewport", command)
            self.assertFalse(any("renderer=gl" in flag for flag in command))
        with self.assertRaises(ValueError):
            proof.capture_command("game", "manifest", "output", 120, "a" * 64)

    def test_publication_rejects_private_extensions_and_unexpected_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("candidate.blend", "candidate.fbx", "source-witness.npz", "asset.vra", "stdout.log", "extra.json"):
                path = root / name
                path.write_text("private")
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "publication artifact"):
                    proof.evidence_inventory(root)
                path.unlink()
            (root / "60").mkdir()
            (root / "60/0000.png").write_bytes(b"synthetic-inventory-only")
            (root / "summary.json").write_text("{}")
            self.assertEqual(set(proof.evidence_inventory(root)), {"60/0000.png"})

    def test_delta_transport_checks_manifest_and_reassembled_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / proof.INPUT_DIRECTORY / "delta"
            folder.mkdir(parents=True)
            manifest = folder / "manifest.json"; manifest.write_text("{}")
            data = b'{"synthetic":"source-only"}'
            item = {"manifest_path": manifest.relative_to(root).as_posix(),
                    "manifest_sha256": proof.sha(manifest), "sha256": proof.hashlib.sha256(data).hexdigest()}
            with patch("prone_r15_delta_transport.assemble_bytes", return_value=data) as assemble:
                self.assertEqual(proof.delta_bytes(root, item), data)
                assemble.assert_called_once_with(manifest, item["manifest_sha256"])
                item["sha256"] = "0" * 64
                with self.assertRaisesRegex(ValueError, "reassembled"):
                    proof.delta_bytes(root, item)

    def test_blender_receipt_cannot_use_secondary_url_or_forged_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exe = root / "blender.exe"
            exe.write_bytes(b"synthetic")
            receipt = {"schema": "rust-duty-prone-r15-blender-toolchain/v1", "version": "4.3.2",
                       "vendor_checksum_url": "https://scoop.sh/manifest.json"}
            with self.assertRaisesRegex(ValueError, "Blender receipt differs"):
                proof.verify_blender(receipt, exe)

    def test_stream_hash_can_use_explicit_archive_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "archive.zip"
            path.write_bytes(b"synthetic-archive")
            with patch.object(proof, "regular", wraps=proof.regular) as bounded:
                proof.sha(path, proof.BLENDER_BYTES)
                bounded.assert_called_once_with(path, proof.BLENDER_BYTES)
            self.assertGreater(proof.BLENDER_BYTES, 256 * 1024 * 1024)
            with self.assertRaises(ValueError):
                proof.sha(path, 1)

    def test_isolated_manifest_copies_only_runtime_companions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "assets").mkdir()
            manifest = root / "assets/animations.cfg"
            manifest.write_text("schema=test\nlocomotion.asset=locomotion/asset.vra\nreload.tactical.asset=reload/asset.vra\n")
            original = proof.sha(manifest)
            for folder in ("locomotion", "reload"):
                (root / "assets" / folder).mkdir()
                for suffix in ("vra", "vrs", "vrm"):
                    (root / "assets" / folder / ("asset." + suffix)).write_bytes(b"synthetic")
            (root / "runtime").mkdir()
            for name in proof.RUNTIME_FILES:
                (root / "runtime" / name).write_bytes(b"synthetic")
            (root / "runtime/private.blend").write_bytes(b"private")
            output = proof.isolated_manifest(root, root / "runtime", root / "isolated")
            self.assertIn("prone_entry.policy=paired_r15_wip", output.read_text())
            self.assertEqual(proof.sha(manifest), original)
            self.assertFalse(any(p.suffix == ".blend" for p in output.parent.rglob("*")))

    def test_default_activation_and_traversal_rejected_before_copy(self):
        for line in ("prone_entry.policy=paired_r15_wip", "locomotion.asset=../private.vra"):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "assets").mkdir()
                (root / "assets/animations.cfg").write_text(line + "\n")
                with self.subTest(line=line), self.assertRaises(ValueError):
                    proof.isolated_manifest(root, root / "runtime", root / "isolated")

    def test_native_failure_is_not_completion_and_logs_stay_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work, evidence = root / "work", root / "evidence"
            work.mkdir(); evidence.mkdir()
            report = {"passed": False, "stages": []}
            runner = proof.Runner(root, work, evidence, report)
            with patch.object(proof.subprocess, "run") as native:
                native.return_value.returncode = 7
                with self.assertRaisesRegex(ValueError, "failed"):
                    runner.run("synthetic", ["never-executed"])
            self.assertFalse(report["stages"][0]["completed"])
            self.assertEqual(report["stages"][0]["exit_code"], 7)
            self.assertEqual(set(p.name for p in evidence.iterdir()), {"summary.json"})
            self.assertTrue((work / "synthetic.log").exists())


class WorkflowSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.workflow = (cls.root / ".github/workflows/prone-r15-windows-sourceproof.yml").read_text()

    def test_independent_non_canceling_branch_lane(self):
        self.assertIn("group: prone-r15-sourceproof-${{ github.head_ref || github.ref_name }}", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)
        self.assertIn("  pull_request:", self.workflow)
        self.assertIn("  workflow_dispatch:", self.workflow)
        self.assertNotIn("  push:", self.workflow)
        self.assertNotIn("branches:", self.workflow)
        self.assertIn("startsWith(github.head_ref, 'aella/prone-r15-sourceproof-')", self.workflow)
        self.assertNotIn("pull_request_target:", self.workflow)
        self.assertNotIn("contents: write", self.workflow)

    def test_all_companions_wait_on_admission_and_use_same_run(self):
        for name in ("reload", "walk", "ads", "directional", "jump"):
            self.assertIn(f"name: generated-{name}-runtime", self.workflow)
        self.assertNotIn("run-id:", self.workflow)
        self.assertNotIn("github-token:", self.workflow)
        self.assertIn("needs: [admission, reload, walk, ads, directional, jump]", self.workflow)
        self.assertIn("run_prone_r15_windows_sourceproof.py preflight", self.workflow)

    def test_vendor_checksum_fails_closed_and_upload_is_allowlisted(self):
        self.assertIn('Invoke-WebRequest "$base/blender-$env:BLENDER_VERSION.sha256"', self.workflow)
        self.assertIn("$matches.Count -ne 1", self.workflow)
        self.assertIn("405138423", self.workflow)
        uploads = self.workflow.split("uses: actions/upload-artifact@v4")
        self.assertEqual(len(uploads), 2)
        upload = uploads[1]
        self.assertIn("summary.json", upload)
        self.assertNotIn(".blend", upload)
        self.assertNotIn(".fbx", upload)
        self.assertNotIn(".npz", upload)
        self.assertNotIn("RUNNER_TEMP", upload)
        self.assertNotIn("path: .", upload)
        self.assertNotIn("**", upload)

    def test_adapter_is_explicit_reviewed_code_prerequisite(self):
        self.assertIn(proof.ADAPTER_PATH, proof.MINIMUM_CODE_PINS)
        self.assertEqual(proof.ADAPTER_PATH, "tools/produce_prone_r15_regenerated_runtime.py")


if __name__ == "__main__":
    unittest.main()
