"""Bounded evidence uses real tiny companion parsers; no downloads or rendering."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml
import package_game
import package_source_companion_evidence as evidence
import test_blender_pipeline

ROOT = Path(__file__).resolve().parents[1]


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.pack = test_blender_pipeline.BlenderPipelineTests().fixture(self.root)
        source_dir = self.root / "assets/source/reload"
        source_dir.mkdir(parents=True)
        blend = b"public authored test source"
        (source_dir / "current.blend").write_bytes(blend)
        self.contract = json.loads((self.pack / "source.json").read_text())
        self.contract.update(file="current.blend", **evidence.digest(blend))
        self.save_selection(self.pack, self.contract)
        (source_dir / "source.json").write_text(json.dumps(self.contract))
        for name in (evidence.WORKFLOW, evidence.PRODUCER):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, path)
        self.identity = {"run_attempt": 2, "run_id": 123, "source_commit": "a" * 40}

    def save_selection(self, folder, source):
        (folder / "source.json").write_text(json.dumps(source))
        for name, values in (
            ("manifest.json", {"authoring_master_sha256": source["sha256"]}),
            ("export-manifest.json", {"source_sha256": source["sha256"], "action": source["action"]}),
        ):
            path = folder / name
            value = json.loads(path.read_text())
            value.update(values)
            path.write_text(json.dumps(value))

    def validate(self, command, *, cwd, stdout, check):
        self.assertEqual(command[1:], ["tools/check_generated_assets.py", "--kind", "reload",
                                      "--directory", "assets/reload"])
        self.assertEqual(cwd, self.root)
        self.assertEqual(stdout, subprocess.PIPE)
        self.assertTrue(check)
        report = {}
        for key, selected in evidence.selections(self.contract):
            folder = Path("assets/reload") / "alternates" / key if key else Path("assets/reload")
            report[key or "primary"] = package_game.verify_generated_pack(self.root, folder, selected)
        return subprocess.CompletedProcess(command, 0, (json.dumps(report, indent=2) + "\n").encode())

    def package(self):
        with patch.object(evidence.subprocess, "run", side_effect=self.validate):
            return evidence.package(self.root, "assets/reload", "evidence/parts", self.identity)

    def test_exact_bytes_and_shared_receipts_with_all_companion_hashes(self):
        before = {name: (self.pack / name).read_bytes() for name in evidence.FILES}
        receipt = self.package()
        for name in evidence.COMPANIONS:
            part = self.root / "evidence/parts" / name.rsplit(".", 1)[1]
            self.assertEqual({p.name for p in part.iterdir()},
                             {name, *evidence.REPORTS, "receipt.json", "revalidation.json"})
            for filename in (name, *evidence.REPORTS):
                self.assertEqual((part / filename).read_bytes(), before[filename])
            self.assertEqual(json.loads((part / "receipt.json").read_bytes()), receipt)
            validation = (part / "revalidation.json").read_bytes()
            self.assertEqual(receipt["validation"]["sha256"], hashlib.sha256(validation).hexdigest())
            self.assertLessEqual(sum(p.stat().st_size for p in part.iterdir()), evidence.MAX_PART_BYTES)
        self.assertEqual(receipt["input_files"], {name: evidence.digest(data) for name, data in before.items()})
        self.assertEqual(before, {name: (self.pack / name).read_bytes() for name in evidence.FILES})

    def test_total_part_bound_counts_metadata_and_does_not_leave_output(self):
        sizes = [(self.pack / name).stat().st_size for name in evidence.FILES]
        # Each file fits, but the repeated receipt plus files do not.
        with patch.object(evidence, "MAX_PART_BYTES", max(sizes) + 1):
            with self.assertRaisesRegex(ValueError, "including all metadata"):
                self.package()
        self.assertFalse((self.root / "evidence/parts").exists())

    def test_oversize_file_is_rejected_before_validation(self):
        with patch.object(evidence, "MAX_REPORT_BYTES", 16):
            with patch.object(evidence.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "byte bound"):
                    evidence.package(self.root, "assets/reload", "evidence/parts", self.identity)
                run.assert_not_called()

    def test_existing_output_preserved(self):
        output = self.root / "evidence/parts"
        output.mkdir(parents=True)
        marker = output / "original.txt"
        marker.write_bytes(b"preserve me")
        with self.assertRaises(FileExistsError):
            self.package()
        self.assertEqual(marker.read_bytes(), b"preserve me")

    def test_traversal_absolute_and_overlapping_paths_rejected(self):
        for directory, output in (("../reload", "parts"), ("/tmp/reload", "parts"),
                                  ("assets/reload", "../parts"), ("assets/reload", "/tmp/parts"),
                                  ("assets/reload", "assets/reload/parts"),
                                  ("assets/reload", "assets"), ("assets\\reload", "parts")):
            with self.subTest(directory=directory, output=output), self.assertRaises(ValueError):
                evidence.package(self.root, directory, output, self.identity)

    def test_unexpected_file_or_directory_and_missing_file_rejected(self):
        for name in ("private-soldier.blend", "vector-range.exe", "token.txt"):
            path = self.pack / name
            path.write_bytes(b"do not publish")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unexpected input file"):
                self.package()
            path.unlink()
        (self.pack / "unknown").mkdir()
        with self.assertRaisesRegex(ValueError, "unexpected input directory"):
            self.package()
        (self.pack / "unknown").rmdir()
        (self.pack / "asset.vrs").unlink()
        with self.assertRaisesRegex(ValueError, "missing generated files"):
            self.package()

    def test_links_nonregular_files_and_linked_output_ancestors_rejected(self):
        path = self.pack / "asset.vra"
        original = path.read_bytes()
        path.unlink()
        outside = self.root / "outside.vra"
        outside.write_bytes(original)
        try:
            path.symlink_to(outside)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        with self.assertRaisesRegex(ValueError, "link in path"):
            self.package()
        path.unlink()
        os.link(outside, path)
        with self.assertRaisesRegex(ValueError, "regular file"):
            self.package()
        path.unlink()
        if hasattr(os, "mkfifo"):
            os.mkfifo(path)
            with self.assertRaisesRegex(ValueError, "regular file"):
                self.package()
            path.unlink()
        path.write_bytes(original)
        (self.root / "evidence").symlink_to(self.root / "missing", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "link in path"):
            self.package()
        self.assertFalse((self.root / "missing").exists())

    def test_corrupt_companion_and_failed_parity_cannot_publish(self):
        parity_path = self.pack / "parity.json"
        parity = json.loads(parity_path.read_text())
        parity["passed"] = False
        parity_path.write_text(json.dumps(parity))
        with self.assertRaisesRegex(ValueError, "Rust parity"):
            self.package()
        parity["passed"] = True
        parity_path.write_text(json.dumps(parity))
        (self.pack / "asset.vrs").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.package()
        self.assertFalse((self.root / "evidence/parts").exists())

    def test_input_changed_during_validation_cannot_publish(self):
        def change(*args, **kwargs):
            result = self.validate(*args, **kwargs)
            (self.pack / "asset.vrm").write_bytes(b"changed after validation")
            return result
        with patch.object(evidence.subprocess, "run", side_effect=change):
            with self.assertRaisesRegex(ValueError, "changed during validation"):
                evidence.package(self.root, "assets/reload", "evidence/parts", self.identity)
        self.assertFalse((self.root / "evidence/parts").exists())

    def test_all_selected_alternates_required_validated_and_hashed_but_not_copied(self):
        alternate = self.pack / "alternates/opening"
        alternate.mkdir(parents=True)
        for name in evidence.FILES:
            shutil.copyfile(self.pack / name, alternate / name)
        self.contract["additional_selections"] = [{"id": "opening", "action": "opening"}]
        (self.root / "assets/source/reload/source.json").write_text(json.dumps(self.contract))
        self.save_selection(self.pack, self.contract)
        selected = list(evidence.selections(self.contract))[1][1]
        self.save_selection(alternate, selected)
        receipt = self.package()
        self.assertEqual(len(receipt["input_files"]), 14)
        self.assertIn("alternates/opening/asset.vra", receipt["input_files"])
        self.assertFalse(any(path.name == "alternates" for path in (self.root / "evidence/parts").rglob("*")))
        (alternate / "asset.vrm").unlink()
        with self.assertRaisesRegex(ValueError, "missing generated files"):
            evidence.inventory(self.pack, self.contract)

    def test_real_cli_revalidates_all_inputs_and_binds_clean_github_identity(self):
        # Exercise the actual unchanged check_generated_assets entry point.
        shutil.copytree(ROOT / "assets/locomotion", self.root / "assets/locomotion")
        scripts = ("check_generated_assets.py", "build_blender_assets.py", "package_game.py",
                   "vrpack.py", "vrskin.py", "vrview.py", "merge_walk_clip.py",
                   "exclusive_output.py", "package_source_companion_evidence.py")
        (self.root / "tools").mkdir()
        for name in scripts:
            shutil.copyfile(ROOT / "tools" / name, self.root / "tools" / name)
        for command in (["git", "init", "-q"], ["git", "add", "."],
                        ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                         "commit", "-qm", "Public test fixture"]):
            subprocess.run(command, cwd=self.root, check=True)
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.root, text=True).strip()
        env = dict(os.environ, GITHUB_ACTIONS="true", GITHUB_SERVER_URL="https://github.com",
                   GITHUB_REPOSITORY=evidence.REPOSITORY, GITHUB_REF="refs/heads/main",
                   GITHUB_WORKFLOW_REF=f"{evidence.REPOSITORY}/{evidence.WORKFLOW}@refs/heads/main",
                   GITHUB_SHA=sha, GITHUB_WORKFLOW_SHA=sha, GITHUB_EVENT_NAME="workflow_dispatch",
                   GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="2")
        command = [sys.executable, "tools/package_source_companion_evidence.py",
                   "--directory", "assets/reload", "--output", "evidence/parts"]
        result = subprocess.run(command, cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads((self.root / "evidence/parts/vra/receipt.json").read_text())
        self.assertEqual(receipt["origin"]["source_commit"], sha)
        self.assertEqual(receipt["origin"]["input_artifact"], "generated-reload-runtime-attempt-2")
        self.assertEqual(receipt["origin"]["full_canonical_artifact"], "generated-reload-runtime")
        self.assertEqual(receipt["origin"]["full_attempt_artifact"], "generated-reload-runtime-attempt-2")
        for key, value in (("GITHUB_REPOSITORY", "other/repo"), ("GITHUB_REF", "refs/heads/other"),
                           ("GITHUB_WORKFLOW_SHA", "0" * 40), ("GITHUB_RUN_ID", "0"),
                           ("GITHUB_EVENT_NAME", "pull_request"), ("GITHUB_WORKFLOW_REF", "other"),
                           ("GITHUB_SHA", "1" * 40)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                evidence.github_identity(self.root, dict(env, **{key: value}))
        (self.root / evidence.PRODUCER).write_text("changed")
        with self.assertRaisesRegex(ValueError, "clean current caller"):
            evidence.github_identity(self.root, env)


class WorkflowTests(unittest.TestCase):
    def test_current_run_producer_dependency_and_no_cross_run_retrieval(self):
        workflow = yaml.safe_load((ROOT / evidence.WORKFLOW).read_text())
        trigger = workflow.get("on", workflow.get(True))  # YAML 1.1 parses 'on' as True.
        self.assertEqual(set(trigger), {"push", "workflow_dispatch"})
        self.assertEqual(trigger["push"]["branches"], ["main"])
        self.assertEqual(set(trigger["push"]["paths"]), {
            evidence.WORKFLOW, "tools/package_source_companion_evidence.py",
            "tools/test_source_companion_evidence.py"})
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        jobs = workflow["jobs"]
        self.assertEqual(set(jobs), {"produce", "evidence"})
        self.assertEqual(jobs["produce"], {"if": "github.ref == 'refs/heads/main'",
                                          "uses": "./.github/workflows/blender-assets.yml"})
        self.assertEqual(jobs["evidence"]["needs"], "produce")
        steps = jobs["evidence"]["steps"]
        downloads = [step for step in steps if step.get("uses") == "actions/download-artifact@v4"]
        self.assertEqual(len(downloads), 1)
        self.assertEqual(downloads[0]["with"], {"name": "generated-reload-runtime-attempt-${{ github.run_attempt }}",
                                               "path": "evidence/current-reload-runtime"})
        runs = [step for step in steps if "run" in step]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["run"], "python tools/package_source_companion_evidence.py "
                         "--directory evidence/current-reload-runtime --output evidence/source-companion-parts")
        uploads = [step for step in steps if step.get("uses") == "actions/upload-artifact@v4"]
        self.assertEqual(len(uploads), 3)
        self.assertLess(steps.index(downloads[0]), steps.index(runs[0]))
        for step, suffix in zip(uploads, ("vra", "vrs", "vrm")):
            self.assertLess(steps.index(runs[0]), steps.index(step))
            self.assertEqual(step["with"], {
                "name": f"renderer-source-reload-{suffix}-attempt-${{{{ github.run_attempt }}}}",
                "path": f"evidence/source-companion-parts/{suffix}/", "if-no-files-found": "error",
                "compression-level": 0, "retention-days": 7})
            self.assertNotIn("if", step)  # Publication requires successful validation.
        text = (ROOT / evidence.WORKFLOW).read_text()
        for forbidden in ("continue-on-error", "always()", "run-id:", "github-token:", "secrets:",
                          "contents: write", "actions: write", "fetch_source", "cargo build"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
