# Full movement reference

This folder stores every byte of the recovered **Modern Warfare 2022 Movement Reference** MP4 on GitHub, in seven exact binary parts. No transcoding or trimming was performed.

The complete file is 50,406,346 bytes, SHA-256 `491a1729aa0f32373025d35fff86da76c6c1c8f057c0c553d0fbb5fb6226ff46`.

## Restore the stable MP4 filename

After checking out this branch, run from the repository root with Python 3.9 or later:

```sh
python references/movement/restore_movement_reference.py
```

The script verifies each part and creates:

`references/movement/modern_warfare_2022_movement_reference.mp4`

It uses only the Python standard library, performs no network access, and rejects mismatched bytes or an existing different output. Repeating it with a matching output verifies the existing file. Use `--output /path/to/modern_warfare_2022_movement_reference.mp4` to choose another destination.

The manifest records exact part ordering, sizes, and SHA-256 hashes. The parts are ordinary Git files, not Git LFS pointers. A clone containing this folder is sufficient; the original Drive or YouTube service is not needed to reconstruct the full source.

## Why the file is stored in parts

The available authenticated repository transport accepts inline blobs whose request size is limited. The full MP4 exceeds that transport's request capacity even though it is below GitHub's normal 100 MiB Git file limit. Parts preserve the original bytes without changing credentials or repository security settings. This storage format does **not** provide a single direct-playback raw MP4 URL. An authenticated Git executor may later commit the reconstructed MP4 under the stable filename after verifying its hash.

## Provenance and identity limits

- Recovered file: `Modern_Warfare_2022_Movement_Reference.mp4`
- User-supplied [Drive source](https://drive.google.com/file/d/1hxAU4KKtB8hP0Ch1o-rOWgOV93ye-Y7i/view), file ID `1hxAU4KKtB8hP0Ch1o-rOWgOV93ye-Y7i`
- Clarified [YouTube reference](https://www.youtube.com/watch?v=V_QT_cnlBHU): **Modern Warfare 2022 Movement Reference**, Hexagon, displayed duration 2:32
- Decoded source: 1280 × 720, 60 fps, 9,137 frames, 152.283333 seconds
- Matching title, runtime and complete chapter timeline establish strong footage correspondence. Independent YouTube encoded-byte or live-pixel equivalence was not established
- Jumping chapter starts at 65 seconds. The first confirmed stationary jump begins at zero-based native frame 4034 (67.233333 seconds); estimated impact is frame 4067, with ±1-frame observational uncertainty

The manifest preserves all chapter boundaries and exact source identity. Image-space phase estimates are observations, not engine-event telemetry.
