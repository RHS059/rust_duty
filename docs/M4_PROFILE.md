# M4A1-inspired candidate profile

This is a provisional, independently implemented game-behavior preset for a
**2009 multiplayer M4A1 without perks or attachments**. It is not a retail-game
measurement, verified recreation, or claim of indistinguishable feel. The exact
platform, build, and collection method behind the published table are unresolved.

The profile selects gameplay settings only. An HK416A5 visual model, if selected,
is a separate presentation choice and does not identify this as an HK416 behavior
simulation or change the weapon's movement/cadence. No original game code, assets,
recordings, or legacy recoil coefficients are imported by this profile.

## Selection and integration

- `Settings::default()` and `profiles/kestrel.cfg` remain the original authored Kestrel-30
  preset, preserving its 90 ms cadence and existing regression contract
- `Settings::m4_candidate()` constructs the candidate without filesystem access
- `profiles/m4a1-candidate.cfg` is a complete editable copy of the candidate;
  the frontend's default `settings.cfg` initially contains this same profile
- `Settings::load(path)` still loads a file over the Kestrel default
- `Settings::load_with_base(path, Settings::m4_candidate())` applies partial
  overrides while retaining unspecified candidate values
- Missing files and unknown/non-finite values retain the selected base. Finite
  settings are range-clamped; ammunition-credit times cannot exceed readiness

The frontend defaults to the candidate. Run `cargo run --release -- --profile=m4a1`
to select it explicitly, or `cargo run --release -- --profile=kestrel` for the
legacy profile. Add `--settings=path/to/overrides.cfg` for a partial override file.
Without that option, M4 uses `settings.cfg` and Kestrel uses `profiles/kestrel.cfg`.
F5 saves and F6 reloads the active path. Reloading uses the selected preset as the
base again, so removing a line restores that preset's value. Saved settings
include `ads_move_multiplier`. Gameplay selection is independent of visual-model
selection.

## Implemented values and provenance

Marvel4's public M4A1 row lists a 0.070 s interval, 30-round magazine, 0.250 s ADS,
0.300 s sprint-out, 2.029/2.359 s nonempty/empty reload, 1.100 s reload-add, and
0.95/0.38 normal/aimed movement. These are **published candidate inputs**, not
measurements made here. [Public table, M4A1 row 7](https://docs.google.com/spreadsheets/d/1ydB2DmPSrkR-h-QyECrCbD28zWsHr842EQkNtJ6wITw/edit)

| Setting | Candidate | Classification / implementation choice |
| --- | ---: | --- |
| Fire interval | 70 ms | Published candidate; stored as `60 / 0.070` RPM |
| Magazine | 30 | Published candidate; existing shared magazine size |
| ADS in | 250 ms | Published candidate |
| ADS out | 250 ms | Proposed symmetric transition; no separate exit trace |
| Sprint-out | 300 ms | Published candidate |
| Tactical reload credit | 1.100 s | Candidate interpretation of the single add entry |
| Tactical readiness | 2.029 s | Published completion used as the uninterrupted fire gate |
| Empty readiness | 2.359 s | Published completion used as the uninterrupted fire gate |
| Empty reload credit | 1.800 s | **Authored fallback**, not inferred from the single add entry |
| Walk | 4.584700 m/s | Derived from authored 4.826 m/s base × 0.95 |
| Sprint | 6.877050 m/s | Derived; retained authored 1.5 × walk ratio |
| Crouch | 2.980055 m/s | Derived; retained authored 0.65 × walk ratio |
| Full ADS movement | 0.40 × normal stance speed | Derived interpretation: 0.38 / 0.95 |
| Hip / ADS horizontal FOV | 90° / 65° | Retained authored values, not a table conversion |
| Spread and recoil | Kestrel authored defaults | Temporary design choices, described below |

Denkirson distinguishes reload completion from the earlier ammunition-counter
update and describes weapon-class movement penalties. Those definitions are a
reason to keep distinct milestones; they do not establish the prototype's cancel
rules or an exact empty-credit event. [Original analysis](https://denkirson.wordpress.com/2010/02/04/modern-warfare-2/)

## Scheduling and controls

The 120 Hz simulation retains fractional absolute shot deadlines. It does not
round 70 ms to a fresh nine-tick (75 ms) delay after every shot. For a trigger held
from time zero, a 30-round magazine has **29 intervals**, ending at a scheduled
2.030 s; delivery occurs on the first eligible simulation tick. The accepted
first-to-last duration may differ by less than one step (8.333 ms), without
accumulating drift. An unlimited-supply diagnostic expects 143 shots in [0, 10 s),
with the last deadline at 9.940 s.

Input release is sampled before a shot due on that update. A later fresh press
starts a new sequence without replaying missed shots, while the previous cooldown
still limits rapid taps. Render rates share the same fixed-step clock and do not
change cadence or random hit sampling.

ADS reverses continuously from its current progress. Symmetric ADS exit,
linear partial-ADS movement/spread, and concurrent sprint-out/ADS timing remain
prototype choices. The sprint-to-fire gate is 300 ms; this is not a claim that
sprint-to-ADS always takes 300 + 250 ms.

## Movement interpretation

The 0.95 normal and 0.38 aimed entries are interpreted relative to the same base.
Consequently, aimed movement uses 40% of already weapon-adjusted movement, not
38% of that reduced speed. The simulation contains only one such weapon penalty:
configured walk/sprint/crouch values include 0.95, while the ADS blend uses 0.40.
At settled forward speed this produces 4.584700 m/s normal and 1.833880 m/s aimed.

The 190-reference-unit/s baseline and 0.0254 m/unit conversion are authored
prototype conventions. They are not new physical measurements of a retail game.
Existing directional penalties, stance ratios, acceleration/friction, prone speed,
air steering, sprint duration/recovery, collision and jump rules remain unchanged.

## Explicit unresolved behavior

- **Spread stays authored.** Standing/crouched/prone hip minima remain
  1.60°/1.15°/0.80° and settled full-ADS residual spread remains 0.08°. This does
  not implement the published stance envelopes or zero-ADS-spread entry. Existing
  movement/air additions, bloom, recovery and partial-aim blend are also authored
- **Recoil stays authored.** Impulse, jitter, clamps and return use the existing
  independent tuning. The table's viewkick/centerspeed fields are not treated as
  literal degrees or a recovered integration model. Raw look, aim recoil and
  visual weapon animation remain separate channels
- **Empty credit is unknown.** 1.800 s is the existing authored fallback and stays
  independently configurable; it is not a confirmed original-game event
- Tactical sprint cancellation keeps old ammo before credit and credited ammo
  afterward. Credit occurs once; a due milestone wins over simultaneous cancel
  input. Empty reload remains uninterruptible. These are correctness-oriented
  prototype rules, not verified retail cancellation or re-raise behavior
- Initial reserve, target damage, hit feedback, ADS FOV, accuracy dynamics and
  perk/attachment effects are not reconstructed by this preset

The public table reports stance ranges and zero ADS spread, but does not establish
all the accuracy-state dynamics needed to replace the current system safely.
[Published spread fields](https://docs.google.com/spreadsheets/d/1ydB2DmPSrkR-h-QyECrCbD28zWsHr842EQkNtJ6wITw/edit)

For a distinct historical-cadence comparison, use a partial override containing
`fire_rpm = 800`. This produces 75 ms and a scheduled 2.175 s full-magazine span.
An original-era guide records 800 RPM and attributes the figures to Denkirson;
it does not resolve the discrepancy. Do not average these two rates or assume a
cause such as platform/tick rounding without measurement.
[Historical alternative and attribution](https://gamefaqs.gamespot.com/pc/951942-call-of-duty-modern-warfare-2/faqs/58754)

## Automated checks

Executed on Linux on 2026-09-30: all 18 profile tests passed in debug and release
builds. The complete current test suite (117 tests), formatting check and
warnings-as-errors Clippy check also passed. These are prototype checks, with no
retail game involved.

Run `cargo test --locked --test m4_profile`. The suite checks:

- Candidate isolation, the shipped config, partial/missing-file fallback, finite
  parsing, movement-factor clamps and settings serialization
- All 30 magazine deadlines, fractional phase, trigger release/repress and rapid
  taps, and a separate 800 RPM comparison
- 143 unlimited-supply shots over ten seconds at 30/60/120/144/240 rendered FPS,
  identical accepted times/directions, and bounded sub-tick deadline lateness
- Real magazine/reload/ammunition invariance at the same render rates
- ADS entry/exit/reversal, 300 ms sprint-out, both reload-ready gates, tactical
  credit at 1.100 s and the explicit empty-credit fallback at 1.800 s
- Tactical cancel one tick before/at/after credit with no stale transfer, and the
  authored uninterruptible-empty rule at its corresponding boundary
- Settled walk/sprint/crouch speeds and the 0.40 ADS/normal movement ratio

These checks establish the declared candidate implementation. Retail capture,
matched platform/build/loadout testing, recoil/spread reconstruction and blinded
feel comparisons remain necessary before making equivalence claims.
