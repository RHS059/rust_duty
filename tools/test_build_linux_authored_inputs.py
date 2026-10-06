#!/usr/bin/env python3
"""Offline contract tests: no Blender generation, compilation or network."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import build_linux_authored_inputs as build


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.source = base / "source"
        self.jump = base / "jump"
        self.output = base / "output"
        self.source.mkdir()
        self.jump.mkdir()
        self.immutable = {"src/main.rs": b"original production Rust\n", "ui/theme.css": b"original UI\n"}
        for name, raw in self.immutable.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        jump = self.jump / "halcyon_jump.blend"
        jump.write_bytes(b"test immutable jump source")
        self.blender = base / "blender"
        self.blender.write_bytes(b"supplied Blender")
        self.blender.chmod(0o755)
        self.sampler = base / "sampler"
        elf = bytearray(64)
        elf[:6] = b"\x7fELF\x02\x01"
        elf[18:20] = b"\x3e\x00"
        self.sampler.write_bytes(elf)
        self.sampler.chmod(0o755)
        self.argv = ["--source", str(self.source), "--output", str(self.output),
                     "--blender", str(self.blender), "--sampler", str(self.sampler),
                     "--jump-source-dir", str(self.jump)]
        self.patches = [mock.patch.object(build, "PINNED_FILES", {
                            n: build.record(self.source / n) for n in self.immutable}),
                        mock.patch.object(build, "PRODUCTION_FILES", tuple(self.immutable)),
                        mock.patch.object(build, "JUMP_RECORD", build.record(jump))]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def valid(self):
        args = build.parse_args(self.argv)
        with mock.patch.object(build.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "Blender 4.3.2\n", "")):
            inputs = build.preflight(args)
        return args, inputs

    def test_plan_preserves_dependency_order_and_no_render_compile_network(self):
        args, _ = self.valid()
        plan = build.build_plan(args)
        names = [s["name"] for s in plan]
        self.assertEqual(names[0], "materialize-locomotion")
        self.assertLess(names.index("parity-reload"), names.index("validate-reload"))
        for group in ("ads", "directional", "jump"):
            self.assertLess(names.index("stage-walk"), names.index("build-" + group))
        for group in ("reload", "walk", "ads", "directional", "jump"):
            self.assertLess(names.index("validate-" + group), names.index("stage-" + group))
        self.assertEqual(names[-1], "validate-complete-staged-assets")
        final = plan[-1]["argv"]
        for flag in ("--include-walk", "--include-ads", "--include-directional", "--include-jump", "--require-generated"):
            self.assertIn(flag, final)
        commands = [s["argv"] for s in plan if s["kind"] == "command"]
        self.assertTrue(all(argv[0] == build.sys.executable and argv[1] == "-B" for argv in commands))
        self.assertFalse(any(word in {"curl", "wget", "git", "cargo", "render", "--render-frame", "--render-anim"}
                             for argv in commands for word in argv))
        jump = next(s for s in plan if s["name"] == "build-jump")["argv"]
        self.assertEqual(jump[jump.index("--source-dir") + 1], str(self.jump))

    def test_missing_or_modified_inputs_fail_before_external_execution(self):
        for kind in ("missing", "changed"):
            path = self.source / "src/main.rs"
            if kind == "missing":
                path.unlink()
            else:
                path.write_bytes(b"changed")
            with mock.patch.object(build.subprocess, "run") as run:
                with self.assertRaises(build.BuildFailure):
                    build.preflight(build.parse_args(self.argv))
                run.assert_not_called()
            path.write_bytes(self.immutable["src/main.rs"])
        self.assertFalse(self.output.exists())

    def test_wrong_blender_version_prevents_producer_execution(self):
        with mock.patch.object(build.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "Blender 4.3.21\n", "")) as run:
            with self.assertRaisesRegex(build.BuildFailure, "exact Blender"):
                build.preflight(build.parse_args(self.argv))
            self.assertEqual(run.call_args.args[0], [str(self.blender), "--version"])
            self.assertEqual(run.call_count, 1)
        self.assertFalse(self.output.exists())

    def test_main_preserves_preflight_rejection_without_running_producers(self):
        (self.source / "src/main.rs").unlink()
        with mock.patch.object(build.subprocess, "run") as external:
            with mock.patch.object(build, "run_build") as producer, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(build.main(self.argv), 1)
                external.assert_not_called()
                producer.assert_not_called()
        result = json.loads((self.output / "ASSET_BUILD_RESULT.json").read_text())
        self.assertEqual((result["status"], result["phase"], result["commands"]), ("failed", "preflight", []))

    def test_source_symlink_and_wrong_jump_fail_before_execution(self):
        original = self.source / "src/main.rs"
        external = Path(self.temp.name) / "outside.rs"
        external.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(external)
        with mock.patch.object(build.subprocess, "run") as run:
            with self.assertRaisesRegex(build.BuildFailure, "Symlink"):
                build.preflight(build.parse_args(self.argv))
            run.assert_not_called()
        original.unlink()
        original.write_bytes(self.immutable["src/main.rs"])
        (self.jump / "halcyon_jump.blend").write_bytes(b"wrong historical source")
        with mock.patch.object(build.subprocess, "run") as run:
            with self.assertRaisesRegex(build.BuildFailure, "Historical jump"):
                build.preflight(build.parse_args(self.argv))
            run.assert_not_called()

    def test_output_must_be_fresh_and_disjoint(self):
        for output in (self.source / "work", self.jump / "work", self.source, Path(self.temp.name)):
            args = build.parse_args(self.argv)
            args.output = output
            with self.assertRaises(build.BuildFailure):
                build.preflight(args)

    def test_dry_run_has_no_mutating_execution_or_output(self):
        with mock.patch.object(build.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "Blender 4.3.2\n", "")) as run:
            with mock.patch.object(build, "run_build") as produce, contextlib.redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(build.main(self.argv + ["--dry-run"]), 0)
                self.assertEqual(json.loads(stdout.getvalue())["status"], "preflight_passed")
                produce.assert_not_called()
            self.assertEqual(run.call_count, 1)
        self.assertFalse(self.output.exists())

    def test_staging_preserves_existing_readme_and_rejects_code_or_links(self):
        origin = Path(self.temp.name) / "runtime"
        destination = self.source / "assets/walk"
        origin.mkdir()
        destination.mkdir(parents=True)
        (origin / "asset.vra").write_bytes(b"new generated companion")
        (destination / "README.md").write_bytes(b"committed documentation")
        rows = build.stage_data(origin, destination)
        self.assertEqual(rows["asset.vra"], build.record(destination / "asset.vra"))
        self.assertEqual((destination / "README.md").read_bytes(), b"committed documentation")
        (origin / "unexpected.py").write_bytes(b"code")
        with self.assertRaisesRegex(build.BuildFailure, "Unexpected producer"):
            build.stage_data(origin, destination)
        (origin / "unexpected.py").unlink()
        (origin / "linked.json").symlink_to(origin / "asset.vra")
        with self.assertRaisesRegex(build.BuildFailure, "Symlink"):
            build.stage_data(origin, destination)

    def test_nonzero_producer_retains_failed_receipt_and_never_stages(self):
        args, inputs = self.valid()
        plan = [{"name": "build-walk", "kind": "command", "group": "walk", "argv": ["mock-producer"]},
                {"name": "stage-walk", "kind": "stage", "group": "walk", "from": "/unused", "to": "/unused"}]
        with mock.patch.object(build, "run_logged_command", return_value=17):
            with mock.patch.object(build, "stage_data") as stage, contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(build.BuildFailure):
                    build.run_build(args, inputs, plan)
                stage.assert_not_called()
        result = json.loads((self.output / "ASSET_BUILD_RESULT.json").read_text())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["commands"][0]["exit_code"], 17)
        self.assertEqual(result["groups"]["walk"]["failed_step"], "build-walk")
        self.assertTrue(result["production_files_preserved"])
        self.assertEqual((self.output / "receipt.json").read_bytes(), (self.output / "ASSET_BUILD_RESULT.json").read_bytes())

    def test_production_mutation_fails_after_nominal_command_success(self):
        args, inputs = self.valid()
        def mutate(*unused, **kwargs):
            (self.source / "src/main.rs").write_bytes(b"unexpected mutation")
            return 0
        plan = [{"name": "mock", "kind": "command", "group": None, "argv": ["mock"]}]
        with mock.patch.object(build, "run_logged_command", side_effect=mutate), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(build.BuildFailure):
                build.run_build(args, inputs, plan)
        result = json.loads((self.output / "ASSET_BUILD_RESULT.json").read_text())
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["production_files_preserved"])
        self.assertIn("src/main.rs", result["integrity_error"])

    def test_timeout_terminates_producer_process_group(self):
        process = mock.Mock()
        process.pid = 12345
        process.wait.side_effect = [subprocess.TimeoutExpired(["producer"], 5400), 0]
        process.poll.return_value = None
        with mock.patch.object(build.subprocess, "Popen", return_value=process) as popen:
            with mock.patch.object(build.os, "killpg") as kill:
                with self.assertRaisesRegex(build.BuildFailure, "exceeded 5400"):
                    build.run_logged_command(["producer"], self.source, io.BytesIO(), {})
                kill.assert_called_once_with(12345, build.signal.SIGTERM)
            self.assertTrue(popen.call_args.kwargs["start_new_session"])


if __name__ == "__main__":
    unittest.main()
