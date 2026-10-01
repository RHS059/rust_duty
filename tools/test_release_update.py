import argparse
import importlib.util
import json
from pathlib import Path
import random
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("release_update", Path(__file__).with_name("release_update.py"))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def apply(base, patch):
    assert patch[:8] == b"RDDLT001"
    old, new = struct.unpack_from("<QQ", patch, 8)
    assert old == len(base)
    output, pos = bytearray(), 24
    while patch[pos] != 255:
        tag, pos = patch[pos], pos + 1
        if tag == 0:
            offset, size = struct.unpack_from("<QQ", patch, pos)
            pos += 16
            output.extend(base[offset:offset + size])
        else:
            size, = struct.unpack_from("<Q", patch, pos)
            pos += 8
            output.extend(patch[pos:pos + size])
            pos += size
    assert len(output) == new and pos + 1 == len(patch)
    return bytes(output)


class ReleaseTests(unittest.TestCase):
    def test_real_delta_insertion_deletion_changes(self):
        rng = random.Random(59)
        base = rng.randbytes(512 * 1024)
        new = b"prefix insertion" + base[:17000] + b"replacement" + base[21000:] + b"tail"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "old").write_bytes(base)
            (root / "new").write_bytes(new)
            info = release.make_delta(root / "old", root / "new", root / "delta")
            self.assertEqual(apply(base, (root / "delta").read_bytes()), new)
            self.assertGreater(info["copied_bytes"], len(new) * .9)
            self.assertLess(info["size"], len(new) * .1)

    def test_bundle_deterministic_and_preserves_user_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input"
            source.mkdir()
            (source / "game.exe").write_bytes(b"game")
            (source / "settings.cfg").write_text("my sensitivity")
            (source / "private-assets").mkdir()
            (source / "private-assets" / "secret").write_text("not distributable")
            (source / "launch.json").write_text("private launch mappings")
            (source / "fps-arms.vrs").write_bytes(b"private arm skeleton")
            (source / "assets" / "arms").mkdir(parents=True)
            preview_arms = source / "assets" / "arms" / "first-person.vrs"
            preview_arms.write_bytes(b"private preview skeleton")
            (source / "FIRST-PERSON.VRS").write_bytes(b"uppercase private preview")
            (source / "nested" / "private-assets").mkdir(parents=True)
            (source / "nested" / "private-assets" / "secret").write_text("nested private source")
            release.pack(source, root / "first", "game.exe")
            release.pack(source, root / "second", "game.exe")
            content = (root / "first").read_bytes()
            self.assertEqual(content, (root / "second").read_bytes())
            self.assertNotIn(b"sensitivity", content)
            self.assertNotIn(b"distributable", content)
            self.assertNotIn(b"launch mappings", content)
            self.assertNotIn(b"arm skeleton", content)
            self.assertNotIn(b"private preview", content)
            self.assertNotIn(b"first-person", content.lower())
            self.assertEqual(preview_arms.read_bytes(), b"private preview skeleton")
            self.assertNotIn(b"private source", content)

    def test_paths_and_symlinks(self):
        for path in ("../x", "/x", "a\\b", "C:/x", "CON", "a/../b", "private-assets/x", "settings.cfg", "version.json", "x.", "assets/arms/first-person.vrs", "assets/arms/FIRST-PERSON.VRS"):
            with self.assertRaises(ValueError): release.safe_path(path)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input"
            source.mkdir()
            (source / "game.exe").symlink_to(root / "elsewhere")
            with self.assertRaises(ValueError): release.pack(source, root / "out", "game.exe")

    def test_github_manifest_verification_and_asset_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input"
            source.mkdir()
            (source / "game.exe").write_bytes(b"test game")
            output = root / "assets"
            release.prepare(argparse.Namespace(input=source, output=output, version="1.1.0", sequence=2, target="test-target", entrypoint="game.exe", previous=None, previous_version=None))
            manifest_path = output / "update-test-target.json"
            options = argparse.Namespace(manifest=manifest_path, assets_dir=output, version="1.1.0", target="test-target", bundle_only=True)
            verified = release.verify_manifest(options)
            self.assertEqual(verified["sequence"], 2)
            self.assertNotIn("signature", verified)
            bundle = output / verified["bundle"]["name"]
            bundle.write_bytes(b"corruption")
            with self.assertRaises(ValueError): release.verify_manifest(options)
            legacy = {"payload": manifest_path.read_text(), "signature": "00"}
            manifest_path.write_text(json.dumps(legacy))
            with self.assertRaises(ValueError): release.verify_manifest(options)

    def test_prepare_two_versions_produces_real_delta_and_verified_plain_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input"
            source.mkdir()
            base = random.Random(61).randbytes(256 * 1024)
            (source / "game.exe").write_bytes(base)
            first = root / "first"
            release.prepare(argparse.Namespace(input=source, output=first, version="1.0.0", sequence=1, target="test-target", entrypoint="game.exe", previous=None, previous_version=None))
            old = first / "rust-duty-1.0.0-test-target.rdb"
            (source / "game.exe").write_bytes(base[:128000] + b"new executable bytes" + base[128000:])
            second = root / "second"
            result = release.prepare(argparse.Namespace(input=source, output=second, version="1.1.0", sequence=2, target="test-target", entrypoint="game.exe", previous=old, previous_version="1.0.0"))
            options = argparse.Namespace(manifest=second / "update-test-target.json", assets_dir=second, version="1.1.0", target="test-target", bundle_only=False)
            manifest = release.verify_manifest(options)
            self.assertEqual(len(manifest["deltas"]), 1)
            self.assertLess(result["delta"]["size"], manifest["bundle"]["size"] / 10)
            patch = second / manifest["deltas"][0]["asset"]["name"]
            full = second / manifest["bundle"]["name"]
            self.assertEqual(apply(old.read_bytes(), patch.read_bytes()), full.read_bytes())
            manifest["deltas"][0]["asset"]["url"] = "https://other.example/patch"
            options.manifest.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError): release.verify_manifest(options)

    def test_small_and_unrelated_inputs(self):
        for base, new in [(b"a", b"b"), (b"A" * 100000, b"B" * 100000), (b"A" * 8192, b"A" * 8192)]:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "old").write_bytes(base)
                (root / "new").write_bytes(new)
                release.make_delta(root / "old", root / "new", root / "delta")
                self.assertEqual(apply(base, (root / "delta").read_bytes()), new)

if __name__ == "__main__": unittest.main()
