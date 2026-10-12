# DX12 hardware playtest checklist (isolated preview)

Human checklist for the M4 hardware DX12 playtest of the isolated WIP preview.
Every box starts unchecked. Mark exactly one of Pass / Fail / Untested for each
item and attach evidence. An item without evidence counts as Untested.

Completing this checklist is not approval. It sets no time budget, pixel score
or performance threshold. It does not test or authorize a network update,
release, release-channel change or artistic sign-off. Human approval is the
separate section at the end and stays open until the owner fills it in.

## Launcher

Use only the preview's strict hardware-DX12 launcher, `PLAYTEST_DX12.cmd`, from
the extracted `Rust-Duty-<label>-DX12-Preview-Windows-x64` artifact. As staged
by `tools/stage_dx12_preview.py`, its full content is:

```bat
@echo off
cd /d "%~dp0"
"%~dp0vector-range.exe" --renderer=dx12 --no-update
exit /b %ERRORLEVEL%
```

Explicit `--renderer=dx12` never silently changes API. There is no
`--force-fallback-adapter`, so WARP is not forced. `--no-update` disables the
release channel for this launch.

Source status: neither `PLAYTEST_DX12.cmd` nor `tools/stage_dx12_preview.py` is
in commit `72663e2` (PR 44 head when this checklist was written). Both come from
the pending preview-packaging change (mailbox message
`halcyon-dx12-preview-package-20261005-261`). If the extracted launcher is
missing or differs from the text above, stop and record the run as blocked. Do
not substitute `run.bat` (it uses Cargo with the default legacy renderer),
double-clicking `vector-range.exe` (legacy default until M4), or any
`--force-fallback-adapter` command.

To keep the backend log, start it from a Command Prompt in the extracted
folder. This only redirects output and leaves the launcher unchanged:

```bat
PLAYTEST_DX12.cmd 2> dx12-playtest-stderr.txt
```

## Build identity

| Field | Value |
| --- | --- |
| Preview artifact name | |
| Artifact ZIP SHA-256 | |
| Source commit (`DX12_PREVIEW.json` / `BUILD_IDENTITY.json`) | |
| CI run ID / attempt | |
| `vector-range.exe --build-label` | |
| `vector-range.exe --build-number` | |
| `vector-range.exe --build-version` | |
| `vector-range.exe` SHA-256 (`certutil -hashfile vector-range.exe SHA256`) | |
| Executable SHA-256 recorded in `DX12_PREVIEW.json` (must match) | |
| `PLAYTEST_DX12.cmd` SHA-256 | |
| `ui/theme.css` SHA-256 before any F7 edit | |
| Machine name | |
| OS edition and build (`winver`) | |
| CPU / RAM | |
| GPU model | |
| GPU driver version and date | |
| Display resolution and refresh rate | |
| Windows display scale (100/125/150/175/200%) | |
| Monitor count and per-monitor scale | |
| Audio output device | |
| Tester / date / time zone | |

## 1. Strict hardware DX12 identity

- [ ] Pass  [ ] Fail  [ ] Untested: stderr contains
  `renderer requested=dx12 backend=Dx12 adapter=<GPU>` naming the real GPU.
  Evidence (exact line):
- [ ] Pass  [ ] Fail  [ ] Untested: stderr contains
  `renderer dx12_shader_compiler=Fxc`. Evidence:
- [ ] Pass  [ ] Fail  [ ] Untested: adapter is not
  `Microsoft Basic Render Driver`. If it is, this was a WARP run: record it and
  stop. It is not a hardware result. Evidence:
- [ ] Pass  [ ] Fail  [ ] Untested: the window title shows the same build label
  as `--build-label`. Evidence (screenshot):

## 2. Focus loss and resume

- [ ] Pass  [ ] Fail  [ ] Untested: Alt+Tab away while holding W and firing.
  The game pauses, releases the cursor and shows the mouse. Evidence:
- [ ] Pass  [ ] Fail  [ ] Untested: on return it stays paused until a fresh
  resume. No key or button held across the switch moves, fires or reloads until
  released and pressed again. Resume clicks never fire. Evidence:
- [ ] Pass  [ ] Fail  [ ] Untested: minimize and restore. No crash, no stretched
  or stale frame, input still works. Evidence:
- [ ] Pass  [ ] Fail  [ ] Untested: F7 pressed on the frame focus returns does not
  reload the theme. Evidence:

## 3. Resize and F11

- [ ] Pass  [ ] Fail  [ ] Untested: drag-resize the window from small to large and
  maximize/restore. HUD and menu stay anchored with no stretching, black bands
  or clipping. Evidence:
- [ ] Pass  [ ] Fail  [ ] Untested: F11 enters borderless fullscreen on the current
  monitor, and F11 again restores the window. Mouse look and pause still work in
  both states. Evidence:
- [ ] Pass  [ ] Fail  [ ] Untested: change the Windows display scale while the game
  runs (for example 100% → 125% → 150% → 175%). UI rescales with no crash and stays
  crisp. Scales tried:  Evidence:
- [ ] Pass  [ ] Fail  [ ] Untested: move the window between monitors with different
  scales. Mark Untested if only one monitor is available. Evidence:

## 4. Mouse, menu and slider alignment

Repeat at every Windows display scale available. Scales covered:

- [ ] Pass  [ ] Fail  [ ] Untested: Escape opens the pause menu. Clicks just inside
  each edge of Resume, Save, Reset and position Reset activate that control.
  Clicks just outside do nothing. Evidence:
- [ ] Pass  [ ] Fail  [ ] Untested: each walking X/Y/Z and viewmodel slider follows
  the pointer from track start to track end. The value at the drawn endpoints
  matches the limits. Evidence:
- [ ] Pass  [ ] Fail  [ ] Untested: a drag that leaves the slider keeps ownership
  until release. Release saves once and does not resume. Evidence:
- [ ] Pass  [ ] Fail  [ ] Untested: keyboard menu navigation adjusts only the selected
  axis. Evidence:
- [ ] Pass  [ ] Fail  [ ] Untested: in-game mouse look sensitivity feels the same at
  100% and fractional scales. Evidence:

## 5. F7 theme reload (valid and invalid, last-good)

Edit the `ui/theme.css` next to `vector-range.exe`. Restore the original file
afterwards and confirm its hash matches the identity table.

- [ ] Pass  [ ] Fail  [ ] Untested: a valid edit (for example
  `#pause-menu .button { background-color: #123456; }`) followed by F7 shows
  `UI theme reloaded` and the change is visible. Evidence:
- [ ] Pass  [ ] Fail  [ ] Untested: an invalid edit (for example adding the rule
  `.label:hover {}`, or `opacity: 2;` inside an existing rule) followed by F7
  shows `UI theme retained:` with file:line:column. The previous look is
  unchanged. Evidence:
- [ ] Pass  [ ] Fail  [ ] Untested: fixing the file and pressing F7 again applies it.
  No stale property from the failed attempt remains. Evidence:
- [ ] Pass  [ ] Fail  [ ] Untested: clickable bounds still match the painted buttons
  and sliders after a reload with larger fonts and borders. Evidence:

## 6. Audio

- [ ] Pass  [ ] Fail  [ ] Untested: weapon and gameplay sounds play on the named
  output device without crackle or delay. Evidence:
- [ ] Pass  [ ] Fail  [ ] Untested: M mutes and unmutes. Evidence:
- [ ] Pass  [ ] Fail  [ ] Untested: sound still plays after focus loss/resume,
  minimize/restore and F11. Evidence:

## 7. Performance observations on a named machine

These are observations only and set no threshold.

| Scene / location | Resolution / scale / window mode | F1 `RENDER … fps` range | Hitches or stutter seen | Notes |
| --- | --- | --- | --- | --- |
| | | | | |

- [ ] Recorded  [ ] Untested: observations above, with the machine named in the
  identity table.
- [ ] Recorded  [ ] Untested: optional legacy comparison on the same scene. Launch
  `vector-range.exe --renderer=gl --no-update` and record it in a separate row.

## Explicitly untested here

Each stays unchecked unless separately exercised and evidenced:

- [ ] Native OS DPI events and per-monitor DPI beyond the items above. The CPU
  tests in `tests/ui_scale_contract.rs` drive the recorder directly and cannot
  certify them.
- [ ] Release-channel or network update behavior (disabled by `--no-update`).
- [ ] WARP/software-adapter runs (CI smoke only, not a hardware result).
- [ ] Vulkan, Metal or other backends.
- [ ] HDR, variable refresh rate, multi-GPU adapter selection.
- [ ] Authored-capture visual parity, ADS landmarks, artistic review.
- [ ] Long-session stability beyond this playtest's duration.

## Human approval (separate; left open)

Checklist results above are evidence for review, not approval.

- Reviewer:
- Date:
- Build identity reviewed (source commit and executable SHA-256):
- [ ] Approved as M4 hardware DX12 playtest evidence for this exact build
- [ ] Not approved. Reasons:

This approval covers this build's hardware DX12 playtest only. It does not
approve cutover, a release, an update, performance targets or artwork.
