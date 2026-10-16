"""CPU-only synthetic admission tests. No native launch or source asset copies."""
import copy
import importlib
import json
import marshal
from pathlib import Path
import shutil
import struct
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import portable_source as p
CORE = p.load_core(HERE.parent)
d, runner = CORE.delta, CORE.runner
fixtures = ModuleType("test_onehand_v6_source_proof")
fixtures.__file__ = str(HERE.parent / "test_onehand_v6_source_proof.py")
exec(compile(Path(fixtures.__file__).read_bytes(), fixtures.__file__, "exec"), fixtures.__dict__)


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class PortableConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="portable-config-", dir=HERE)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_frozen_package_imports_without_bpy_or_subprocess_execution(self):
        core = p.load_core(HERE.parent)
        self.assertEqual(len(core.pins), 9)
        self.assertNotIn("bpy", sys.modules)
        import ast
        tree = ast.parse((HERE / "portable_source.py").read_text())
        imported = {n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)}
        self.assertNotIn("subprocess", imported)
        self.assertNotIn("bpy", imported)

    def test_changed_manifest_rejected_before_import(self):
        package = self.root / "package"; package.mkdir()
        (package / "PINS.json").write_text("{}\n")
        with patch("builtins.compile") as imported:
            with self.assertRaisesRegex(ValueError, "file bytes differ"):
                p.load_core(package)
            imported.assert_not_called()

    def test_crlf_rewrite_of_core_rejected_before_import(self):
        package = self.root / "package"; package.mkdir()
        for name in (*p.PACKAGE_FILES, "PINS.json"):
            shutil.copyfile(HERE.parent / name, package / name)
        target = package / "onehand_v6_source_native.py"
        target.write_bytes(target.read_bytes().replace(b"\n", b"\r\n"))
        with patch("builtins.compile") as imported:
            with self.assertRaisesRegex(ValueError, "file bytes differ"):
                p.load_core(package)
            imported.assert_not_called()

    def test_mutated_same_path_loaded_module_is_replaced_from_verified_source(self):
        previous = p.load_core(HERE.parent)
        original = previous.delta.probe_times
        previous.delta.probe_times = lambda: ["unverified implementation"]
        try:
            fresh = p.load_core(HERE.parent)
            self.assertIsNot(fresh.delta, previous.delta)
            self.assertEqual(len(fresh.delta.probe_times()), 4240)
        finally:
            previous.delta.probe_times = original

    def test_timestamp_valid_poisoned_pycache_is_never_executed(self):
        package = self.root / "cache package"; package.mkdir()
        for name in (*p.PACKAGE_FILES, "PINS.json"):
            shutil.copyfile(HERE.parent / name, package / name)
        source = package / "onehand_v6_source_delta.py"
        cache = Path(importlib.util.cache_from_source(str(source))); cache.parent.mkdir()
        code = compile("raise RuntimeError('poisoned cache executed')", str(source), "exec")
        cache.write_bytes(importlib.util.MAGIC_NUMBER + struct.pack("<III", 0,
                          int(source.stat().st_mtime) & 0xffffffff, source.stat().st_size) + marshal.dumps(code))
        before = cache.read_bytes()
        with patch.dict(sys.modules):
            for name in ("onehand_v6_source_delta", "onehand_v6_source_native", "run_onehand_v6_source_proof"):
                sys.modules.pop(name, None)
            core = p.load_core(package)
            self.assertEqual(len(core.delta.probe_times()), 4240)
        self.assertEqual(cache.read_bytes(), before)

    def test_symlink_redirect_rejected(self):
        target = self.root / "target"; target.write_bytes(b"content")
        link = self.root / "redirect"
        try:
            link.symlink_to(target)
        except OSError as error:
            self.skipTest(str(error))
        with self.assertRaisesRegex(ValueError, "symlink/reparse"):
            p.pinned_file(link, p.sha(target))

    def test_windows_reparse_attribute_rejected(self):
        with patch.object(Path, "lstat", return_value=SimpleNamespace(st_mode=0o100644, st_file_attributes=0x400)):
            with self.assertRaisesRegex(ValueError, "symlink/reparse"):
                p.ordinary_path(self.root / "junction")

    def test_duplicate_or_nonfinite_json_rejected(self):
        target = self.root / "input.json"
        for value in ('{"a":1,"a":2}', '{"a":NaN}'):
            target.write_text(value)
            with self.assertRaises(ValueError): p.strict_json(target)

    def test_import_from_other_package_rejected(self):
        with patch.dict(sys.modules, {"onehand_v6_source_delta": SimpleNamespace(__file__="/other/package.py")}):
            with self.assertRaisesRegex(ValueError, "another package"):
                p.load_core(HERE.parent)

    def test_future_native_package_rejects_bytecode_and_shadow_modules(self):
        for item in ("__pycache__", "json.py", "evil.PYD", "math.so"):
            with tempfile.TemporaryDirectory(dir=self.root) as folder:
                package = Path(folder)
                if item == "__pycache__": (package / item).mkdir()
                else: (package / item).write_bytes(b"never executed")
                with self.assertRaises(ValueError): p.cache_free_execution_package(package)
        for init in ("__init__.py", "__init__.cp311-win_amd64.pyd", "__init__.cpython-311-x86_64-linux-gnu.so"):
            with tempfile.TemporaryDirectory(dir=self.root) as folder:
                package = Path(folder)
                shadow = package / "json"; shadow.mkdir(); (shadow / init).write_text("never executed")
                with self.assertRaisesRegex(ValueError, "importable source-package directory"):
                    p.cache_free_execution_package(package)


class PortableEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="portable-synthetic-", dir=HERE)
        cls.root = Path(cls.temp.name)
        cls.work = cls.root / "proof with spaces ü"; cls.work.mkdir()
        cls.base = cls.root / "baseline.blend"; cls.base.write_bytes(b"SYNTHETIC BASE IDENTITY")
        cls.approved = cls.root / "approved.blend"; cls.approved.write_bytes(b"SYNTHETIC APPROVED IDENTITY")
        cls.delta_file = cls.root / "original-delta.json"
        cls.recipe = fixtures.synthetic_recipe()
        dump(cls.delta_file, cls.recipe)
        cls.delta_sha = p.sha(cls.delta_file)
        cls.generated = cls.work / "regenerated-onehand-v6.blend"
        cls.generated.write_bytes(b"SYNTHETIC NEW SERIALIZED IDENTITY ONLY")
        cls.replay = fixtures.synthetic_replay(cls.recipe)
        cls.replay["delta_sha256"] = cls.delta_sha
        cls.replay["generated_source_sha256"] = p.sha(cls.generated)
        dump(cls.work / "replay-receipt.json", cls.replay)
        index = {}
        for i in range(17):
            for kind in ("approved", "regenerated"):
                name = f"{kind}-{i:03}.json"
                dump(cls.work / name, fixtures.synthetic_witness(cls.recipe, cls.replay, kind, i))
                index[name] = p.sha(cls.work / name)
        dump(cls.work / "witness-index.json", index)
        args = SimpleNamespace(delta=cls.delta_file, delta_sha256=cls.delta_sha,
            replay_receipt=cls.work / "replay-receipt.json", replay_receipt_sha256=p.sha(cls.work / "replay-receipt.json"),
            witness_index=cls.work / "witness-index.json", witness_index_sha256=p.sha(cls.work / "witness-index.json"),
            directory=cls.work, output=cls.work / "source-equivalence.json")
        dump(args.output, runner.build_equivalence_result(args))
        cls.pins = {"generated_source_sha256": p.sha(cls.generated),
            "replay_receipt_sha256": p.sha(args.replay_receipt), "witness_index_sha256": p.sha(args.witness_index),
            "source_equivalence_sha256": p.sha(args.output)}
        cls.blender = cls.root / "Blender fake.exe"; cls.blender.write_bytes(b"SYNTHETIC TOOL; NEVER EXECUTED")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.originals = {}
        self.pins_now = copy.deepcopy(self.pins)
        self.delta_patch = patch.object(p, "DELTA_SHA", self.delta_sha); self.delta_patch.start()
        original = p.pinned_file
        def synthetic_inputs(path, expected):
            if Path(path) == self.base:
                self.assertEqual(expected, p.BASE_SHA); return self.base
            if Path(path) == self.approved:
                self.assertEqual(expected, p.APPROVED_SHA); return self.approved
            return original(path, expected)
        self.input_patch = patch.object(p, "pinned_file", side_effect=synthetic_inputs)
        self.input_patch.start()
        self.ctx = p.context(self.args())

    def tearDown(self):
        self.input_patch.stop(); self.delta_patch.stop()
        for path, data in self.originals.items(): path.write_bytes(data)

    def args(self, root=None):
        python = Path(sys.executable).resolve()
        return SimpleNamespace(source_package=HERE.parent, baseline=self.base, approved=self.approved,
            delta=self.delta_file, directory=root or self.work, blender=self.blender,
            blender_sha256=p.sha(self.blender), python=python, python_sha256=p.sha(python),
            lock=self.root / "shared-owner.lock")

    def change(self, name, value=None, remove=False):
        path = self.work / name
        self.originals.setdefault(path, path.read_bytes())
        if remove: path.unlink()
        else: dump(path, value)

    def admit(self):
        return p.admit_outputs(self.ctx, self.pins_now)

    def test_full_34_file_4240_admission_is_read_only(self):
        before = {f.name: (f.stat().st_mtime_ns, p.sha(f)) for f in self.work.iterdir()}
        result = self.admit()
        self.assertEqual(result["sample_count"], 4240)
        self.assertEqual(result["chunk_pairs"], 17)
        self.assertTrue(result["evaluated_source_equivalence_proved"])
        self.assertFalse(result["runtime_equivalence_proved"])
        self.assertFalse(result["windows_execution_proved"])
        self.assertFalse(result["input_admission"]["publication_authorized"])
        self.assertFalse(result["runtime_handoff"]["substitute_regenerated_source"])
        self.assertEqual(before, {f.name: (f.stat().st_mtime_ns, p.sha(f)) for f in self.work.iterdir()})

    def test_all_four_external_output_pins_required(self):
        self.pins_now.pop("witness_index_sha256")
        with self.assertRaisesRegex(ValueError, "four explicit"): self.admit()

    def test_generated_bytes_must_match_explicit_pin_and_receipt(self):
        self.change(self.generated.name, {"substituted": True})
        self.pins_now["generated_source_sha256"] = p.sha(self.generated)
        with self.assertRaisesRegex(ValueError, "actual generated bytes"): self.admit()

    def test_historical_generated_sha_is_not_portable_output_identity(self):
        self.assertNotEqual(self.pins_now["generated_source_sha256"], p.HISTORICAL_GENERATED_SHA)
        self.pins_now["generated_source_sha256"] = p.HISTORICAL_GENERATED_SHA
        with self.assertRaisesRegex(ValueError, "file bytes differ"): self.admit()

    def test_minimal_completion_summary_fails_even_with_updated_file_pin(self):
        proof = d.load_json(self.work / "source-equivalence.json")
        self.change("source-equivalence.json", {k: proof[k] for k in
            ("passed", "generated_source_sha256", "sample_count", "delta_sha256")})
        self.pins_now["source_equivalence_sha256"] = p.sha(self.work / "source-equivalence.json")
        with self.assertRaisesRegex(ValueError, "full current sealed evidence"): self.admit()

    def test_stale_external_proof_pin_fails(self):
        proof = d.load_json(self.work / "source-equivalence.json"); proof["extra"] = True
        self.change("source-equivalence.json", proof)
        with self.assertRaisesRegex(ValueError, "file bytes differ"): self.admit()

    def test_stale_replay_receipt_pin_fails(self):
        value = d.load_json(self.work / "replay-receipt.json"); value["passed"] = False
        self.change("replay-receipt.json", value)
        with self.assertRaisesRegex(ValueError, "file bytes differ"): self.admit()

    def test_missing_final_chunk_is_never_complete(self):
        self.change("regenerated-016.json", remove=True)
        with self.assertRaises(FileNotFoundError): self.admit()

    def test_five_pairs_cannot_be_admitted_as_complete(self):
        for i in range(5,17):
            for kind in ("approved", "regenerated"):
                self.change(f"{kind}-{i:03}.json", remove=True)
        with self.assertRaises(FileNotFoundError): self.admit()

    def test_coherently_replaced_pair_with_stale_seal_fails(self):
        for kind in ("approved", "regenerated"):
            name = f"{kind}-000.json"; value = d.load_json(self.work / name)
            value["motion"]["rows"][0]["bones_world_sha256"] = "f"*64
            self.change(name, value)
        with self.assertRaisesRegex(ValueError, "pinned evidence differs"): self.admit()

    def test_resealed_changed_pair_with_stale_proof_fails(self):
        index = d.load_json(self.work / "witness-index.json")
        for kind in ("approved", "regenerated"):
            name = f"{kind}-000.json"; value = d.load_json(self.work / name)
            value["motion"]["rows"][0]["bones_world_sha256"] = "f"*64
            self.change(name, value); index[name] = p.sha(self.work / name)
        self.change("witness-index.json", index)
        self.pins_now["witness_index_sha256"] = p.sha(self.work / "witness-index.json")
        with self.assertRaisesRegex(ValueError, "full current sealed evidence"): self.admit()

    def test_relaxed_numeric_contract_fails(self):
        name = "regenerated-000.json"; value = d.load_json(self.work / name)
        value["motion"]["numeric_contract"] = "tolerance allowed"
        self.change(name, value)
        index = d.load_json(self.work / "witness-index.json"); index[name] = p.sha(self.work / name)
        self.change("witness-index.json", index)
        self.pins_now["witness_index_sha256"] = p.sha(self.work / "witness-index.json")
        with self.assertRaisesRegex(ValueError, "numeric contract"): self.admit()

    def test_correction_and_driver_counts_cannot_be_relabelled(self):
        value = d.load_json(self.work / "replay-receipt.json")
        value["original_scalar_corrections_applied"] = 16
        value["unchanged_driven_outputs_recomputed"] = 0
        self.change("replay-receipt.json", value)
        self.pins_now["replay_receipt_sha256"] = p.sha(self.work / "replay-receipt.json")
        with self.assertRaisesRegex(ValueError, "lineage correction"): self.admit()

    def test_output_directory_cannot_alias_source_package(self):
        with self.assertRaisesRegex(ValueError, "aliases or contains"):
            p.context(self.args(HERE.parent))

    def test_hardlinked_output_cannot_alias_private_input(self):
        target = self.work / "source-equivalence.json"
        self.originals[target] = target.read_bytes(); target.unlink()
        try:
            target.hardlink_to(self.delta_file)
            with self.assertRaisesRegex(ValueError, "hardlink aliases"):
                p.context(self.args())
        finally:
            target.unlink()  # restore never writes through a protected hardlink

    def test_planner_never_claims_completion_from_existing_files(self):
        result = p.plan_next(self.ctx, self.args())
        self.assertEqual(result["stage"], "admission_required")
        self.assertFalse(result["complete"])

    def test_new_replay_plan_uses_existing_delta_and_literal_argv_paths(self):
        root = self.root / "new Windows run with spaces ü"
        args = self.args(root); ctx = p.context(args)
        result = p.plan_next(ctx, args)
        self.assertEqual(result["stage"], "replay")
        self.assertNotIn("extract", result["argv"])
        self.assertIn(str(root / "regenerated-onehand-v6.blend"), result["argv"])
        self.assertIn(str(self.delta_file), result["argv"])
        self.assertEqual(result["argv"][1:3], ["-I", "-B"])
        self.assertIn("--disable-autoexec", runner.native_command(self.blender, ["replay"]))
        self.assertFalse(root.exists())
        self.assertFalse(result["launch_authorized_by_this_plan"])

    def test_partial_replay_and_preexisting_job_are_not_retried(self):
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            root = Path(folder); args = self.args(root); ctx = p.context(args)
            (root / "regenerated-onehand-v6.blend").write_bytes(b"partial")
            with self.assertRaisesRegex(ValueError, "partial replay"): p.plan_next(ctx, args)
            (root / "regenerated-onehand-v6.blend").unlink()
            (root / "replay-job").mkdir()
            with self.assertRaisesRegex(ValueError, "previous native attempt"): p.plan_next(ctx, args)

    def test_lock_or_wrong_tool_pin_fails_before_command(self):
        args = self.args(); args.blender_sha256 = "0"*64
        with self.assertRaisesRegex(ValueError, "file bytes differ"): p.plan_next(self.ctx, args)
        args = self.args(); args.lock = self.generated
        with self.assertRaisesRegex(ValueError, "lock already exists"): p.plan_next(self.ctx, args)

    def test_low_disk_blocks_native_plan_without_creating_outputs(self):
        root = self.root / "low disk new run"; args = self.args(root); ctx = p.context(args)
        with patch.object(p.shutil, "disk_usage", return_value=SimpleNamespace(free=512*1024**2)):
            with self.assertRaisesRegex(ValueError, "1 GiB free floor"): p.plan_next(ctx, args)
        self.assertFalse(root.exists())

    def test_missing_witness_in_sealed_proof_is_not_resumed_as_unsealed(self):
        self.change("regenerated-016.json", remove=True)
        with self.assertRaisesRegex(ValueError, "sealed proof has missing"): p.plan_next(self.ctx, self.args())


if __name__ == "__main__":
    unittest.main()
