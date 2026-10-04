"""Independent release inventories reject source drift and silent asset loss.

The companion bytes are deliberately small fixtures. The source-owned packager
performs binary/parity validation; these tests cover the additional guard that
must still reject a publisher using an obsolete, internally valid allowlist.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import stat
import struct
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

import stage_release_game as release
import release_update
import smoke_live_update


COMPANIONS = ("asset.vra", "asset.vrs", "asset.vrm")
FAMILIES = ("locomotion", "walk", "ads", "directional", "reload")
SELECTIONS = ("opening", "reset", "pickup")
CONFIG = """schema=rust-duty-animation-slots/v1
locomotion.asset=locomotion/asset.vra
regular_walk.asset=directional/asset.vra
regular_walk.clip=normal_walk_r1
regular_walk.direction.forward=hip_walk_forward_r1
regular_walk.direction.backward=hip_walk_backward_r1
regular_walk.direction.left=hip_strafe_left_r1
regular_walk.direction.right=hip_strafe_right_r1
ads.asset=ads/asset.vra
ads.entry.clip=ads_entry_r1
ads.hold.clip=ads_hold_r1
ads.exit.clip=ads_exit_r1
reload.tactical.asset=reload/asset.vra
reload.tactical.clip=reload_current_wip
"""


def write(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(value, encoding="utf-8")
    return path


def write_json(root, relative, value):
    return write(root, relative, json.dumps(value, sort_keys=True) + "\n")


class ReleasePackageGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="release-package-guard-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.artifact = self.root / "artifact"
        self.staged = self.root / "staged"
        self.contract = {
            "schema": "rust-duty-blender-source/v1",
            "file": "current.blend",
            "sha256": "a" * 64,
            "bytes": 123,
            "action": "current_action",
            "clip": "reload_current_wip",
            "native_range": [0, 156],
            "native_fps": [60000, 1001],
            "unreviewed_prefix": [0, 48],
            "additional_selections": [
                {"id": key, "action": key + "_action", "clip": key + "_clip",
                 "native_range": [index, index]}
                for index, key in enumerate(SELECTIONS)
            ],
        }
        write(self.source, "assets/animations.cfg", CONFIG)
        write_json(self.source, "assets/source/reload/source.json", self.contract)
        write(self.artifact, "assets/animations.cfg", CONFIG)
        for family in FAMILIES:
            self.make_pack(Path("assets") / family)
        write_json(self.artifact, "assets/reload/source.json", self.contract)
        for extra in self.contract["additional_selections"]:
            selected = {key: value for key, value in self.contract.items()
                        if key not in ("additional_selections", "unreviewed_prefix")}
            selected.update(extra)
            folder = Path("assets/reload/alternates") / extra["id"]
            self.make_pack(folder)
            write_json(self.artifact, folder / "source.json", selected)
        for relative in ("LICENSE", "THIRD_PARTY_LICENSES.txt",
                         "updater/notices/THIRD_PARTY_UPDATER_LICENSES.txt",
                         "docs/ANIMATION_SLOTS.md", "README.md"):
            write(self.artifact, relative, "fixture: " + relative + "\n")
        write(self.artifact, "vector-range", b"\x7fELF native game fixture")
        write(self.artifact, "settings.cfg", "mouse_sensitivity=0.75\n")
        # The selected checkout owns frozen locomotion bytes and immutable
        # authored recipes; regenerated output hashes may differ from its cache.
        for family in ("locomotion", "walk", "ads"):
            relative = Path("assets") / family / "manifest.json"
            write(self.source, relative, (self.artifact / relative).read_bytes())

    def make_pack(self, folder):
        files = {}
        for name in COMPANIONS:
            data = (str(folder) + "/" + name + " fixture\n").encode()
            write(self.artifact, folder / name, data)
            files[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        manifest = {"files": files}
        if folder in (Path("assets/walk"), Path("assets/ads"), Path("assets/directional")):
            family = folder.name
            blend_file = {
                "walk": "assets/authoring/locomotion/locomotion.blend",
                "ads": "assets/authoring/ads/ads.blend",
                "directional": "assets/authoring/locomotion_directional/r5/halcyon_hip_directional_r5.blend",
            }[family]
            blend_bytes = (family + " immutable authored fixture\n").encode()
            write(self.source, blend_file, blend_bytes)
            manifest.update({
                "schema": "fixture-authored-" + family,
                "clip_count": 1,
                "clip_names": [family + "_clip"],
                "source": {
                    "file": blend_file, "bytes": len(blend_bytes),
                    "sha256": hashlib.sha256(blend_bytes).hexdigest(),
                    "action": family + "_action", "fps": 60,
                    "frame_start": 1, "frame_end": 45,
                    "fbx": {"file": "export.fbx", "bytes": 100, "sha256": "c" * 64},
                },
                "repository_transport": {},
                "validation": {"maximum_skin_error_m": 0.000001},
                "preservation": {"baseline_bytes_preserved": True},
            })
        write_json(self.artifact, folder / "manifest.json", manifest)
        write_json(self.artifact, folder / "parity.json", {"passed": True})
        write_json(self.artifact, folder / "conversion.json", {"fixture": True})
        write_json(self.artifact, folder / "export-manifest.json", {"fixture": True})
        write(self.artifact, folder / "README.md", "Fixture runtime pack.\n")

    def stage_fixture(self, *, update=True):
        shutil.copytree(self.artifact, self.staged)
        if update:
            (self.staged / "settings.cfg").unlink()
        return self.staged

    def make_zip(self, *, omit=(), overrides=None, extras=()):
        archive = self.root / "game.zip"
        overrides = overrides or {}
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as stream:
            for path in sorted(self.staged.rglob("*")):
                if path.is_file():
                    relative = path.relative_to(self.staged).as_posix()
                    if relative not in omit:
                        stream.writestr(relative, overrides.get(relative, path.read_bytes()))
            for name, data in extras:
                stream.writestr(name, data)
        return archive

    def add_jump(self, binding="jump.asset=jump/asset.vra"):
        for root in (self.source, self.artifact):
            write(root, "assets/animations.cfg", CONFIG + binding + "\n")
        self.make_pack(Path("assets/jump"))
        takes = [{"name": name, "action": name + "_r7", "loop": False,
                  "frame_start": 1, "frame_end": end}
                 for name, end in (("jump_takeoff", 12), ("jump_air", 24), ("jump_land", 29))]
        config = {"schema": "rust-duty-jump-authoring-export/v1",
                  "source_file": "halcyon_jump.blend", "source_sha256": "e" * 64,
                  "source_fps": 60, "bake_hz": 480, "source_takes": takes}
        write_json(self.source, "assets/authoring/jump/export_config.json", config)
        path = self.artifact / "assets/jump/manifest.json"
        manifest = json.loads(path.read_text())
        manifest.update(schema="rust-duty-authored-jump-distribution/v1",
                        source={"file": "assets/authoring/jump/halcyon_jump.blend",
                                "sha256": "e" * 64, "fps": 60, "bake_hz": 480},
                        jump_clips=[take | {"duration": (take["frame_end"] - 1) / 60}
                                    for take in takes])
        path.write_text(json.dumps(manifest))
        return path

    def test_jump_recipe_and_spaced_runtime_binding_pass(self):
        self.add_jump("  jump.asset = jump/asset.vra  ")
        assets = release.verify_source_contract(self.source, self.artifact)
        self.assertIn("assets/jump/asset.vra", assets)

    def test_bound_jump_cannot_be_missing_from_artifact(self):
        self.add_jump()
        (self.artifact / "assets/jump/asset.vrs").unlink()
        with self.assertRaises(ValueError):
            release.verify_source_contract(self.source, self.artifact)

    def test_staging_cannot_silently_drop_jump(self):
        self.add_jump()
        shutil.copytree(self.artifact, self.staged)
        shutil.rmtree(self.staged / "assets/jump")
        with self.assertRaises(ValueError):
            release.verify_staged_assets(self.artifact, self.staged, update=False)

    def test_jump_source_and_take_drift_fail_independently(self):
        path = self.add_jump()
        original = json.loads(path.read_text())
        for label in ("source", "action", "frame", "loop", "duration"):
            with self.subTest(label=label):
                doc = copy.deepcopy(original)
                if label == "source":
                    doc["source"]["sha256"] = "f" * 64
                else:
                    key, value = {"action": ("action", "jump_air_r6"),
                                  "frame": ("frame_end", 25),
                                  "loop": ("loop", True),
                                  "duration": ("duration", 0.5)}[label]
                    doc["jump_clips"][1][key] = value
                path.write_text(json.dumps(doc))
                with self.assertRaises(ValueError):
                    release.verify_source_contract(self.source, self.artifact)

    def test_jump_companion_hash_mismatch_fails(self):
        self.add_jump()
        with (self.artifact / "assets/jump/asset.vra").open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaises(ValueError):
            release.verify_source_contract(self.source, self.artifact)

    def test_duplicate_or_noncanonical_jump_binding_fails(self):
        for binding in ("jump.asset=jump/other.vra",
                        "jump.asset=jump/asset.vra\njump.asset=jump/asset.vra"):
            with self.subTest(binding=binding):
                self.add_jump(binding)
                with self.assertRaises(ValueError):
                    release.verify_source_contract(self.source, self.artifact)

    def test_exact_source_and_all_selected_alternates_pass(self):
        release.verify_source_contract(self.source, self.artifact)

    def test_source_contract_uses_json_semantics_for_selection(self):
        path = self.artifact / "assets/reload/source.json"
        path.write_text(json.dumps(self.contract, indent=4), encoding="utf-8")
        release.verify_source_contract(self.source, self.artifact)

    def test_bindings_allow_only_crlf_lf_portability_without_rewriting_bytes(self):
        source_path = self.source / "assets/animations.cfg"
        artifact_path = self.artifact / "assets/animations.cfg"
        lf = CONFIG.encode("utf-8")
        crlf = lf.replace(b"\n", b"\r\n")
        for source_bytes, artifact_bytes in ((lf, crlf), (crlf, lf), (crlf, crlf)):
            with self.subTest(source_crlf=source_bytes.count(b"\r\n"),
                              artifact_crlf=artifact_bytes.count(b"\r\n")):
                source_path.write_bytes(source_bytes)
                artifact_path.write_bytes(artifact_bytes)
                release.verify_source_contract(self.source, self.artifact)
                self.assertEqual(source_path.read_bytes(), source_bytes)
                self.assertEqual(artifact_path.read_bytes(), artifact_bytes)
        source_path.write_bytes(lf)
        for artifact_bytes in (
                crlf.replace(b"ads/asset.vra", b"ads/stale.vra"),
                crlf.replace(b"ads.asset=", b"ads.asset ="),
                crlf + b"# newly added comment\r\n",
                lf.replace(b"\n", b"\r"),
                lf.replace(b"\n", b"\r", 1)):
            with self.subTest(changed_bytes=artifact_bytes):
                artifact_path.write_bytes(artifact_bytes)
                with self.assertRaises(ValueError):
                    release.verify_source_contract(self.source, self.artifact)
                self.assertEqual(artifact_path.read_bytes(), artifact_bytes)

    def test_missing_or_downgraded_animation_manifest_fails(self):
        path = self.artifact / "assets/animations.cfg"
        for value in (None, "locomotion.asset=locomotion/asset.vra\n",
                      CONFIG.replace("ads.asset=ads/asset.vra\n", "")):
            with self.subTest(manifest=value):
                if value is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_text(value, encoding="utf-8")
                with self.assertRaises(ValueError):
                    release.verify_source_contract(self.source, self.artifact)

    def test_same_selection_shape_from_another_source_fails(self):
        contract = copy.deepcopy(self.contract)
        contract["sha256"] = "b" * 64
        write_json(self.artifact, "assets/reload/source.json", contract)
        with self.assertRaises(ValueError):
            release.verify_source_contract(self.source, self.artifact)

    def test_artifact_cannot_omit_source_selected_alternates(self):
        contract = copy.deepcopy(self.contract)
        contract["additional_selections"] = []
        write_json(self.artifact, "assets/reload/source.json", contract)
        shutil.rmtree(self.artifact / "assets/reload/alternates")
        with self.assertRaises(ValueError):
            release.verify_source_contract(self.source, self.artifact)

    def test_each_missing_or_modified_alternate_source_fails(self):
        for key in SELECTIONS:
            path = self.artifact / "assets/reload/alternates" / key / "source.json"
            original = path.read_bytes()
            for mutation in ("missing", "wrong action", "wrong source"):
                with self.subTest(selection=key, mutation=mutation):
                    if mutation == "missing":
                        path.unlink()
                    else:
                        contract = json.loads(original)
                        contract["action" if mutation == "wrong action" else "sha256"] = "stale"
                        path.write_text(json.dumps(contract), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        release.verify_source_contract(self.source, self.artifact)
                    path.write_bytes(original)

    def test_manifest_cannot_claim_a_different_raw_hash(self):
        for family in ("locomotion", "walk", "ads"):
            path = self.artifact / "assets" / family / "manifest.json"
            original = path.read_bytes()
            with self.subTest(family=family):
                manifest = json.loads(original)
                manifest["files"]["asset.vra"]["sha256"] = "b" * 64
                path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaises(ValueError):
                    release.verify_source_contract(self.source, self.artifact)
                path.write_bytes(original)

    def test_regenerated_walk_outputs_preserve_immutable_recipe(self):
        path = self.artifact / "assets/walk/manifest.json"
        manifest = json.loads(path.read_bytes())
        raw = self.artifact / "assets/walk/asset.vra"
        regenerated = raw.read_bytes() + b"freshly regenerated output\n"
        raw.write_bytes(regenerated)
        manifest["files"]["asset.vra"] = {
            "bytes": len(regenerated), "sha256": hashlib.sha256(regenerated).hexdigest(),
        }
        manifest["source"]["fbx"].update(bytes=250, sha256="d" * 64)
        manifest["validation"]["maximum_skin_error_m"] = 0.000002
        manifest["repository_transport"] = {"fixture": "different generated transport"}
        manifest["preservation"] = {"fixture": "different generated verification result"}
        write_json(self.artifact, "assets/walk/manifest.json", manifest)
        release.verify_source_contract(self.source, self.artifact)
        self.stage_fixture()
        release.verify_staged_assets(self.artifact, self.staged, update=True)
        self.assertEqual((self.staged / "assets/walk/asset.vra").read_bytes(), regenerated)

    def test_regenerated_walk_requires_matching_raw_output_digest(self):
        path = self.artifact / "assets/walk/asset.vra"
        original = path.read_bytes()
        path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        with self.assertRaises(ValueError):
            release.verify_source_contract(self.source, self.artifact)

    def test_regenerated_walk_cannot_change_source_or_clip_recipe(self):
        path = self.artifact / "assets/walk/manifest.json"
        original = json.loads(path.read_bytes())
        mutations = (
            lambda value: value["source"].update(sha256="b" * 64),
            lambda value: value["source"].update(bytes=value["source"]["bytes"] + 1),
            lambda value: value["source"].update(action="other_action"),
            lambda value: value["source"].update(frame_end=46),
            lambda value: value.update(clip_names=["other_clip"]),
            lambda value: value.update(clip_count=2),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                manifest = copy.deepcopy(original)
                mutate(manifest)
                write_json(self.artifact, "assets/walk/manifest.json", manifest)
                with self.assertRaises(ValueError):
                    release.verify_source_contract(self.source, self.artifact)

    def test_regenerated_walk_source_hash_binds_actual_selected_blend(self):
        manifest = json.loads((self.artifact / "assets/walk/manifest.json").read_bytes())
        source_file = self.source / manifest["source"]["file"]
        original = source_file.read_bytes()
        source_file.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        with self.assertRaises(ValueError):
            release.verify_source_contract(self.source, self.artifact)

    def test_unknown_source_asset_binding_fails_closed(self):
        config = CONFIG + "fire.asset=future_fire/asset.vra\n"
        write(self.source, "assets/animations.cfg", config)
        write(self.artifact, "assets/animations.cfg", config)
        self.make_pack(Path("assets/future_fire"))
        with self.assertRaises(ValueError):
            release.verify_source_contract(self.source, self.artifact)

    def test_complete_update_preserves_all_runtime_assets(self):
        self.stage_fixture(update=True)
        release.verify_staged_assets(self.artifact, self.staged, update=True)

    def test_fresh_build_keeps_default_settings(self):
        self.stage_fixture(update=False)
        release.verify_staged_assets(self.artifact, self.staged, update=False)
        self.assertEqual((self.staged / "settings.cfg").read_bytes(),
                         (self.artifact / "settings.cfg").read_bytes())

    def test_legacy_43_clip_only_stage_fails(self):
        self.stage_fixture()
        for family in ("walk", "ads", "directional", "reload"):
            shutil.rmtree(self.staged / "assets" / family)
        (self.staged / "assets/animations.cfg").unlink()
        with self.assertRaises(ValueError):
            release.verify_staged_assets(self.artifact, self.staged, update=True)

    def test_every_runtime_companion_is_required(self):
        self.stage_fixture()
        for family in FAMILIES:
            for name in COMPANIONS:
                path = self.staged / "assets" / family / name
                original = path.read_bytes()
                with self.subTest(family=family, companion=name):
                    path.unlink()
                    with self.assertRaises(ValueError):
                        release.verify_staged_assets(self.artifact, self.staged, update=True)
                    path.write_bytes(original)

    def test_truncated_artifact_and_matching_stage_still_fail(self):
        for family in ("walk", "ads", "directional", "reload"):
            with self.subTest(family=family):
                path = self.artifact / "assets" / family / "asset.vra"
                original = path.read_bytes()
                path.unlink()
                self.stage_fixture()
                with self.assertRaises(ValueError):
                    release.verify_staged_assets(self.artifact, self.staged, update=True)
                shutil.rmtree(self.staged)
                path.write_bytes(original)

    def test_selected_alternate_companion_cannot_disappear(self):
        self.stage_fixture()
        for key in SELECTIONS:
            path = self.staged / "assets/reload/alternates" / key / "asset.vra"
            original = path.read_bytes()
            with self.subTest(selection=key):
                path.unlink()
                with self.assertRaises(ValueError):
                    release.verify_staged_assets(self.artifact, self.staged, update=True)
                path.write_bytes(original)

    def test_same_size_runtime_mutation_fails(self):
        self.stage_fixture()
        path = self.staged / "assets/directional/asset.vra"
        original = path.read_bytes()
        path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        with self.assertRaises(ValueError):
            release.verify_staged_assets(self.artifact, self.staged, update=True)

    def test_future_managed_member_cannot_be_silently_dropped(self):
        self.stage_fixture()
        write(self.artifact, "assets/ads/new-required-metadata.json", "{}")
        with self.assertRaises(ValueError):
            release.verify_staged_assets(self.artifact, self.staged, update=True)

    def test_noncompanion_metadata_and_bindings_are_preserved(self):
        self.stage_fixture()
        for relative in ("assets/animations.cfg", "assets/ads/parity.json",
                         "assets/reload/alternates/opening/source.json"):
            path = self.staged / relative
            original = path.read_bytes()
            with self.subTest(relative=relative):
                path.unlink()
                with self.assertRaises(ValueError):
                    release.verify_staged_assets(self.artifact, self.staged, update=True)
                path.write_bytes(original)

    def test_update_rejects_settings_private_assets_and_user_state(self):
        self.stage_fixture()
        for relative in ("settings.cfg", "private-assets/soldier.bin",
                         "assets/private-assets/soldier.bin", "assets/fps-arms.vrs",
                         "userdata/save.dat", ".rust-duty-updates/install.json"):
            with self.subTest(relative=relative):
                path = write(self.staged, relative, b"must not ship")
                with self.assertRaises(ValueError):
                    release.verify_staged_assets(self.artifact, self.staged, update=True)
                path.unlink()

    def test_symlink_companion_is_rejected_even_with_identical_bytes(self):
        self.stage_fixture()
        path = self.staged / "assets/ads/asset.vrm"
        path.unlink()
        try:
            path.symlink_to(self.artifact / "assets/ads/asset.vrm")
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")
        with self.assertRaises(ValueError):
            release.verify_staged_assets(self.artifact, self.staged, update=True)

    def test_exact_archive_inventory_and_contents_pass(self):
        self.stage_fixture(update=False)
        release.verify_archive(self.make_zip(), self.staged)

    def test_archive_cannot_omit_asset_or_settings(self):
        self.stage_fixture(update=False)
        for relative in ("assets/animations.cfg", "assets/directional/asset.vra",
                         "assets/reload/alternates/pickup/asset.vrs", "settings.cfg"):
            with self.subTest(relative=relative):
                with self.assertRaises(ValueError):
                    release.verify_archive(self.make_zip(omit=(relative,)), self.staged)

    def test_archive_cannot_change_asset_bytes(self):
        self.stage_fixture(update=False)
        archive = self.make_zip(overrides={"assets/ads/asset.vra": b"modified"})
        with self.assertRaises(ValueError):
            release.verify_archive(archive, self.staged)

    def test_archive_rejects_extra_or_unsafe_members(self):
        self.stage_fixture(update=False)
        for name in ("unexpected.txt", "../escape.txt", "/absolute.txt",
                     "assets\\ads\\asset.vra", "private-assets/soldier.bin"):
            with self.subTest(name=name):
                archive = self.make_zip(extras=((name, b"must not ship"),))
                with self.assertRaises(ValueError):
                    release.verify_archive(archive, self.staged)

    def test_archive_rejects_duplicate_members(self):
        self.stage_fixture(update=False)
        relative = "assets/animations.cfg"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            archive = self.make_zip(extras=((relative, (self.staged / relative).read_bytes()),))
        with self.assertRaises(ValueError):
            release.verify_archive(archive, self.staged)

    def test_archive_rejects_symlink_members(self):
        self.stage_fixture(update=False)
        relative = "assets/ads/asset.vra"
        archive = self.make_zip(omit=(relative,))
        with zipfile.ZipFile(archive, "a") as stream:
            entry = zipfile.ZipInfo(relative)
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            stream.writestr(entry, (self.staged / relative).read_bytes())
        with self.assertRaises(ValueError):
            release.verify_archive(archive, self.staged)

    def test_archive_allows_only_real_parent_directories(self):
        self.stage_fixture(update=False)
        archive = self.make_zip(extras=(("assets/", b""), ("assets/ads/", b"")))
        release.verify_archive(archive, self.staged)
        for name in ("../escape/", "/absolute/", "unrelated/", "assets/ads/../../escape/"):
            with self.subTest(name=name):
                archive = self.make_zip(extras=((name, b""),))
                with self.assertRaises(ValueError):
                    release.verify_archive(archive, self.staged)

    def test_archive_rejects_symlink_directory_entries(self):
        self.stage_fixture(update=False)
        archive = self.make_zip()
        with zipfile.ZipFile(archive, "a") as stream:
            entry = zipfile.ZipInfo("assets/")
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            stream.writestr(entry, b"elsewhere")
        with self.assertRaises(ValueError):
            release.verify_archive(archive, self.staged)

    def make_identity(self):
        source_sha = "a" * 40
        executable = self.artifact / "vector-range"
        identity = {
            "repository": "RHS059/rust_duty",
            "source": {"commit": source_sha},
            "version": "0.1.7",
            "executable": {"name": "vector-range", "size": executable.stat().st_size,
                           "sha256": hashlib.sha256(executable.read_bytes()).hexdigest()},
        }
        write_json(self.artifact, "BUILD_IDENTITY.json", identity)
        write(self.source, "tools/package_game.py", "# Execution is mocked in this boundary test.\n")
        return source_sha, identity

    def test_stage_executes_exact_source_packager_with_required_generated_flag(self):
        source_sha, _ = self.make_identity()
        with mock.patch.object(release.subprocess, "check_output", return_value=source_sha + "\n") as head:
            with mock.patch.object(release.subprocess, "run", side_effect=lambda *a, **k: self.stage_fixture()) as run:
                release.stage_game(self.source, source_sha, self.artifact, "vector-range",
                                   self.staged, update=True, version="0.1.7")
        head.assert_called_once_with(["git", "-C", str(self.source), "rev-parse", "HEAD"], text=True)
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(command[1], str((self.source / "tools/package_game.py").resolve()))
        self.assertEqual(command[2], "stage")
        self.assertEqual(command[command.index("--root") + 1], str(self.artifact.resolve()))
        self.assertIn("--require-generated", command)
        self.assertIn("--update", command)
        self.assertTrue(run.call_args.kwargs["check"])

    def test_wrong_toolchain_head_prevents_packager_execution(self):
        source_sha, _ = self.make_identity()
        with mock.patch.object(release.subprocess, "check_output", return_value="b" * 40 + "\n"):
            with mock.patch.object(release.subprocess, "run") as run:
                with self.assertRaises(ValueError):
                    release.stage_game(self.source, source_sha, self.artifact, "vector-range", self.staged)
                run.assert_not_called()
        self.assertFalse(self.staged.exists())

    def test_stage_cannot_omit_or_change_verified_executable(self):
        source_sha, _ = self.make_identity()
        for mutation in ("missing", "changed"):
            def fake_stage(*args, **kwargs):
                self.stage_fixture()
                path = self.staged / "vector-range"
                if mutation == "missing":
                    path.unlink()
                else:
                    path.write_bytes(b"\x7fELF wrong native game")
            with self.subTest(mutation=mutation):
                with mock.patch.object(release.subprocess, "check_output", return_value=source_sha + "\n"):
                    with mock.patch.object(release.subprocess, "run", side_effect=fake_stage):
                        with self.assertRaises(ValueError):
                            release.stage_game(self.source, source_sha, self.artifact, "vector-range",
                                               self.staged, update=True, version="0.1.7")
                shutil.rmtree(self.staged)

    def test_artifact_source_binary_and_version_identity_fail_before_execution(self):
        source_sha, original = self.make_identity()
        for mutation in ("source", "binary", "version"):
            identity = copy.deepcopy(original)
            if mutation == "source":
                identity["source"]["commit"] = "b" * 40
            elif mutation == "binary":
                identity["executable"]["sha256"] = "b" * 64
            else:
                identity["version"] = "0.1.6"
            write_json(self.artifact, "BUILD_IDENTITY.json", identity)
            with self.subTest(mutation=mutation):
                with mock.patch.object(release.subprocess, "check_output", return_value=source_sha + "\n"):
                    with mock.patch.object(release.subprocess, "run") as run:
                        with self.assertRaises(ValueError):
                            release.stage_game(self.source, source_sha, self.artifact, "vector-range",
                                               self.staged, version="0.1.7")
                        run.assert_not_called()
                self.assertFalse(self.staged.exists())

    def test_existing_stage_is_never_replaced(self):
        source_sha, _ = self.make_identity()
        sentinel = write(self.staged, "sentinel", b"preserve me")
        with mock.patch.object(release.subprocess, "check_output", return_value=source_sha + "\n"):
            with mock.patch.object(release.subprocess, "run") as run:
                with self.assertRaises(ValueError):
                    release.stage_game(self.source, source_sha, self.artifact, "vector-range", self.staged)
                run.assert_not_called()
        self.assertEqual(sentinel.read_bytes(), b"preserve me")

    def make_bundle(self, directory=None):
        bundle = self.root / "game.rdb"
        release_update.pack(directory or self.staged, bundle, "vector-range")
        return bundle

    def test_complete_rdb_preserves_exact_update_members(self):
        self.stage_fixture()
        release.verify_bundle_members(self.make_bundle(), self.staged)

    def test_rdb_rejects_second_stage_filtering_and_omitted_alternate(self):
        self.stage_fixture()
        filtered = self.root / "filtered"
        shutil.copytree(self.staged, filtered)
        for relative in ("assets/ads/asset.vra", "assets/reload/alternates/reset/asset.vrm"):
            path = filtered / relative
            original = path.read_bytes()
            with self.subTest(relative=relative):
                path.unlink()
                with self.assertRaises(ValueError):
                    release.verify_bundle_members(self.make_bundle(filtered), self.staged)
                path.write_bytes(original)

    def test_rdb_rejects_modified_staged_bytes(self):
        self.stage_fixture()
        bundle = self.make_bundle()
        path = self.staged / "assets/walk/asset.vra"
        original = path.read_bytes()
        path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        with self.assertRaises(ValueError):
            release.verify_bundle_members(bundle, self.staged)

    def test_rdb_parser_rejects_truncation_trailing_bytes_and_invalid_magic(self):
        self.stage_fixture()
        bundle = self.make_bundle()
        original = bundle.read_bytes()
        for data in (original[:11], original[:-1], original + b"extra", b"INVALID!" + original[8:]):
            with self.subTest(length=len(data)):
                bundle.write_bytes(data)
                with self.assertRaises(ValueError):
                    release.bundle_records(bundle)

    def test_rdb_parser_rejects_duplicate_and_protected_paths(self):
        bundle = self.root / "invalid.rdb"
        for names in (("vector-range", "vector-range"), ("settings.cfg",),
                      ("private-assets/soldier.bin",), ("../escape",)):
            data = bytearray(b"RDBND001" + struct.pack("<I", len(names)))
            for name in names:
                encoded = name.encode("ascii")
                data.extend(struct.pack("<H", len(encoded)) + encoded + b"\0" + struct.pack("<Q", 1) + b"x")
            bundle.write_bytes(data)
            with self.subTest(names=names):
                with self.assertRaises(ValueError):
                    release.bundle_records(bundle)

    def make_installed_fixture(self, *, legacy=False):
        self.stage_fixture()
        if legacy:
            for family in ("walk", "ads", "directional", "reload"):
                shutil.rmtree(self.staged / "assets" / family)
            (self.staged / "assets/animations.cfg").unlink()
        bundle = self.make_bundle()
        install = self.root / "install"
        version_dir = install / "versions/7-0.1.7"
        shutil.copytree(self.staged, version_dir)
        shutil.copy2(bundle, version_dir / "payload.rdb")
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
        manifest = {
            "version": "0.1.7", "sequence": 7, "entrypoint": "vector-range",
            "bundle": {"name": "game.rdb", "size": bundle.stat().st_size, "sha256": digest},
        }
        state = {
            "active": {"version": "0.1.7", "sequence": 7, "bundle_sha256": digest,
                       "entrypoint": "vector-range"},
            "highest_sequence": 7, "pending_launch": False,
        }
        write_json(install, "install.json", state)
        return install, version_dir, manifest, state

    def test_live_smoke_accepts_verified_full_authored_assets(self):
        install, version_dir, manifest, state = self.make_installed_fixture()
        sentinel = write(install, "private-assets/user-sentinel", b"user owned")
        self.assertTrue((version_dir / "assets/ads/asset.vra").is_file())
        self.assertEqual(smoke_live_update.validate_install(install, manifest), state)
        self.assertEqual(sentinel.read_bytes(), b"user owned")

    def test_live_smoke_rejects_missing_or_changed_extracted_asset(self):
        install, version_dir, manifest, _ = self.make_installed_fixture()
        for relative in ("assets/ads/asset.vra", "assets/reload/alternates/pickup/asset.vrm"):
            path = version_dir / relative
            original = path.read_bytes()
            for mutation in ("missing", "changed"):
                with self.subTest(relative=relative, mutation=mutation):
                    if mutation == "missing":
                        path.unlink()
                    else:
                        path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
                    with self.assertRaises(ValueError):
                        smoke_live_update.validate_install(install, manifest)
                    path.write_bytes(original)

    def test_live_smoke_rejects_internally_consistent_legacy_43_only_install(self):
        install, _, manifest, _ = self.make_installed_fixture(legacy=True)
        with self.assertRaises(ValueError):
            smoke_live_update.validate_install(install, manifest)


if __name__ == "__main__":
    unittest.main()
