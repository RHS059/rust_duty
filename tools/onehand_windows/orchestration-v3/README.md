# Windows workflow v3: scalar application selection

This immutable source-only successor corrects the first real Windows execution blocker from frozen v2. Run 38900572341 at commit c61dbd67039a4961d0c56f0a3c7e478c431d1ced failed before source tests because Git discovery returned three Application paths and PowerShell coerced them into one invalid executable. The failed run and all v2 source/review files remain preserved.

The workflow and Rust installer now use the same Resolve-Application function. It selects the first Application in Get-Command -All execution-precedence order, requires the uncast Source to be one nonempty string, verifies an existing literal leaf, and returns that exact path. Git, rustup, link, cl and lib use it. Paths containing spaces remain a single argument. Explicit vswhere/ComSpec paths are unaffected. No signer, installation or trust-policy changes are included.

The source bootstrap/package path moves to orchestration-v3, and its exact helper hash is refreshed. The byte materializer, all numerical/native/process/runtime code, original resource bounds and reviewed-dependencies declaration remain byte-identical to v2. The null proof-admission alias is unchanged. All five native steps still require independently accepted complete input admission; source tests cannot authorize them.

Regression coverage checks the identical resolver bodies and all five call sites. On Windows it uses three PATH entries containing spaces with copies of the installed command shell, ignores an alias, checks first-match and reversed-PATH behavior, and actually invokes the selected scalar path through both the call operator and ProcessStartInfo. Missing, empty, whitespace, array, absent-file and directory inputs reject rather than silently falling back. No compiler, installer, Blender or game runs in the regression. On this non-Windows preparation host the real PowerShell test is explicitly skipped; actual Windows source CI remains required.

Inherited architecture and full original-source proof requirements are documented in the retained orchestration-v2 README. No gzip input, completed witness, original delta, private asset, held vault/prone payload, actual candidate proof or activation is introduced here.

Microsoft documents Get-Command -All ordering at https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/get-command?view=powershell-7.6 .
