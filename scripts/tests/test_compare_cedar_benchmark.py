import copy
import importlib.util
import pathlib
import unittest

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

    def test_summary_nearest_rank_and_explicit_missing(self):
        result = benchmark.summary([1,2,3,4,None])
        self.assertEqual(result["p50"], 2)
        self.assertEqual(result["p95"], 4)
        self.assertEqual((result["available_samples"],result["total_samples"]), (4,5))


if __name__ == "__main__":
    unittest.main()
