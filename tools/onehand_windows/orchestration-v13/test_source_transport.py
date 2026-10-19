"""Small CPU-only, non-native adversarial transport fixtures."""
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import source_transport as t


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.raw = bytes(range(256)) * 1025
        self.encoded = gzip.compress(self.raw, mtime=0)
        self.path = self.root / "input.gz"; self.path.write_bytes(self.encoded)

    def tearDown(self):
        self.tmp.cleanup()

    def identity(self, raw):
        return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

    def run_decode(self, encoded=None, canonical=None):
        data = self.encoded if encoded is None else encoded
        self.path.write_bytes(data); writes = []
        result = t.decode_verified(self.path, self.identity(data), canonical or self.identity(self.raw), writes.append)
        return result, writes

    def test_exact_bounded_roundtrip(self):
        result, writes = self.run_decode()
        self.assertEqual(result, self.identity(self.raw)); self.assertEqual(b"".join(writes), self.raw)
        self.assertLessEqual(max(map(len, writes)), t.CHUNK)

    def test_encoded_prehash_header_decode_use_one_open(self):
        original = Path.open; calls=[]
        def opened(path,*args,**kwargs):
            if path == self.path:calls.append(args)
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',opened):
            t.decode_verified(self.path,self.identity(self.encoded),self.identity(self.raw),lambda _:None)
        self.assertEqual(len(calls),1)

    def test_empty_raw_forbidden(self):
        with self.assertRaises(ValueError): self.run_decode(gzip.compress(b""), self.identity(b""))

    def test_encoded_hash_checked_before_sink(self):
        writes = []
        with self.assertRaises(ValueError):
            t.decode_verified(self.path, {**self.identity(self.encoded), "sha256": "0" * 64}, self.identity(self.raw), writes.append)
        self.assertEqual(writes, [])

    def test_encoded_size_checked_before_sink(self):
        writes = []
        with self.assertRaises(ValueError):
            t.decode_verified(self.path, {**self.identity(self.encoded), "bytes": len(self.encoded) - 1}, self.identity(self.raw), writes.append)
        self.assertEqual(writes, [])

    def test_expansion_stops_at_exact_raw_cap(self):
        writes = []
        with self.assertRaises(ValueError):
            t.decode_verified(self.path, self.identity(self.encoded), {**self.identity(self.raw), "bytes": 17}, writes.append)
        self.assertLessEqual(sum(map(len, writes)), 17)

    def test_raw_size_too_large_fails(self):
        with self.assertRaises(ValueError): self.run_decode(canonical={**self.identity(self.raw), "bytes": len(self.raw) + 1})

    def test_raw_hash_mismatch_fails(self):
        with self.assertRaises(ValueError): self.run_decode(canonical={**self.identity(self.raw), "sha256": "0" * 64})

    def test_source_change_between_passes_fails(self):
        original_fingerprint = t.stream_fingerprint
        expected = self.identity(self.encoded)
        def change_after_check(path, cap):
            result = original_fingerprint(path, cap)
            self.path.write_bytes(gzip.compress(b"X" * len(self.raw), mtime=0))
            return result
        with patch.object(t, "stream_fingerprint", side_effect=change_after_check), self.assertRaises((ValueError, t.zlib.error)):
            t.decode_verified(self.path, expected, self.identity(self.raw), lambda _: None)

    def test_truncated_header_body_and_footer_fail(self):
        for length in (1, 9, len(self.encoded) // 2, len(self.encoded) - 1):
            with self.subTest(length=length), self.assertRaises((ValueError, t.zlib.error)):
                self.run_decode(self.encoded[:length])

    def test_bad_crc_fails(self):
        bad = bytearray(self.encoded); bad[-8] ^= 1
        with self.assertRaises((ValueError, t.zlib.error)): self.run_decode(bytes(bad))

    def test_multiple_members_fail(self):
        with self.assertRaises(ValueError): self.run_decode(self.encoded + gzip.compress(b"hidden", mtime=0))

    def test_trailing_data_fails(self):
        with self.assertRaises(ValueError): self.run_decode(self.encoded + b"hidden")

    def test_non_gzip_fails(self):
        with self.assertRaises((ValueError, t.zlib.error)): self.run_decode(t.zlib.compress(self.raw))

    def test_gzip_optional_metadata_and_timestamp_fail(self):
        out = io.BytesIO()
        with gzip.GzipFile(filename="hidden-name", fileobj=out, mode="wb", mtime=0) as stream:
            stream.write(self.raw)
        with self.assertRaises(ValueError): self.run_decode(out.getvalue())
        with self.assertRaises(ValueError): self.run_decode(gzip.compress(self.raw, mtime=1))

    def test_total_and_per_file_caps(self):
        for field, value in (("bytes", t.TRANSPORT_CAP + 1), ("bytes", True)):
            with self.assertRaises(ValueError):
                t.decode_verified(self.path, {**self.identity(self.encoded), field: value}, self.identity(self.raw), lambda _: None)
        with self.assertRaises(ValueError): self.run_decode(canonical={**self.identity(self.raw), "bytes": t.RAW_CAP + 1})

    def test_redirect_and_hardlink_fail(self):
        import os
        linked = self.root / "linked.gz"
        try: linked.symlink_to(self.path)
        except OSError: self.skipTest("symlink unavailable")
        with self.assertRaises(ValueError): t.fingerprint(linked, t.TRANSPORT_CAP)
        linked.unlink(); os.link(self.path, linked)
        with self.assertRaises(ValueError): t.fingerprint(linked, t.TRANSPORT_CAP)

    def test_path_rejections(self):
        for name in ("../x", "/x", "a//b", "a/./b", "a\\b", "C:/x", "NUL", "a/COM1.txt", "a. "):
            with self.subTest(name=name), self.assertRaises(ValueError): t.relative(name)

    def test_strict_json(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}'):
            with self.assertRaises(ValueError): t.strict_load(raw)

    def manifest(self):
        return {"schema": t.SCHEMA, "canonical_pins_sha256": t.RAW_PIN_SHA, "files": [
            {"name": p["name"], "kind": p["kind"], "canonical": {"path": p["canonical_path"], "sha256": p["sha256"], "bytes": p["bytes"]},
             "transport": {"path": "payload/" + p["name"] + ".gz", "encoding": "gzip-single-member", "sha256": "a" * 64, "bytes": 20}}
            for p in t.canonical_pins()]}

    def test_complete_manifest_passes_without_admitting_native(self):
        value = self.manifest(); self.assertEqual(len(t.validate_manifest(value)), 38)
        self.assertNotIn("native_admission", value)

    def test_missing_duplicated_reordered_extra_inputs_fail(self):
        baseline = self.manifest()
        variants = [baseline["files"][:-1], baseline["files"] + baseline["files"][:1],
                    baseline["files"][:1] + baseline["files"][:-1], list(reversed(baseline["files"]))]
        for files in variants:
            with self.assertRaises(ValueError): t.validate_manifest({**baseline, "files": files})

    def test_canonical_identity_cannot_be_changed(self):
        for key, value in (("sha256", "0" * 64), ("bytes", 1), ("path", "private.blend")):
            m = self.manifest(); m["files"][0]["canonical"][key] = value
            with self.assertRaises(ValueError): t.validate_manifest(m)

    def test_unexpected_transport_and_hidden_fields_fail(self):
        for key, value in (("path", "../private.gz"), ("encoding", "zip"), ("extra", "hidden")):
            m = self.manifest(); m["files"][0]["transport"][key] = value
            with self.assertRaises(ValueError): t.validate_manifest(m)
        m = self.manifest(); m["hidden"] = "payload"
        with self.assertRaises(ValueError): t.validate_manifest(m)

    def test_manifest_total_cap(self):
        m = self.manifest()
        for row in m["files"]: row["transport"]["bytes"] = 1024**2
        with self.assertRaises(ValueError): t.validate_manifest(m)

    def test_disk_floor_failure_writes_nothing(self):
        root = self.root / "output"
        with patch.object(t.shutil, "disk_usage", return_value=type("Disk", (), {"free": t.DISK_FLOOR})()):
            with self.assertRaises(ValueError): t.materialize(self.manifest(), self.root, root)
        self.assertFalse(root.exists())

    def test_existing_output_refused(self):
        with self.assertRaises(ValueError): t.materialize(self.manifest(), self.root, self.root)

    def test_small_synthetic_materialization_is_fresh_and_unadmitted(self):
        row = {"name": "synthetic.json", "kind": "original-action-delta",
               "canonical": {"path": "original-source/synthetic.json", **self.identity(self.raw)},
               "transport": {"path": "input.gz", "encoding": "gzip-single-member", **self.identity(self.encoded)}}
        out = self.root / "fresh"
        # Only the test patches the fixed real 38-file inventory. The production
        # codec/paths/disk checks and actual small byte writes are unchanged.
        with patch.object(t, "validate_manifest", return_value=[row]):
            result = t.materialize({}, self.root, out)
        self.assertEqual((out / row["canonical"]["path"]).read_bytes(), self.raw)
        self.assertIs(result["native_admission"], False)
        with patch.object(t, "validate_manifest", return_value=[row]), self.assertRaises(ValueError):
            t.materialize({}, self.root, out)

    def test_canonical_pin_tampering_rejected(self):
        (self.root / "RAW_INPUT_PINS.json").write_text("{}")
        with patch.object(t, "HERE", self.root), self.assertRaises(ValueError):
            t.canonical_pins()



class PinnedReadRegression(unittest.TestCase):
    def test_empty_replacement_inventory_is_rejected(self):
        with patch.object(t, 'read_pinned_json', return_value={'files': []}):
            with self.assertRaisesRegex(ValueError, '38-file'):t.canonical_pins()

    def test_canonical_hash_and_parse_use_same_buffer(self):
        original = (t.HERE/'RAW_INPUT_PINS.json').read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'RAW_INPUT_PINS.json').write_bytes(original)
            def formerly_exploitable(*args):
                (root/'RAW_INPUT_PINS.json').write_text('{"files": []}')
                return {'sha256':t.RAW_PIN_SHA,'bytes':len(original)}
            with patch.object(t,'HERE',root),patch.object(t,'fingerprint',side_effect=formerly_exploitable) as old:
                self.assertEqual(len(t.canonical_pins()),38);old.assert_not_called()

    def test_manifest_hash_and_parse_use_same_buffer(self):
        original = (t.HERE/'TRANSPORT_MANIFEST.json').read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'manifest.json';path.write_bytes(original)
            expected=hashlib.sha256(original).hexdigest();captured=[]
            def formerly_exploitable(*args):
                replacement=json.loads(original);replacement['files'][0]['transport']['sha256']='0'*64
                path.write_text(json.dumps(replacement))
                return {'sha256':expected,'bytes':len(original)}
            import contextlib
            with patch.object(t.sys,'argv',['source_transport','--manifest',str(path),'--manifest-sha256',expected,'--output',str(root/'out')]),patch.object(t,'fingerprint',side_effect=formerly_exploitable) as old,patch.object(t,'materialize',side_effect=lambda value,*_:captured.append(value) or {'native_admission':False}),contextlib.redirect_stdout(io.StringIO()):
                t.main();old.assert_not_called()
            self.assertEqual(captured,[json.loads(original)])

    def test_pinned_read_rejects_oversized_and_duplicate_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'x.json'
            for raw,cap in [(b'{}x',2),(b'{"a":1,"a":2}',256)]:
                path.write_bytes(raw)
                with self.assertRaises(ValueError):t.read_pinned_json(path,hashlib.sha256(raw).hexdigest(),cap)

if __name__ == "__main__": unittest.main()
