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
            self.assertNotIn(b"private source", content)

    def test_paths_and_symlinks(self):
        for path in ("../x", "/x", "a\\b", "C:/x", "CON", "a/../b", "private-assets/x", "settings.cfg", "version.json", "x."):
            with self.assertRaises(ValueError): release.safe_path(path)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input"
            source.mkdir()
            (source / "game.exe").symlink_to(root / "elsewhere")
            with self.assertRaises(ValueError): release.pack(source, root / "out", "game.exe")

    def test_public_signature_verification_and_asset_hashes(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        # Public deterministic test fixture, never a production key or OS-random generation.
        signing = Ed25519PrivateKey.from_private_bytes(bytes([59]) * 32)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input"
            source.mkdir()
            (source / "game.exe").write_bytes(b"test game")
            output = root / "assets"
            release.prepare(argparse.Namespace(input=source, output=output, version="1.1.0", sequence=2, target="test-target", entrypoint="game.exe", previous=None, previous_version=None))
            payload = output / "update-test-target.payload.json"
            signature = root / "fixture.sig"
            signature.write_bytes(signing.sign(payload.read_bytes()))
            public = root / "fixture-public.hex"
            public.write_text(signing.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex())
            envelope = output / "update-test-target.json"
            release.seal(argparse.Namespace(payload=payload, signature=signature, public_key=public, output=envelope))
            options = argparse.Namespace(manifest=envelope, public_key=public, assets_dir=output, version="1.1.0", target="test-target", bundle_only=True)
            verified = release.verify_manifest(options)
            self.assertEqual(verified["sequence"], 2)
            bundle = output / verified["bundle"]["name"]
            bundle.write_bytes(b"corruption")
            with self.assertRaises(ValueError): release.verify_manifest(options)
            invalid = json.loads(envelope.read_text())
            invalid["payload"] += " "
            envelope.write_text(json.dumps(invalid))
            with self.assertRaises(Exception): release.verify_manifest(options)

    def test_small_and_unrelated_inputs(self):
        for base, new in [(b"a", b"b"), (b"A" * 100000, b"B" * 100000), (b"A" * 8192, b"A" * 8192)]:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "old").write_bytes(base)
                (root / "new").write_bytes(new)
                release.make_delta(root / "old", root / "new", root / "delta")
                self.assertEqual(apply(base, (root / "delta").read_bytes()), new)

if __name__ == "__main__": unittest.main()
