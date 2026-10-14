# Common Jump: approved r8 landing

Stable takeoff and air bindings retain Halcyon's r7 Actions. Landing uses the
exact two-key `jump_land_r8_ease_candidate` correction under the existing runtime
ID `jump_land`. Native 60 Hz timing and the 29-frame landing are unchanged.
Actual gameplay ground contact starts landing; extended flight holds the
non-looping air endpoint. ADS/reload/mantle retain gameplay ownership.

CI reads the existing pinned r7 BLEND, SHA256
`a2c4b2bbe98da1a608450bba92404cb39008eae5861bcf8fc3f5d2f978df0e3b`,
and reconstructs the reviewed Action in memory. Its complete curve digest must
match the approved candidate's recorded digest before export. Source bytes and
all 103 existing Actions remain unchanged; no new authoring asset is bundled.

[Elara's final review](https://github.com/RHS059/rust_duty/pull/20#pullrequestreview-5511992220)
recommends 82/pass with no measured blocking defects. The user authorized game
integration on that verdict. See `docs/JUMP_R8_APPROVED_INTEGRATION.md` for exact
identities, the reviewer’s inspection limits and verification.
