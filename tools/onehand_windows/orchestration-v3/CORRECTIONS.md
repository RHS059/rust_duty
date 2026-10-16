# Narrow executable-selection correction

Predecessor v2 PINS: 0f8d652b595d30525933ca378eb45850d84aa2512726e9018a2c3a85a2105d58.
Failed source CI: https://github.com/RHS059/rust_duty/actions/runs/38900572341/job/116971516110 .

The exact Git/rustup/link/cl/lib discovery sites are corrected using one identical resolver body. Get-Command is constrained to Application, returns -All in execution-precedence order, and is reduced with Select-Object -First 1 before accessing Source. Scalar string and literal leaf checks precede return; the path is never joined, cast from an array, split on spaces, or used as a shell command string.

All source admission, commit-object, source reconstruction, process ownership, native math, bounds and proof checks remain unchanged. No native admission record is completed. Historical v1/v2 defects and runs are not relabeled as successful.

The only other executable-source change is the immutable package destination/source bootstrap path from orchestration-v2 to orchestration-v3 and its corresponding reviewed bootstrap digest. New tests and package metadata bind this successor. No broad toolchain rewrite or input-completion work is mixed into this correction.
