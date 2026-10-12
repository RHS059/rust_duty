#!/usr/bin/env python3
"""Build fresh authored runtime inputs in an explicitly disposable pinned checkout.

No download, installation, compilation, rendering, GPU or publication is performed.
The caller provides Blender 4.3.2 and the already compiled production CPU sampler.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

SOURCE_COMMIT = "49c3bf9b3d0482ce81a7d50683904bda28468d7d"
JUMP_COMMIT = "e9317f90ea171976306e2f17c111325d948ea357"
JUMP_RECORD = {"bytes": 10470527, "sha256": "a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b"}
PINNED_FILES = json.loads(r'''{
  ".github/actions/setup-blender/action.yml": {
    "bytes": 1322,
    "sha256": "c5fc8884a2dfeb35021c5957dc8c71ff81a1170509071060b5ca93314f431655"
  },
  "Cargo.lock": {
    "bytes": 105160,
    "sha256": "2aa35ed5561b7e40f515520ec36cb7eaa5c4175f12f0fcf9c764dd0ae6cbdeef"
  },
  "Cargo.toml": {
    "bytes": 915,
    "sha256": "ec02a76fb9e8eb29178d707c0f6cfea8206b0299d81f6594fd3cfe0707f55584"
  },
  "assets/animations.cfg": {
    "bytes": 3298,
    "sha256": "7ab3a60c5c271163de3a7349e69d0d07db85aa759737be0264cb29e6134e84ee"
  },
  "assets/authoring/ads/ads.blend": {
    "bytes": 9446001,
    "sha256": "3acdf3e2d04757d719ba59ede08decdf8bad48e2e87d9448046fe8edcbba4f58"
  },
  "assets/authoring/ads/export_config.json": {
    "bytes": 1381,
    "sha256": "79e26b9bde09d406ce8f65ff4d643eec9615a7dabf81dbb8f775c63514806278"
  },
  "assets/authoring/ads/source_integrity.json": {
    "bytes": 173243,
    "sha256": "84d8ec6f8d0560e64f8d4f3e853cc17def887df954930eccc878a81ec9238bfc"
  },
  "assets/authoring/ads/source_integrity.py": {
    "bytes": 2898,
    "sha256": "d22ae8dcc117e29ffb7d746772efce015010407cbb1ddce22924a31746e831ca"
  },
  "assets/authoring/jump/export_config.json": {
    "bytes": 1642,
    "sha256": "a8b483b9bcf73c86c31667890b5c59ef3f498fbe0ddcec08edd7f4ae8d244d95"
  },
  "assets/authoring/locomotion/export_config.json": {
    "bytes": 13784,
    "sha256": "9636c75a25920f83a5ae612ecfc74ee3671836af7c25484a55b9c765821f077b"
  },
  "assets/authoring/locomotion/export_locomotion.py": {
    "bytes": 11084,
    "sha256": "165531d287844efcedbf7eb8b12f12115879da1fd283cd009414eb53f0a33cc0"
  },
  "assets/authoring/locomotion/locomotion.blend": {
    "bytes": 9352824,
    "sha256": "1b01f49d7fe92f39c7bd180823ee4556a0074dd9ff8ef9c10b3fb4d3f3059e43"
  },
  "assets/authoring/locomotion/source_integrity.json": {
    "bytes": 171884,
    "sha256": "3a4d552023dd78c908548a657e69a1c04d0b26b60e4da5e536eb46b3ebf327f2"
  },
  "assets/authoring/locomotion/source_integrity.py": {
    "bytes": 2898,
    "sha256": "d22ae8dcc117e29ffb7d746772efce015010407cbb1ddce22924a31746e831ca"
  },
  "assets/authoring/locomotion_directional/export_directional_preview.py": {
    "bytes": 10968,
    "sha256": "e94498857bc7744604d5381cf101cec0608ffda30141bb30dedf9918d2285e74"
  },
  "assets/authoring/locomotion_directional/r5/halcyon_hip_directional_r5.blend": {
    "bytes": 9922429,
    "sha256": "36d76491c2cf6238b8a1e10069dddd5b0d63e199063e1f4012b34f3fd4b1e18d"
  },
  "assets/authoring/locomotion_directional/r5/source_integrity.json": {
    "bytes": 172777,
    "sha256": "128d2f360c465964ee99d5526ed382a86a2d544b639c5b58ddf40f5e54152924"
  },
  "assets/authoring/locomotion_directional/runtime_export_config.json": {
    "bytes": 5614,
    "sha256": "5f21226b790945ba1d783ce4c025d669a60ce6ab4860b3911eda4eba400fc409"
  },
  "assets/locomotion/README.md": {
    "bytes": 1627,
    "sha256": "b7774fbef7355e5e0e647a887ee33bb3f9a0bfeef2a127733588a2daca33f28b"
  },
  "assets/locomotion/asset.vra": {
    "bytes": 10736787,
    "sha256": "d02d04d4adb429b6493bf3347b302dc007bb7b99f4761da3c2b314e6d313c6ab"
  },
  "assets/locomotion/asset.vrm": {
    "bytes": 10641724,
    "sha256": "d11736162b2cda993db3cdd5d4015aff2b151ea6377b8b954370b54006e02d67"
  },
  "assets/locomotion/asset.vrs.gz": {
    "bytes": 4088316,
    "sha256": "d2bd669fe44644de6a536ddb4e6829fb9571a84b95b4d74166e3c055fce76760"
  },
  "assets/locomotion/manifest.json": {
    "bytes": 3474,
    "sha256": "9d8de9f33304ce190a6eabcb4ac696cd995145d4bcbe13e05ec3fd891b628639"
  },
  "assets/source/reload/current.blend": {
    "bytes": 8247987,
    "sha256": "8cec36c6bfcc4967cb80629b40ecdced3c0b5507914aec7eb3d2d614f2d758fd"
  },
  "assets/source/reload/source.json": {
    "bytes": 1657,
    "sha256": "c3af430be9e30a3e4acf8fd0f98a037767792ddaaf8ceeb19bd0f5bdc75930d6"
  },
  "assets/weapons/hk416a5.vrm": {
    "bytes": 3901244,
    "sha256": "082b8302a39c8fd3218f3c732f8c3a06c1af1fb40f703f8d64f581b38b32d4aa"
  },
  "build.rs": {
    "bytes": 3266,
    "sha256": "e054de56657900e8f2b7cf66a7abd776389164fec60aff4c181f9f3eef7de565"
  },
  "build_number.rs": {
    "bytes": 2002,
    "sha256": "df533d358c8f40b094fb9efd5e914c997a6e943d9076b965947913424c3999c5"
  },
  "docs/ANIMATION_SLOTS.md": {
    "bytes": 14250,
    "sha256": "741786fede1d04764887048470a5865d17feb71317a6eec1c280d166153cff9a"
  },
  "examples/sample_viewmodel_clip.rs": {
    "bytes": 6856,
    "sha256": "82123dbb8be6db54a3780a2b18079a809738cd2559f89de7dcee0aac1d31e22b"
  },
  "profiles/kestrel.cfg": {
    "bytes": 623,
    "sha256": "36a3dd9e677a64e762e97771f949ee5bc5dea09adce57f8c93ad57c6eb1143f8"
  },
  "profiles/m4a1-beta-visual.cfg": {
    "bytes": 2002,
    "sha256": "37f2a7754864753fd845abd7fddcbc02f6d908d4cdd6102a51fefb6038c9fadb"
  },
  "profiles/m4a1-candidate.cfg": {
    "bytes": 1628,
    "sha256": "4ed5e2500933351b3b991ab0a1144a7f41eb8648b83513804ac2b7c2f9a216ea"
  },
  "settings.cfg": {
    "bytes": 1819,
    "sha256": "8bce6b463cedfd5d5534dac606963a4b5b90085a18d5d14e34dd23132cb2a9ca"
  },
  "src/action.rs": {
    "bytes": 24554,
    "sha256": "072d58fd13c8c428c9c866b6f8fc131c39cac45b2da3f91272ab17deae435cf7"
  },
  "src/ammo_supply.rs": {
    "bytes": 11007,
    "sha256": "73ebe7fa399ae62f1a44c3ed15191589c072eda68d9291b226fc9d756a03d5c1"
  },
  "src/ammo_supply_view.rs": {
    "bytes": 6742,
    "sha256": "5184469c248b343fe84729a736f6dc992913cb947d698c2c83555cb3b03aad64"
  },
  "src/animation_manifest.rs": {
    "bytes": 12503,
    "sha256": "e60c65b57e366ca3eefc4b863ff3d3c1289f9fb3a50d9790e7ac9226e6c6a6fc"
  },
  "src/app.rs": {
    "bytes": 75655,
    "sha256": "c282e402b35b0edee452eff30741251b729a936e90431c94387eb14c3cb918da"
  },
  "src/arms.rs": {
    "bytes": 60235,
    "sha256": "69eb12a369f5c9a88d43b1cae1d3a0180228193b94077b2b80afb279664db20f"
  },
  "src/asset.rs": {
    "bytes": 10152,
    "sha256": "eec1033c8e711fd8ee17537e5486d96553735ce32880f1aa0188e86dd9889481"
  },
  "src/asset_path.rs": {
    "bytes": 6992,
    "sha256": "17446ae0902b223ab89dc3488527766a5455af79179a386ab2374fc41a8fc119"
  },
  "src/authored_ads.rs": {
    "bytes": 27476,
    "sha256": "db3faa82cb05f6a7b44cbdeb500af84902f60ab67699bb5d67da714f01e28065"
  },
  "src/authored_jump.rs": {
    "bytes": 6522,
    "sha256": "948c3e31acceec3af04e5fe503eda6599ce3add0397424fdb1dd7a4065e809a1"
  },
  "src/authored_locomotion_adapter.rs": {
    "bytes": 12345,
    "sha256": "6694bcafc9fb9ae24ff11f51e40182cf90ccb691cf78f5e94857d51d7450315e"
  },
  "src/authored_locomotion_path.rs": {
    "bytes": 24395,
    "sha256": "591a1360f747b2a9c99f204bb9664be7e411f31c5f3fd3b39d5da9d39e69a789"
  },
  "src/authored_pose_return.rs": {
    "bytes": 7303,
    "sha256": "2d31138d5d34475a264021e03793b8b2db7953de42e60d7b465dcb90f7317eed"
  },
  "src/authored_reload.rs": {
    "bytes": 5817,
    "sha256": "551ddee6d1204034cba2864e1e194a8d89d7824fe4afd822e273296d94b0bed0"
  },
  "src/authored_viewmodel.rs": {
    "bytes": 48735,
    "sha256": "c87f0a15241d8a03ec3426eef3b6c3809b257789e4d533c9006e80c3807fdaf5"
  },
  "src/authored_walk.rs": {
    "bytes": 16481,
    "sha256": "15383c9d52c721194aaf50903f9143a7d13ece9b6152d8d5763a49e2fa379eec"
  },
  "src/body_presentation.rs": {
    "bytes": 12872,
    "sha256": "65caaa6852bb6758e87c86de74fcf98f66718fbd9fd060956ba6864dead50b7c"
  },
  "src/capture.rs": {
    "bytes": 18262,
    "sha256": "807eb12a983a9dd3f289ca71c0eff7368e722c268b0112f98a26c0f7e5f06d09"
  },
  "src/clock.rs": {
    "bytes": 3912,
    "sha256": "9f2bde0e35e8685bfa9f30d46549bddb8e8352bce0755165bfe0b903591f59bc"
  },
  "src/control.rs": {
    "bytes": 15252,
    "sha256": "325895b12c20358eac25d6fb76244808fc24f8f16727da2cd294385878e881a5"
  },
  "src/draw/facade.rs": {
    "bytes": 52345,
    "sha256": "18ce443544975ef4bac82f2c599a9f0c60f8a8b709a731437f6fa1083e7ca5b6"
  },
  "src/draw/frame_witness.rs": {
    "bytes": 5537,
    "sha256": "fede582c4758f4e429f1389f0fceefb2b8821bf1abed1e57bf664c7248d94fd2"
  },
  "src/draw/geometry.rs": {
    "bytes": 5058,
    "sha256": "75d0a9b9ff434173b4f4460a3c3a08c6149ddee90feaff90f9ec57eb340f7891"
  },
  "src/draw/mod.rs": {
    "bytes": 10228,
    "sha256": "9d3ea1559678bc9c5298bd423bf5546f207285596a25a43a44cd92127248c14a"
  },
  "src/frame_performance.rs": {
    "bytes": 31117,
    "sha256": "dfd68b9970a9b38cfef2b60a8b75238350c89466fc6e5a0d9d54413758c415bd"
  },
  "src/frame_performance_session.rs": {
    "bytes": 19408,
    "sha256": "4b72fe3910f08d2a4dd7e9dcaea7557675451275010c72c75da7b37d654d577c"
  },
  "src/game_update.rs": {
    "bytes": 33271,
    "sha256": "a8fa7df462007faca3666c2937ea64d832a52a62303e6ebe10427045fd53f1f4"
  },
  "src/gpu_telemetry.rs": {
    "bytes": 7594,
    "sha256": "e8f8f1a2781142735a58940ae0b2a6e318a178527ce9459a5b031f84997cc383"
  },
  "src/gpu_telemetry/counters.rs": {
    "bytes": 7782,
    "sha256": "b9c7fa21698c53d32b2d98f0cb9cc4850fa444dd308d065f131656c7b3e13172"
  },
  "src/gpu_telemetry/tests.rs": {
    "bytes": 14612,
    "sha256": "8a9e46c0006944bba3962143e570de0fb36b8fbdec70ecc99eb4391ce69d2465"
  },
  "src/gpu_telemetry/windows.rs": {
    "bytes": 13418,
    "sha256": "d2e6ec48b2017e73a0a811c0a6a52a44c2fff731a4721d6be3b526e827369681"
  },
  "src/graphics_device.rs": {
    "bytes": 18112,
    "sha256": "731d3ad664ed8b8cc358e19f7ec321646af8fbe50872ccf63322128264418e8b"
  },
  "src/hud.rs": {
    "bytes": 16567,
    "sha256": "0a3440310b1ad91812f527eaca9a5cfbcea833f69fe51d2c60baf947c1316ab4"
  },
  "src/input_frame.rs": {
    "bytes": 11246,
    "sha256": "7cff84966ee1af991face3bea79e87bbb3415d38e2381eaf39dba8c8673a4d5d"
  },
  "src/layered_locomotion.rs": {
    "bytes": 26417,
    "sha256": "d089129219f3f2c019b5acdd21ac06f00fc085be5e7595a18353d074cf670105"
  },
  "src/legacy_macroquad/mod.rs": {
    "bytes": 57557,
    "sha256": "f8aff43030d1e2e826fc296b4bcb716c0b13c685e1733b838bc5db09f41bf90c"
  },
  "src/legacy_macroquad/precision_receipt.rs": {
    "bytes": 20236,
    "sha256": "2f1a2a689926ae51643fa353a1aaa1c759a6dc81f4653dbf4fb840765eb3a4be"
  },
  "src/legacy_macroquad/runtime.rs": {
    "bytes": 10383,
    "sha256": "7b65c0c4426458f2c65275b89c1b71b0380d3033eaf865f991b429f18151275d"
  },
  "src/lib.rs": {
    "bytes": 1726,
    "sha256": "d99219a4e4fcc06d73d3841b0b6d6fa40edcb4ac2aa5e1882cd5f66cda7284b1"
  },
  "src/locomotion_presentation.rs": {
    "bytes": 7433,
    "sha256": "d2f7e01e660c40f20f2ae0254c4cb940561777d0c9531490ffe68715db80c495"
  },
  "src/main.rs": {
    "bytes": 6421,
    "sha256": "04f2c0ce85c2ceac6ccf9b215e043df097107749a676dfa3d2661334b6463f41"
  },
  "src/muzzle_fx.rs": {
    "bytes": 36248,
    "sha256": "b49e08e861af65f4d844ad6bf8dd2f7c90d984dc6ae25b61a16bf674bafb93f1"
  },
  "src/pause_menu.rs": {
    "bytes": 65356,
    "sha256": "c08e8fc87407bc9cfda5cfadf7f92eb5802e7abb625e0b66e9d96c5d8f0bca9e"
  },
  "src/platform/audio.rs": {
    "bytes": 7292,
    "sha256": "ba6891e80207593a3bde98b6ee4f99c4c617f2402df05e6fd85047e08fb0d846"
  },
  "src/platform/input.rs": {
    "bytes": 10033,
    "sha256": "c869e553b0697f9fa8679f04c628405a08e3bd0ec30b40fa84f978ca03c417aa"
  },
  "src/platform/launch.rs": {
    "bytes": 7750,
    "sha256": "35427ce4a504af3352dae330d9f4339d8928ef61275c615d1c18976b27a345c3"
  },
  "src/platform/mod.rs": {
    "bytes": 138,
    "sha256": "5aa227aede4fed73c8b410cbf48b575b4d81592d9718502efcc2769f2aaf3b0e"
  },
  "src/platform/runtime.rs": {
    "bytes": 2998,
    "sha256": "cbf57e86d377529ff3eea58028c59eee6cf37e73c119d5cec2710c66ba319395"
  },
  "src/platform/session_focus.rs": {
    "bytes": 25067,
    "sha256": "6b964c7ac72182cb8a99f6e9b1cbdb81c55e83d48a9943601dc734e76213e0fd"
  },
  "src/platform/window.rs": {
    "bytes": 31592,
    "sha256": "485b038b385a5a2f6ff74ee1f57c6a94a902c32bf6ab954a5f86bccd85e085d8"
  },
  "src/reference_motion.rs": {
    "bytes": 9131,
    "sha256": "5a63c94b05f4d959785142cc44c7fcef73c8d3374a06327ac827456537751929"
  },
  "src/render/arena.rs": {
    "bytes": 11542,
    "sha256": "5e39d00125b34d07ec23f845841809c0effa678980b1395988880b7d23674ddb"
  },
  "src/render/backend.rs": {
    "bytes": 8833,
    "sha256": "4a9c1efab9ecb5a462cd55f2a2b9bb10959f2e4d318f53dd439d75a01b6c8603"
  },
  "src/render/capture.rs": {
    "bytes": 7907,
    "sha256": "21cb24be9f79e69c2593451c0ecf697302ded36dc859e40c1c96ccbaadff9487"
  },
  "src/render/device.rs": {
    "bytes": 28061,
    "sha256": "fe742b814bcc55ab3b5d13ad70a03dcef54e5369a7b3a82665a016eec16a6763"
  },
  "src/render/finite_warp_probe.rs": {
    "bytes": 61080,
    "sha256": "69531dbc035e468785d8c501527c671d2becba31eaebb6dcdbc4582a5155fd5e"
  },
  "src/render/font/LICENSE": {
    "bytes": 1501,
    "sha256": "2ab177f9b9aaf988111d76363fe3b73ce29f32eb7f00a7f346acc41499d770e4"
  },
  "src/render/font/ProggyClean.ttf": {
    "bytes": 41208,
    "sha256": "527d2a443ce051f93f7e77b855609722b8cb220a9f104b4aa037be5c90b71324"
  },
  "src/render/frame.rs": {
    "bytes": 25738,
    "sha256": "aad7d066764a658b3dc8a3dbd1eaed2fb3bb69708effbbffe16a9b6fc07d8628"
  },
  "src/render/lines.rs": {
    "bytes": 9655,
    "sha256": "9258cada6ad49cbb3dbd564b6f6c5b9fe78d86d37174f46aa2c1ef3c4f1669fc"
  },
  "src/render/mesh.rs": {
    "bytes": 22798,
    "sha256": "a671a78f50ccc8d872d5e3e1c128859a70488bc6405a532590af3018e5ea85d7"
  },
  "src/render/mesh.wgsl": {
    "bytes": 2261,
    "sha256": "9185a0b16773c8c46ca1a2513832a08c8e8b29c63b00632cfcb61673b71cca41"
  },
  "src/render/mod.rs": {
    "bytes": 883,
    "sha256": "c78768f1c1144a14618960975fe43027293fa1a8a21cb147eea9bef6e44c7bae"
  },
  "src/render/plan.rs": {
    "bytes": 22649,
    "sha256": "c23e97a848435a610f5be0c72341ef8e5090fa2cd66846cda1b29159558a4c7e"
  },
  "src/render/runtime.rs": {
    "bytes": 20650,
    "sha256": "67af6a5ee23d3db06a526abe3b5df6dc5e325365dce436562e1e4e31381a3e48"
  },
  "src/render/sprite2d.rs": {
    "bytes": 1291,
    "sha256": "862180ee20915e6b1ce13f279c90c808d3030a8c6f6cc06eb6e50810056de6d1"
  },
  "src/render/target.rs": {
    "bytes": 7648,
    "sha256": "8e7095a8d6e67efa9ff6671fdfef7727a8887207cd9870b59ce8e0d5b5a44639"
  },
  "src/render/text.rs": {
    "bytes": 24237,
    "sha256": "06ad5a1489c96152f516cfbade027ef2a7fa83f583889bed46c99f5dcd04a446"
  },
  "src/scene_lighting.rs": {
    "bytes": 7974,
    "sha256": "28de8685b9d0442d07294ae0f5db0ea42bd05d13128ad9b38b533a8f6bb10bc4"
  },
  "src/session.rs": {
    "bytes": 20844,
    "sha256": "1b96c95b8a25202e05a1d24e24c220622b05783e01dfce48c9602d2f15f75f69"
  },
  "src/session_focus.rs": {
    "bytes": 144,
    "sha256": "9f2dc43e24e9432181f91d4dc0c454c5065003831f37fb77ae37d3085d34215b"
  },
  "src/settings.rs": {
    "bytes": 19501,
    "sha256": "166107a7b4c0c714f02abfc7605783cb96eb908c40114c797bc0ab06ced17232"
  },
  "src/sim.rs": {
    "bytes": 72979,
    "sha256": "89ff17a11deae683b0b6c09dc5cb3038886c84ee862f7ed0329599ec63149623"
  },
  "src/sim/actions.rs": {
    "bytes": 59544,
    "sha256": "9668f94873e15148e787593612dee1d9afabb821b94a7d236cb7320ce2513e0f"
  },
  "src/skinned_asset.rs": {
    "bytes": 16074,
    "sha256": "f7b98e867468b74f9692b408a9a508423d86445dc260cef940a38fd7555d0f16"
  },
  "src/sound.rs": {
    "bytes": 117,
    "sha256": "d274d5942b7c5132e993ba36586eb6aa33bda5ae286f434fc58ccbd4f54c3a56"
  },
  "src/telemetry_export.rs": {
    "bytes": 17446,
    "sha256": "feff16f92c9d03ddd1dda7e18ccf3bc67ae1699b9857c71e354e7c6443d148ea"
  },
  "src/traversal_replay.rs": {
    "bytes": 5446,
    "sha256": "2db50898acadd5f9911a0304a9b9bcf7995a0d392d6977f1a7939f32b9941ead"
  },
  "src/ui_theme.rs": {
    "bytes": 30410,
    "sha256": "d5c07779b012fc41741dcafb65a94d8700fee9414b41ce424549ed7f0daecee1"
  },
  "src/view_animation.rs": {
    "bytes": 30045,
    "sha256": "4b981f7c9a1f22853cebd5087de96a486fb196609e13c6be19d922a5312387ee"
  },
  "src/viewmodel_animation.rs": {
    "bytes": 24296,
    "sha256": "c3f097585cc94c90b9a0bce986d36b707dbf8970058f5bb2db0e6e058f4b6251"
  },
  "src/viewmodel_draw.rs": {
    "bytes": 17205,
    "sha256": "c37a0961dbe184dabc03f7b0ac1db6c009916a984f2bcf4b8911c103b341f113"
  },
  "src/weapon_animation.rs": {
    "bytes": 28450,
    "sha256": "5a09602514952df18eeb5bcf0ac4092aefb5aa0c9df98bcdc4ffad0226a59b08"
  },
  "src/weapon_ik.rs": {
    "bytes": 6784,
    "sha256": "9fce1ddce7cb77b39f0619bd465f4890fb54f0335461751377cfe66920ec7b36"
  },
  "src/weapon_model.rs": {
    "bytes": 13489,
    "sha256": "b6496c9409485023d97cc8e08e43ccbecacef35c72611e2b1f7fa594a1237071"
  },
  "src/weapon_sway.rs": {
    "bytes": 11919,
    "sha256": "91160e6d84c86dd4b94aef04d20bf7142706a6a20bd9db61d12d54613ccddf5f"
  },
  "src/world_draw.rs": {
    "bytes": 9218,
    "sha256": "b841d3a8833c1cc0f473a404054b324dca9e5f2359104b3a6f89c40182748165"
  },
  "tools/build_ads_assets.py": {
    "bytes": 6496,
    "sha256": "2de692460beb34c467b4568084952bcf1734346e4892a5f1539ca29a92819851"
  },
  "tools/build_blender_assets.py": {
    "bytes": 4739,
    "sha256": "570ce2b564d11c5753c2865096523425f1924d93d82c22d02e86468efe7a62ef"
  },
  "tools/build_directional_assets.py": {
    "bytes": 7623,
    "sha256": "1f7ac3df1542b6e7dd97a64d5237681b9e6e9b8a8e9af17077a0c464556c958d"
  },
  "tools/build_jump_assets.py": {
    "bytes": 7114,
    "sha256": "83859b3b0c0fb433fe8df216d6b843ca18bf50c1c610ac9c8f3c87f6d0193062"
  },
  "tools/build_walk_assets.py": {
    "bytes": 6006,
    "sha256": "f2ec58318ee2458e1c75ccbfa94ec3e8df0127add3d19472d11ee7ddb696ed6d"
  },
  "tools/check_generated_assets.py": {
    "bytes": 1528,
    "sha256": "a19aed6990a04148e0e89339e35952de73331d44fc059d679d091479bd14d3ae"
  },
  "tools/export_ads_fbx.py": {
    "bytes": 10639,
    "sha256": "d1f9d61dd0119bbce2c97eea97265b243b6da6097008943543b5423418ed40dd"
  },
  "tools/export_directional_fbx.py": {
    "bytes": 11053,
    "sha256": "105040590e5fa4d204728c5965b6eced096c9b993f968c643b4e88e02db58ba9"
  },
  "tools/export_jump_fbx.py": {
    "bytes": 10669,
    "sha256": "7dd60ee5323699f2b3c9fabea4be5d21186c67c13dff69e8f4726379dc31095b"
  },
  "tools/export_reload_wip_fbx.py": {
    "bytes": 6198,
    "sha256": "c092993b1c138aac80f8e0c31b8763bcfe8e959bff21c7d022b2338e5dcea86f"
  },
  "tools/export_viewmodel.py": {
    "bytes": 16819,
    "sha256": "dd39c05bbe8c2ac557020261e360da8f7e5debedb652daa75b223de2667f93cd"
  },
  "tools/import_fbx_viewmodel.py": {
    "bytes": 12974,
    "sha256": "b2b449ba916d4d8ffb6bb7c6109fa0714f340300aff8863f9b64d923f6b4f37a"
  },
  "tools/merge_walk_clip.py": {
    "bytes": 3526,
    "sha256": "00965785031c6f87c68cffd5e2082db2cbf3bf51bb5fbb9a1b06c1f867b293a5"
  },
  "tools/package_game.py": {
    "bytes": 47723,
    "sha256": "25f66b9760bbbc19a68c3ac844d75a282bfb85a2652c9b8594d80872ef880563"
  },
  "tools/verify_fbx_segment.py": {
    "bytes": 8418,
    "sha256": "d68a9c6a0ddf6924f1668ecdf23229b7b385077c218b61921b2a762f438dcaf0"
  },
  "tools/verify_jump_seams.py": {
    "bytes": 2698,
    "sha256": "ed44ad5b48d84c5ca9b4bde50152fb3d93c16213fa6c3a7a08082caebf0ad742"
  },
  "tools/verify_locomotion_fbx.py": {
    "bytes": 7062,
    "sha256": "84be01842d2579ce108904380d750a8e2798e29e93bf4114268a176881d96d38"
  },
  "tools/vrpack.py": {
    "bytes": 30543,
    "sha256": "28a23ed9a9b0fe0123405a9800473e57d04419596deae8789c66c744ad05b685"
  },
  "tools/vrskin.py": {
    "bytes": 19574,
    "sha256": "e6aff7f5278bb8e6dd09ca75e69b8761b1b71bd30b3feddf84f8380cd88a5e14"
  },
  "tools/vrview.py": {
    "bytes": 34515,
    "sha256": "eefd755f6ef0943a4d8bf443ddfec601bc1336ec90ece722d017c9c4b6d73568"
  },
  "ui/examples/high-contrast.css": {
    "bytes": 827,
    "sha256": "a525b88b686908a03823be3926f75803c4d7d36cbdf6bce7ab04258a7b51ade0"
  },
  "ui/examples/large-type.css": {
    "bytes": 714,
    "sha256": "5943bd2b52ecb286d88c734e74d76f1c0062f63c00a5344e4c96f229235e30c3"
  },
  "ui/theme.css": {
    "bytes": 646,
    "sha256": "fdb3de1bb63e1b4b535c0195a1d4c62db1e8ae1d51c61f3b67c21c693c5f5902"
  },
  "updater/src/bin/rust-duty-release-sign.rs": {
    "bytes": 3636,
    "sha256": "8b5b0ce480f5ce576bbf45ff608446a9bbd82d61dcf55b9df20be7b913d56802"
  },
  "updater/src/bootstrap.rs": {
    "bytes": 6777,
    "sha256": "c377d00eaed90967895bd1fb232a94ae3971e16424f27be79aaa60872d31e833"
  },
  "updater/src/bundle.rs": {
    "bytes": 8103,
    "sha256": "88421fa84afc4fdec69d5c3cea9b592c3654141c0d00546d2f8c229691c0948f"
  },
  "updater/src/delta.rs": {
    "bytes": 2811,
    "sha256": "479e10d2843d79c8268d66dc1b5d1d06d0ab26231d55629e0ed0e1168a81bbbb"
  },
  "updater/src/download.rs": {
    "bytes": 9588,
    "sha256": "91665ed22778ee173c5d99736b9a0fbcd7dbac16604364de664d0eee5567ad09"
  },
  "updater/src/game.rs": {
    "bytes": 82734,
    "sha256": "4b965e0c4fc273187511aaf60620d3de040103897e5c3ad30078164948b19e97"
  },
  "updater/src/install.rs": {
    "bytes": 18050,
    "sha256": "c7ab7aa5b691928a7e1b76a3e14ed5584808270d5880159180a8e3fcc2714b71"
  },
  "updater/src/launch.rs": {
    "bytes": 5736,
    "sha256": "02a4d32030e53bbbf109c1d67588c3247c3af1a46c3188636dcf1112243ef51b"
  },
  "updater/src/lib.rs": {
    "bytes": 6585,
    "sha256": "db7fd2fb02a7aec796568513323148269b3ad1b8aec4d22a358812947fae0700"
  },
  "updater/src/main.rs": {
    "bytes": 18865,
    "sha256": "d5e01a87b672abade3d3eb0660e0b9592941917d48b1fb13f2c5b79f99535211"
  },
  "updater/src/manifest.rs": {
    "bytes": 3262,
    "sha256": "724626bbc6fa5b25ca97d2f1e9fcacb008e04e1fcbfd763e26127904bbc66291"
  },
  "updater/src/signing.rs": {
    "bytes": 7319,
    "sha256": "2e2fbadb40445032a2488a698f6b7c562e6220837b4db76d6a595eae76b299d8"
  },
  "updater/src/source.rs": {
    "bytes": 4585,
    "sha256": "f9265c579ea60bbc251603103379215410b9d724e3738561f0cb0b4f8dcf16b4"
  },
  "updater/src/tests.rs": {
    "bytes": 70050,
    "sha256": "02b345e3ca0c8fada885ae57bcf6fbcbd7009e6cc9eecd033b6bcab2a65d6ace"
  }
}''')
PRODUCTION_FILES = ('build.rs', 'build_number.rs', 'profiles/kestrel.cfg', 'profiles/m4a1-beta-visual.cfg', 'profiles/m4a1-candidate.cfg', 'settings.cfg', 'src/action.rs', 'src/ammo_supply.rs', 'src/ammo_supply_view.rs', 'src/animation_manifest.rs', 'src/app.rs', 'src/arms.rs', 'src/asset.rs', 'src/asset_path.rs', 'src/authored_ads.rs', 'src/authored_jump.rs', 'src/authored_locomotion_adapter.rs', 'src/authored_locomotion_path.rs', 'src/authored_pose_return.rs', 'src/authored_reload.rs', 'src/authored_viewmodel.rs', 'src/authored_walk.rs', 'src/body_presentation.rs', 'src/capture.rs', 'src/clock.rs', 'src/control.rs', 'src/draw/facade.rs', 'src/draw/frame_witness.rs', 'src/draw/geometry.rs', 'src/draw/mod.rs', 'src/frame_performance.rs', 'src/frame_performance_session.rs', 'src/game_update.rs', 'src/gpu_telemetry.rs', 'src/gpu_telemetry/counters.rs', 'src/gpu_telemetry/tests.rs', 'src/gpu_telemetry/windows.rs', 'src/graphics_device.rs', 'src/hud.rs', 'src/input_frame.rs', 'src/layered_locomotion.rs', 'src/legacy_macroquad/mod.rs', 'src/legacy_macroquad/precision_receipt.rs', 'src/legacy_macroquad/runtime.rs', 'src/lib.rs', 'src/locomotion_presentation.rs', 'src/main.rs', 'src/muzzle_fx.rs', 'src/pause_menu.rs', 'src/platform/audio.rs', 'src/platform/input.rs', 'src/platform/launch.rs', 'src/platform/mod.rs', 'src/platform/runtime.rs', 'src/platform/session_focus.rs', 'src/platform/window.rs', 'src/reference_motion.rs', 'src/render/arena.rs', 'src/render/backend.rs', 'src/render/capture.rs', 'src/render/device.rs', 'src/render/finite_warp_probe.rs', 'src/render/font/LICENSE', 'src/render/font/ProggyClean.ttf', 'src/render/frame.rs', 'src/render/lines.rs', 'src/render/mesh.rs', 'src/render/mesh.wgsl', 'src/render/mod.rs', 'src/render/plan.rs', 'src/render/runtime.rs', 'src/render/sprite2d.rs', 'src/render/target.rs', 'src/render/text.rs', 'src/scene_lighting.rs', 'src/session.rs', 'src/session_focus.rs', 'src/settings.rs', 'src/sim.rs', 'src/sim/actions.rs', 'src/skinned_asset.rs', 'src/sound.rs', 'src/telemetry_export.rs', 'src/traversal_replay.rs', 'src/ui_theme.rs', 'src/view_animation.rs', 'src/viewmodel_animation.rs', 'src/viewmodel_draw.rs', 'src/weapon_animation.rs', 'src/weapon_ik.rs', 'src/weapon_model.rs', 'src/weapon_sway.rs', 'src/world_draw.rs', 'ui/examples/high-contrast.css', 'ui/examples/large-type.css', 'ui/theme.css', 'updater/src/bin/rust-duty-release-sign.rs', 'updater/src/bootstrap.rs', 'updater/src/bundle.rs', 'updater/src/delta.rs', 'updater/src/download.rs', 'updater/src/game.rs', 'updater/src/install.rs', 'updater/src/launch.rs', 'updater/src/lib.rs', 'updater/src/main.rs', 'updater/src/manifest.rs', 'updater/src/signing.rs', 'updater/src/source.rs', 'updater/src/tests.rs')
RESULT_NAMES = ("receipt.json", "ASSET_BUILD_RESULT.json")
COMMAND_TIMEOUT_SECONDS = 5400


class BuildFailure(RuntimeError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def record(path):
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
            size += len(chunk)
    return {"bytes": size, "sha256": h.hexdigest()}


def regular(path):
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"Expected regular file: {path}")


def inside(path, root):
    return path == root or root in path.parents


def input_file(root, relative):
    path = root / relative
    for item in [path, *path.parents]:
        if item == root:
            break
        if item.is_symlink():
            raise BuildFailure(f"Symlink rejected in source input: {relative}")
    regular(path)
    return path


def check_pinned(source):
    if not PINNED_FILES or not PRODUCTION_FILES:
        raise BuildFailure("Embedded immutable input manifest is missing")
    actual = {}
    for name, expected in sorted(PINNED_FILES.items()):
        actual[name] = record(input_file(source, name))
        if actual[name] != expected:
            raise BuildFailure(f"Pinned {SOURCE_COMMIT} input differs: {name}")
    return actual


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", "--source", dest="source", type=Path, required=True)
    parser.add_argument("--output-root", "--output", dest="output", type=Path, required=True)
    parser.add_argument("--blender", type=Path, required=True)
    parser.add_argument("--sampler", type=Path, required=True)
    parser.add_argument("--jump-source-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="Verify preflight and print plan without producers or writes")
    return parser.parse_args(argv)


def preflight(args):
    for field in ("source", "output", "blender", "sampler", "jump_source_dir"):
        path = getattr(args, field)
        if not path.is_absolute():
            raise BuildFailure(f"--{field.replace('_', '-')} must be absolute")
        if path.is_symlink():
            raise BuildFailure(f"Direct symlink path rejected: {path}")
        setattr(args, field, path.resolve())
    if not args.source.is_dir() or not args.jump_source_dir.is_dir():
        raise BuildFailure("Source root and historical jump source directory must exist")
    if args.output.exists():
        raise BuildFailure("Output directory must be fresh")
    if any(inside(args.output, root) or inside(root, args.output)
           for root in (args.source, args.jump_source_dir)):
        raise BuildFailure("Output must be outside and disjoint from source and jump inputs")
    immutable = check_pinned(args.source)
    jump = input_file(args.jump_source_dir, "halcyon_jump.blend")
    if record(jump) != JUMP_RECORD:
        raise BuildFailure("Historical jump r7 bytes differ from its immutable contract")
    for name in ("blender", "sampler"):
        path = getattr(args, name)
        regular(path)
        if not os.access(path, os.X_OK):
            raise BuildFailure(f"{name} is not executable: {path}")
    with args.sampler.open("rb") as stream:
        header = stream.read(20)
    if len(header) < 20 or header[:4] != b"\x7fELF" or header[4:6] != b"\x02\x01" or header[18:20] != b"\x3e\x00":
        raise BuildFailure("Sampler must be the supplied x86-64 Linux ELF executable")
    version_started = time.monotonic()
    version = subprocess.run([str(args.blender), "--version"], capture_output=True,
                             text=True, timeout=30, check=False)
    if version.returncode or not re.search(r"^Blender 4\.3\.2(?:\s|$)", version.stdout, re.MULTILINE):
        raise BuildFailure("Producer requires exact Blender 4.3.2; version preflight failed")
    return {"source_commit": SOURCE_COMMIT, "immutable_inputs": immutable,
            "jump": {"commit": JUMP_COMMIT, "file": str(jump), **record(jump)},
            "blender": {"path": str(args.blender), **record(args.blender), "version_output": version.stdout.strip(),
                        "version_command": {"argv": [str(args.blender), "--version"], "exit_code": version.returncode,
                                            "elapsed_seconds": round(time.monotonic() - version_started, 6),
                                            "stderr": version.stderr}},
            "sampler": {"path": str(args.sampler), **record(args.sampler)},
            "python": {"executable": sys.executable, "version": sys.version}}


def build_plan(args):
    src, out = args.source, args.output
    plan = []
    def command(name, script, *flags, group=None, validation=False):
        plan.append({"name": name, "kind": "command", "group": group,
                     "validation": validation,
                     "argv": [sys.executable, "-B", str(src / "tools" / script), *map(str, flags)]})
    def validate(group, directory):
        command(f"validate-{group}", "check_generated_assets.py", "--kind", group,
                "--directory", directory, "--root", src, group=group, validation=True)
    def stage(group, directory):
        plan.append({"name": f"stage-{group}", "kind": "stage", "group": group,
                     "from": str(directory), "to": str(src / "assets" / group)})
    command("materialize-locomotion", "package_game.py", "materialize", "--root", src)
    reload_root = out / "reload-build"
    command("build-reload", "build_blender_assets.py", "--blender", args.blender,
            "--root", src, "--output", reload_root, group="reload")
    command("parity-reload", "build_blender_assets.py", "--verify-sampler", args.sampler,
            "--root", src, "--output", reload_root, group="reload")
    validate("reload", reload_root / "reload")
    for group in ("walk", "ads", "directional", "jump"):
        runtime = out / f"{group}-runtime"
        flags = ["--root", src, "--blender", args.blender, "--sampler", args.sampler,
                 "--work", out / f"{group}-work", "--output", runtime]
        if group == "jump":
            flags += ["--source-dir", args.jump_source_dir]
        command(f"build-{group}", f"build_{group}_assets.py", *flags, group=group)
        validate(group, runtime)
        if group == "walk":
            # Every downstream producer must consume this same freshly validated walk44.
            stage(group, runtime)
    stage("reload", reload_root / "reload")
    for group in ("ads", "directional", "jump"):
        stage(group, out / f"{group}-runtime")
    command("validate-complete-staged-assets", "package_game.py", "materialize", "--root", src,
            "--include-walk", "--include-ads", "--include-directional", "--include-jump", "--require-generated",
            validation=True)
    return plan


def files_record(directory):
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise BuildFailure(f"Symlink rejected in output: {path}")
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = record(path)
    return result


def stage_data(origin, destination):
    if not origin.is_dir() or origin.is_symlink():
        raise BuildFailure(f"Missing regular runtime output directory: {origin}")
    records = files_record(origin)
    if not records:
        raise BuildFailure("Empty runtime output")
    allowed = {".vra", ".vrm", ".vrs", ".gz", ".json"}
    for name in records:
        if Path(name).suffix not in allowed and name != "README.md":
            raise BuildFailure(f"Unexpected producer output: {name}")
        target = destination / name
        for ancestor in [target, *target.parents]:
            if ancestor.is_symlink():
                raise BuildFailure(f"Symlink rejected in staging destination: {ancestor}")
            if ancestor == destination:
                break
        if target.exists() and not target.is_file():
            raise BuildFailure(f"Non-file staging destination: {target}")
    destination.mkdir(parents=True, exist_ok=True)
    for name, expected in records.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin / name, target)
        if record(target) != expected:
            raise BuildFailure(f"Staged bytes differ: {target}")
    return records


def save_result(output, result):
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    for name in RESULT_NAMES:
        temporary = output / (name + ".tmp")
        temporary.write_text(text)
        temporary.replace(output / name)


def run_logged_command(argv, cwd, stream, environment):
    """Bound one producer and own cleanup of all its child processes."""
    process = subprocess.Popen(argv, cwd=cwd, env=environment, stdout=stream,
                               stderr=subprocess.STDOUT, start_new_session=True)
    try:
        return process.wait(timeout=COMMAND_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise BuildFailure(f"Producer exceeded {COMMAND_TIMEOUT_SECONDS}s") from exc
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=10)


def run_build(args, inputs, plan):
    args.output.mkdir(parents=True, exist_ok=False)
    result = {"schema": "rust-duty-public-authored-build/v1", "status": "running",
              "started_at": now(), "source_root": str(args.source), "inputs": inputs,
              "commands": [], "groups": {}, "production_files_preserved": None,
              "limits": ["Fresh derived assets; not the frozen package identity", "CPU numerical parity only; no artistic or native-renderer approval"]}
    save_result(args.output, result)
    current = None
    try:
        for index, step in enumerate(plan, 1):
            current = {**step, "started_at": now(), "status": "running"}
            started = time.monotonic()
            result["commands"].append(current)
            save_result(args.output, result)
            print(f"ASSET_STEP {index}/{len(plan)} {step['name']}", flush=True)
            try:
                if step["kind"] == "command":
                    log = args.output / f"{index:02d}-{step['name']}.log"
                    current["log"] = str(log)
                    environment = dict(os.environ)
                    environment["PYTHONDONTWRITEBYTECODE"] = "1"
                    environment["PYTHONUNBUFFERED"] = "1"
                    with log.open("xb") as stream:
                        code = run_logged_command(step["argv"], args.source, stream, environment)
                    current["exit_code"] = code
                    current["log_record"] = record(log)
                    if code:
                        raise BuildFailure(f"{step['name']} failed with exit code {code}; see {log}")
                else:
                    current["staged_files"] = stage_data(Path(step["from"]), Path(step["to"]))
                current["status"] = "passed"
                if step.get("validation") and step.get("group"):
                    result["groups"].setdefault(step["group"], {})["validation"] = "passed"
                if step["kind"] == "stage":
                    result["groups"].setdefault(step["group"], {})["files"] = current["staged_files"]
            except BaseException:
                current["status"] = "failed"
                if step.get("group"):
                    result["groups"].setdefault(step["group"], {})["failed_step"] = step["name"]
                raise
            finally:
                current["elapsed_seconds"] = round(time.monotonic() - started, 6)
                current["completed_at"] = now()
                if "log" in current and Path(current["log"]).is_file():
                    current["log_record"] = record(Path(current["log"]))
                save_result(args.output, result)
                print(f"ASSET_STEP_RESULT {step['name']} {current['status']} {current['elapsed_seconds']}s", flush=True)
        result["immutable_inputs_after"] = check_pinned(args.source)
        result["production_files_preserved"] = all(
            result["immutable_inputs_after"][name] == inputs["immutable_inputs"][name]
            for name in PRODUCTION_FILES)
        result["staged_assets"] = {name: files_record(args.source / "assets" / name)
                                   for name in ("locomotion", "walk", "reload", "ads", "directional", "jump")}
        result["status"] = "passed"
    except BaseException as exc:
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
        try:
            result["immutable_inputs_after"] = check_pinned(args.source)
            result["production_files_preserved"] = True
        except Exception as integrity_error:
            result["production_files_preserved"] = False
            result["integrity_error"] = str(integrity_error)
        raise
    finally:
        result["completed_at"] = now()
        save_result(args.output, result)
    return result


def main(argv=None):
    args = parse_args(argv)
    admitted = False
    try:
        inputs = preflight(args)
        admitted = True
        plan = build_plan(args)
        if args.dry_run:
            print(json.dumps({"status": "preflight_passed", "source_commit": SOURCE_COMMIT,
                              "inputs": inputs, "plan": plan}, indent=2))
            return 0
        result = run_build(args, inputs, plan)
        print(json.dumps({"status": result["status"], "receipt": str(args.output / "receipt.json")}))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        # Preserve a machine-readable rejection only at a safe, fresh output path.
        # --dry-run always stays read-only, including failures.
        if not admitted and not args.dry_run and args.output.is_absolute() and not args.output.exists():
            output = args.output.resolve()
            roots = (args.source.resolve(), args.jump_source_dir.resolve())
            if not any(inside(output, root) or inside(root, output) for root in roots):
                output.mkdir(parents=True, exist_ok=False)
                save_result(output, {"schema": "rust-duty-public-authored-build/v1",
                                     "status": "failed", "phase": "preflight", "completed_at": now(),
                                     "error": f"{type(exc).__name__}: {exc}", "commands": [], "groups": {},
                                     "production_files_preserved": None})
        print(f"ASSET_BUILD_FAILED {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    def cancelled(signum, frame):
        raise BuildFailure(f"Received termination signal {signum}")
    signal.signal(signal.SIGTERM, cancelled)
    raise SystemExit(main())
