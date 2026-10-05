# Windows-only release control

The live plan is unchanged by this change. Promote only after an exact-source
Windows build, Windows launcher and real-byte preflight pass. Select successful
Windows jobs by commit, repository and push provenance; Linux-hosted native
validation remains visible but is not a Windows-distribution gate.

The delta producer emits smaller full-bundle and executable-baseline patches,
with verified full fallback. Immutable historical assets and reserved0.1.10 are
untouched. Candidate0.1.11 uses public0.1.9 as its retained baseline.

Production trust stays fixed to GitHub/latest. After promotion, native Windows
smoke verifies launcher migration plus actual game-entry replacement/relaunch
from both the full installed baseline and one-file executable baseline. These
production checks are distinct from prepromotion loopback fixture verification.
