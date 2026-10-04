# Full movement reference originals

These are the complete existing R1 and R2 MP4 files, stored as ordered exact binary parts using the established movement-reference format. No reconversion, trimming, annotation, or animation change accompanies this handoff.

## Restore stable MP4 filenames

From a checkout containing this directory, with Python 3.9 or later:

```sh
python references/movement/source_originals/restore_movement_reference.py --manifest references/movement/source_originals/9RRgXvRx43s.manifest.json
python references/movement/source_originals/restore_movement_reference.py --manifest references/movement/source_originals/5KM0XSKxTWw.manifest.json
```

Outputs are `9RRgXvRx43s.mp4` and `5KM0XSKxTWw.mp4` beside the manifests. Each part and each full output is SHA-256 verified. Existing matching output is verified without rewriting; an existing different output is rejected. The helper uses only the Python standard library, makes no network requests, and is copied unchanged from the prior verified R3 transfer. Always supply the appropriate `--manifest`; its historical default names the separate R3 reference.

- R1: **47,049,387 bytes**, SHA-256 `5b883e85d1179d06987509e4ede2b18fbc54433c4578b316af355e68d17becf5`, 1280 × 720 at 60 fps, 6,822 frames, 113.7 seconds. [Original source](https://www.youtube.com/watch?v=9RRgXvRx43s)
- R2: **52,915,134 bytes**, SHA-256 `cff413d8d114b611bbe6f50cc553ef109d61eb8eb1fff960425f506b84d6767e`, 1280 × 720 at 60 fps, 7,976 frames, 132.933333 seconds. [Original source](https://www.youtube.com/watch?v=5KM0XSKxTWw)

The MP4 bytes are stored in ordinary Git binary parts, not Git LFS pointers. Each part is at most 8 MiB. The available repository transport cannot upload either complete MP4 in one request; reconstruction preserves every original byte. This format does not provide a single direct-playback MP4 URL.

## Scope

This isolated handoff adds only `references/movement/source_originals/`. It leaves the separate `references/movement/remaining_20261004/` source-validation lane, existing source files, runtime, build configuration, and animation assets untouched. It makes no new motion-coverage or artistic-acceptance claim. Reference footage is not a game-runtime asset.

## Restore checks

```sh
python -m unittest discover -s references/movement/source_originals -p 'test_restore_movement_reference.py' -v
```

The companion tests cover exact reconstruction and repeat verification, corrupt part rejection, wrong full hash rejection, refusal to overwrite a different output, and path escape rejection.
