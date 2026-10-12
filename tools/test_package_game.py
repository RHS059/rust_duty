import importlib.util
import gzip
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("package_game", Path(__file__).with_name("package_game.py"))
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)
release_spec = importlib.util.spec_from_file_location("release_update", Path(__file__).with_name("release_update.py"))
release = importlib.util.module_from_spec(release_spec)
release_spec.loader.exec_module(release)
ROOT = Path(__file__).resolve().parents[1]
UI_RESOURCES = {
    "docs/FRAME_PERFORMANCE.md": b"# Local recording and complete session-folder export fixture\n",
    "docs/GPU_TELEMETRY.md": b"# GPU sample identity, limitations and observations guidance fixture\n",
    "ui/theme.css": b"#hud .label { color: #e8edf2; }\n",
    "docs/UI_THEME.md": b"# Native theme fixture\n",
    "ui/examples/high-contrast.css": b".panel { background-color: #000000f2; border-width: 2px; }\n",
    "ui/examples/large-type.css": b"#pause-menu .label { font-size: 26px; }\n",
    "docs/UI_THEME_EXAMPLES.md": b"# Theme examples fixture\nHigh contrast uses 95%-opaque black panels.\n",
}


class PackageGameTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "source"
        shutil.copytree(ROOT / package.ASSET_DIR, self.root / package.ASSET_DIR)
        compressed = self.root / package.ASSET_DIR / "asset.vrs.gz"
        (self.root / package.ASSET_DIR / "asset.vrs").write_bytes(gzip.decompress(compressed.read_bytes()))
        compressed.unlink()

    def add_distribution_files(self):
        for relative in (*package.NOTICES, *package.BUILD_FILES, "target/release/vector-range"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        for relative, contents in UI_RESOURCES.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)

    def test_repository_compressed_input_stages_exact_original(self):
        self.add_distribution_files()
        raw = self.root / package.ASSET_DIR / "asset.vrs"
        expected = raw.read_bytes()
        raw.unlink()
        compressed = self.root / package.ASSET_DIR / "asset.vrs.gz"
        shutil.copy2(ROOT / package.ASSET_DIR / "asset.vrs.gz", compressed)
        package.verify(self.root)
        destination = self.base / "compressed-build"
        package.stage(self.root, "target/release/vector-range", destination)
        self.assertEqual((destination / package.ASSET_DIR / "asset.vrs").read_bytes(), expected)
        self.assertFalse((destination / package.ASSET_DIR / "asset.vrs.gz").exists())

    def test_materialize_verifies_and_restores_raw_skin_for_native_runtime(self):
        raw = self.root / package.ASSET_DIR / "asset.vrs"
        expected = raw.read_bytes()
        raw.unlink()
        shutil.copy2(ROOT / package.ASSET_DIR / "asset.vrs.gz", self.root / package.ASSET_DIR / "asset.vrs.gz")
        package.materialize(self.root)
        self.assertEqual(raw.read_bytes(), expected)
        package.materialize(self.root)
        self.assertEqual(raw.read_bytes(), expected)

    def test_compressed_missing_and_corrupt_fail_closed(self):
        (self.root / package.ASSET_DIR / "asset.vrs").unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            package.verify(self.root)
        compressed = self.root / package.ASSET_DIR / "asset.vrs.gz"
        shutil.copy2(ROOT / package.ASSET_DIR / "asset.vrs.gz", compressed)
        with compressed.open("r+b") as stream:
            stream.seek(100)
            value = stream.read(1)[0]
            stream.seek(100)
            stream.write(bytes([value ^ 1]))
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            package.verify(self.root)

    def test_frozen_companions_pass(self):
        result = package.verify(self.root)
        self.assertEqual(result["clip_count"], 43)
        self.assertEqual(sum(x["bytes"] for x in result["files"].values()), 38041785)

    def test_each_missing_companion_fails(self):
        for name in package.COMPANIONS:
            path = self.root / package.ASSET_DIR / name
            hidden = path.with_suffix(".hold")
            path.rename(hidden)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "missing"):
                package.verify(self.root)
            hidden.rename(path)

    def test_same_size_corruption_fails(self):
        path = self.root / package.ASSET_DIR / "asset.vra"
        with path.open("r+b") as stream:
            stream.seek(100)
            value = stream.read(1)[0]
            stream.seek(100)
            stream.write(bytes([value ^ 1]))
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            package.verify(self.root)

    def test_wrong_size_and_manifest_fail(self):
        path = self.root / package.ASSET_DIR / "asset.vrm"
        path.write_bytes(b"truncated")
        with self.assertRaisesRegex(ValueError, "size"):
            package.verify(self.root)
        manifest = self.root / package.ASSET_DIR / "manifest.json"
        data = json.loads(manifest.read_text())
        data["files"]["../unapproved.vrm"] = data["files"].pop("asset.vrm")
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "manifest"):
            package.verify(self.root)

    def test_symlink_is_rejected(self):
        path = self.root / package.ASSET_DIR / "asset.vrm"
        path.unlink()
        try:
            path.symlink_to(ROOT / package.ASSET_DIR / "asset.vrm")
        except OSError as error:
            self.skipTest(f"symlink creation unavailable: {error}")
        with self.assertRaisesRegex(ValueError, "symlink"):
            package.verify(self.root)

    def test_complete_build_update_and_bundle_keep_all_companions(self):
        self.add_distribution_files()
        unlisted_theme = "ui/examples/private-custom.css"
        (self.root / unlisted_theme).write_text("unlisted local theme must not ship")
        build = self.base / "build"
        package.stage(self.root, "target/release/vector-range", build)
        self.assertTrue((build / "vector-range").is_file())
        self.assertTrue((build / "settings.cfg").is_file())
        self.assertFalse((build / "target").exists())
        self.assertFalse((build / unlisted_theme).exists())
        update = self.base / "update"
        package.stage(build, "vector-range", update, update=True)
        self.assertFalse((update / "settings.cfg").exists())
        self.assertFalse((update / unlisted_theme).exists())
        for relative in UI_RESOURCES:
            expected = (self.root / relative).read_bytes()
            self.assertEqual((build / relative).read_bytes(), expected)
            self.assertEqual((update / relative).read_bytes(), expected)
        self.assertEqual(package.verify(update), package.verify(build))
        bundle = self.base / "game.rdb"
        release.pack(update, bundle, "vector-range")
        data = bundle.read_bytes()
        self.assertEqual(data[:8], b"RDBND001")
        count = struct.unpack_from("<I", data, 8)[0]
        offset, included = 12, {}
        for _ in range(count):
            length = struct.unpack_from("<H", data, offset)[0]
            offset += 2
            name = data[offset:offset + length].decode()
            offset += length + 1
            size = struct.unpack_from("<Q", data, offset)[0]
            offset += 8
            included[name] = data[offset:offset + size]
            offset += size
        self.assertEqual(offset, len(data))
        for name in package.COMPANIONS:
            relative = (package.ASSET_DIR / name).as_posix()
            self.assertEqual(included[relative], (self.root / relative).read_bytes())
        for relative in UI_RESOURCES:
            self.assertEqual(included[relative], (self.root / relative).read_bytes())
        self.assertEqual(included["docs/GPU_TELEMETRY.md"], UI_RESOURCES["docs/GPU_TELEMETRY.md"])
        self.assertNotIn("settings.cfg", included)
        self.assertNotIn(unlisted_theme, included)
        self.assertEqual((self.root / "ui/theme.css").read_bytes(), UI_RESOURCES["ui/theme.css"])

    def test_missing_ui_resources_fail_before_build_or_update_output(self):
        self.add_distribution_files()
        for relative in UI_RESOURCES:
            path = self.root / relative
            original = path.read_bytes()
            path.unlink()
            for update in (False, True):
                output = self.base / "missing-ui"
                with self.subTest(relative=relative, update=update):
                    with self.assertRaisesRegex(ValueError, "required distribution file missing"):
                        package.stage(self.root, "target/release/vector-range", output, update=update)
                    self.assertFalse(output.exists())
            path.write_bytes(original)

    def test_ui_resource_symlinks_are_rejected_without_copying_external_data(self):
        self.add_distribution_files()
        target = self.base / "external-theme.css"
        target.write_text("private external theme")
        for relative, original in UI_RESOURCES.items():
            path = self.root / relative
            path.unlink()
            try:
                path.symlink_to(target)
            except OSError as error:
                self.skipTest(f"symlink creation unavailable: {error}")
            for update in (False, True):
                output = self.base / "linked-ui"
                with self.subTest(relative=relative, update=update), self.assertRaisesRegex(ValueError, "symlink"):
                    package.stage(self.root, "target/release/vector-range", output, update=update)
                self.assertFalse(output.exists())
            path.unlink()
            path.write_bytes(original)

    def test_staging_fails_closed_and_never_overwrites(self):
        output = self.base / "output"
        with self.assertRaisesRegex(ValueError, "missing"):
            package.stage(self.root, "target/release/vector-range", output)
        self.assertFalse(output.exists())
        self.add_distribution_files()
        (self.root / package.ASSET_DIR / "asset.vrs").unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            package.stage(self.root, "target/release/vector-range", output)
        self.assertFalse(output.exists())
        output.mkdir()
        with self.assertRaisesRegex(ValueError, "replace"):
            package.stage(self.root, "target/release/vector-range", output)


if __name__ == "__main__":
    unittest.main()
