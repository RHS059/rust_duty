import copy
import hashlib
import importlib.util
import json
import pathlib
import struct
import subprocess
import sys
import unittest
import tempfile
from unittest import mock

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "compare_cedar_benchmark.py"
SPEC = importlib.util.spec_from_file_location("compare_cedar", SCRIPT)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def report(mode="headless-gpu"):
    sample = {key: 100 for key in benchmark.METRICS}
    sample.update(frame_index=0, path_frame=0, camera_position=[0,2,38], upload_bytes=400, gpu_timestamp_ns=None)
    if mode == "cpu-scene":
        for key in benchmark.GPU_ONLY:
            sample[key] = None
    return {"schema":benchmark.SCHEMA, "status":"complete", "mode":mode,
            "source":{"revision":"fixture"}, "config":{"frames":1}, "path":{"cycle_frames":720},
            "scene":{"assets":[{"fnv1a64":"fixture"}]}, "host":{"machine_label":"test"},
            "adapter":None, "gpu_timestamps_available":False, "samples":[sample]}


class CompareTests(unittest.TestCase):
    def test_null_gpu_remains_null_and_zero_is_not_missing(self):
        before = report()
        after = copy.deepcopy(before)
        after["samples"][0]["draw_calls"] = 0
        result = benchmark.compare(before, after)
        self.assertIsNone(result["metrics"]["gpu_timestamp_ns"]["mean_delta"])
        self.assertEqual(result["metrics"]["draw_calls"]["mean_delta_percent"], -100.)

    def test_real_uploaded_bytes_must_reconcile(self):
        broken = report()
        broken["samples"][0]["upload_bytes"] = 0
        with self.assertRaisesRegex(ValueError, "upload byte total"):
            benchmark.validate(broken)

    def test_cpu_mode_cannot_claim_gpu_results(self):
        before = report("cpu-scene")
        benchmark.compare(before, before)
        before["samples"][0]["triangles"] = 100
        with self.assertRaisesRegex(ValueError, "cpu-scene"):
            benchmark.validate(before)

    def test_mismatched_machine_resolution_path_mode_or_assets_rejected(self):
        for key in ("host", "config", "path", "adapter", "mode", "scene"):
            before, after = report(), report()
            if key == "mode":
                after = report("cpu-scene")
            elif key == "adapter":
                after[key] = {"name":"another GPU"}
            elif key == "scene":
                after[key]["assets"] = []
            else:
                after[key]["different"] = True
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "incomparable"):
                benchmark.compare(before, after)

    def test_partial_gpu_samples_are_not_comparable(self):
        before, after = report(), report()
        after["gpu_timestamps_available"] = True
        after["samples"][0]["gpu_timestamp_ns"] = 50
        self.assertIsNone(benchmark.compare(before, after)["metrics"]["gpu_timestamp_ns"]["mean_delta"])

    def test_failed_or_malformed_evidence_is_not_a_pass(self):
        for mutation in (lambda r:r.update(status="failed"),
                         lambda r:r["samples"][0].update(frame_index=1),
                         lambda r:r["samples"][0].update(cpu_record_ns=float("nan")),
                         lambda r:r["samples"][0].update(cpu_record_ns=None),
                         lambda r:r["samples"][0].pop("draw_calls")):
            broken = report()
            mutation(broken)
            with self.assertRaises(ValueError):
                benchmark.validate(broken)

    def parity_fixture(self, root):
        before, after = report(), report()
        directories = []
        parity = {"schema":"rust-duty-city-geometry-parity/v1", "passed":True,
                  "placement_metadata_checked":True, "checks":{
                      "winding_sensitive_triangle_vertex_normal_rgba_multiset_equal":True}}
        for field in ("colliders", "buildings", "spawn", "supply_position", "landmarks", "bounds"):
            parity["checks"][f"original_level_{field}_fields_equal"] = True
        for field in ("buildings", "instances"):
            parity["checks"][f"original_layout_{field}_fields_equal"] = True
        for side, data in (("baseline",before),("candidate",after)):
            directory = pathlib.Path(root)/side
            directory.mkdir()
            (directory/"level.json").write_text("{}")
            (directory/"meshes.bin").write_bytes(side.encode())
            data["scene"]["assets"] = [benchmark.file_identity(directory/name)[0] for name in ("level.json","meshes.bin")]
            parity[side] = {"mesh_sha256":hashlib.sha256(side.encode()).hexdigest(), "sorted_triangle_hashes_sha256":"fixture-digest"}
            directories.append(directory)
        return before, after, parity, directories

    def test_reencode_gate_binds_actual_files_and_recomputes_proof(self):
        with tempfile.TemporaryDirectory() as root:
            before, after, parity, dirs = self.parity_fixture(root)
            with mock.patch.object(benchmark, "run_geometry_verifier", return_value=parity) as verifier:
                evidence = benchmark.bind_geometry_parity(before,after,parity,*dirs)
                verifier.assert_called_once_with(*dirs)
                self.assertTrue(benchmark.compare(before,after,evidence)["scene_reencoding_evidence"]["freshly_verified"])
            with mock.patch.object(benchmark, "run_geometry_verifier", return_value={"passed":False}):
                with self.assertRaisesRegex(ValueError,"fresh independent"):
                    benchmark.bind_geometry_parity(before,after,parity,*dirs)

    def test_reencode_gate_rejects_stale_mesh_sha_and_wrong_benchmark_inputs(self):
        with tempfile.TemporaryDirectory() as root:
            before, after, parity, dirs = self.parity_fixture(root)
            with mock.patch.object(benchmark, "run_geometry_verifier") as verifier:
                stale = copy.deepcopy(parity)
                stale["candidate"]["mesh_sha256"] = "wrong"
                with self.assertRaisesRegex(ValueError,"SHA256"):
                    benchmark.bind_geometry_parity(before,after,stale,*dirs)
                after["scene"]["assets"][1]["name"] = "lighting.bin"
                with self.assertRaisesRegex(ValueError,"asset identities"):
                    benchmark.bind_geometry_parity(before,after,parity,*dirs)
                verifier.assert_not_called()

    def test_reencode_gate_rejects_missing_placement_proof(self):
        with tempfile.TemporaryDirectory() as root:
            before, after, parity, dirs = self.parity_fixture(root)
            parity["placement_metadata_checked"] = False
            with self.assertRaisesRegex(ValueError,"placement"):
                benchmark.bind_geometry_parity(before,after,parity,*dirs)

    @unittest.skipUnless((SCRIPT.parents[1]/"tools/verify_city_geometry.py").is_file(),
                         "stage 2 geometry verifier is not present in this stage 0 checkout")
    def test_actual_reencode_cli_accepts_verified_fixture_and_rejects_stale_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            root = pathlib.Path(root)
            vertex = struct.Struct("<10f")
            vertices = [vertex.pack(0,0,0,0,1,0,1,1,1,1), vertex.pack(1,0,0,0,1,0,1,1,1,1), vertex.pack(0,1,0,0,1,0,1,1,1,1)]
            paths = []
            for name, ordered, indices in (("baseline",vertices,[0,1,2]),("candidate",vertices[::-1],[2,1,0])):
                city = root/name
                city.mkdir()
                mesh = b"RDCITY01" + struct.pack("<I6fII",1,-1,-1,-1,2,2,2,3,3) + b"".join(ordered) + struct.pack("<3H",*indices)
                (city/"meshes.bin").write_bytes(mesh)
                level = {"colliders":[],"buildings":[],"spawn":{"position":[0,0,0],"yaw_degrees":0},"supply_position":[0,0,0],"landmarks":[],"bounds":{"min":[-1,-1,-1],"max":[2,2,2]}}
                (city/"level.json").write_text(json.dumps(level))
                (city/"layout.json").write_text(json.dumps({"buildings":[],"instances":[]}))
                data = report("cpu-scene")
                data["scene"]["assets"] = [benchmark.file_identity(city/f)[0] for f in ("level.json","meshes.bin")]
                path = root/(name+".json")
                path.write_text(json.dumps(data))
                paths.append(path)
            parity_path = root/"parity.json"
            parity_path.write_text(json.dumps(benchmark.run_geometry_verifier(root/"baseline",root/"candidate")))
            command = [sys.executable,str(SCRIPT),*map(str,paths),"--geometry-parity",str(parity_path),"--baseline-city",str(root/"baseline"),"--candidate-city",str(root/"candidate")]
            result = subprocess.run(command,capture_output=True,text=True,check=True)
            self.assertTrue(json.loads(result.stdout)["scene_reencoding_evidence"]["freshly_verified"])
            mesh_path = root/"candidate/meshes.bin"
            mesh_path.write_bytes(mesh_path.read_bytes()+b"bad")
            rejected = subprocess.run(command,capture_output=True,text=True)
            self.assertNotEqual(rejected.returncode,0)
            self.assertIn("asset identities",rejected.stderr)

    def test_summary_nearest_rank_and_explicit_missing(self):
        result = benchmark.summary([1,2,3,4,None])
        self.assertEqual(result["p50"], 2)
        self.assertEqual(result["p95"], 4)
        self.assertEqual((result["available_samples"],result["total_samples"]), (4,5))


if __name__ == "__main__":
    unittest.main()
