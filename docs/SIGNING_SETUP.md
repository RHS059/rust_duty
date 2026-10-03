# One-time release-signing setup: run personally on Windows

## What is ready, and what is still blocked

The signing helper, user-run PowerShell scripts and bootstrap CI are prepared. No production signing key has been created here, no secret has been transmitted, and the publication workflow remains disabled. The regular updater CI builds **UNCONFIGURED** Windows/Linux bootstrap artifacts without secrets or key generation. These setup builds cannot download production updates.

To activate the update channel, the owner must personally complete local key/secret setup, return the **public** key, and have the pinned bootstrap/release workflow reviewed and enabled. Existing owner approval does not allow an assistant to enter/transmit the private signing key. The local script is the handoff for that sensitive step. Signing-key setup does not grant access to your computer and does not create or expand a GitHub login/token.

## Prerequisites

1. Your own Windows computer and an existing GitHub CLI installation from [GitHub CLI](https://cli.github.com/)
2. Your existing `gh` login must already work for `github.com` and be authorized to set repository Actions secrets/variables in **RHS059/rust_duty**
3. The reviewed Windows artifact **rust-duty-signing-setup-windows** from the owner setup CI, extracted into one folder (the full unconfigured bootstrap kit also contains the same helper)
4. Explicit approval for the dedicated signing key, the private local folder ACL and the repository signing secret/public variable

Check your existing authentication yourself:

```powershell
gh auth status --hostname github.com
```

The script pins every request to `github.com`, verifies repository ID `1398577887`, and stops if authentication is missing. A custom `GH_HOST` cannot redirect private-key or asset transmission. It does not run `gh auth login`, refresh scopes, generate GitHub tokens, change repository permissions or ask an assistant for credentials. If you lack access, stop and resolve it personally with the repository owner.

The setup-only artifact includes `rust-duty-release-sign.exe`, `setup-release-signing.ps1`, `publish-approved-weapon.ps1`, documentation and dependency licenses. It contains no game or updater launcher; launcher delivery is separately gated on its full Windows tests. No Rust or Python installation is needed to run the one-time Windows setup helper. A source-build alternative is `cargo build --manifest-path updater/Cargo.toml --locked --release --bins`.

## Exact owner-run command

From the extracted Windows artifact folder:

```powershell
powershell -NoProfile -File .\setup-release-signing.ps1
```

Or from a source checkout after building the helper:

```powershell
powershell -NoProfile -File .\tools\setup-release-signing.ps1
```

Do not add an execution-policy bypass. If local policy blocks a reviewed script, stop and use your organization's normal approved script-execution process. No PowerShell execution policy, firewall, GitHub authentication scope or OS-wide security setting is changed by this setup.

Read the actions shown by the script. Only if you approve them, type exactly:

```
SET UP RUST DUTY SIGNING
```

That confirmation covers:

- Creating/reusing a dedicated Ed25519 release-signing key with operating-system secure randomness on **your** computer
- Protecting `%LOCALAPPDATA%\RustDutyReleaseSigning` so only the current Windows user is granted access by its explicit ACL
- Sending the private key through **stdin** to your own existing `gh secret set`, which locally encrypts it for GitHub; never through command arguments, terminal output, chat or a repository file
- Setting a separate public-key repository variable

The script does not enable a workflow, publish a release, upload game assets or grant an assistant any ongoing access. It refuses existing partial/mismatched key pairs and must not be used to rotate deployed trust silently. Keep an offline secure backup of the private key; losing or rotating it requires a deliberate bootstrap-trust transition.

## Exact files and GitHub settings

Local, outside the repository:

- `%LOCALAPPDATA%\RustDutyReleaseSigning\release-signing.key`: private Ed25519 seed in a versioned local file format; never share this file
- `%LOCALAPPDATA%\RustDutyReleaseSigning\release-public-key.hex`: 64-character public key; safe to share

Repository **RHS059/rust_duty**:

- Actions secret: **RUST_DUTY_RELEASE_SIGNING_KEY**
- Actions variable: **RUST_DUTY_UPDATE_PUBLIC_KEY**

No GitHub token secret is created. A future approved release job uses GitHub's existing ephemeral `GITHUB_TOKEN` with only job-level `contents: write`; ordinary build jobs remain `contents: read`. No `id-token` grant is needed. Protect repository write access: malicious changes to a trusted release workflow could misuse its signing secret.

## Expected successful output

The script checks secret-name presence (GitHub never returns its value) and reads back the public variable. It then prints:

```
Signing setup completed for RHS059/rust_duty. Secret presence and public variable verified.
PUBLIC KEY (safe to share back for the pinned bootstrap):
<64 lowercase hexadecimal characters>
```

Send back **only that public-key value** and “setup completed”. Do not paste private-key contents, upload the private file, post a shell transcript or send a screenshot containing private material. The assistant can then independently check secret presence/public configuration with authorized read-only access and compile the approved public key into the reviewed production bootstrap.

The helper never prints private material. `public-key` prints only derived public information. The private generation command has an explicit confirmation flag, refuses repository paths and never overwrites key files. Automated tests use a clearly public deterministic fixture seed; they do **not** exercise production random key generation. Native PowerShell execution still requires the owner-run setup; CI only parses the scripts and tests non-production fixtures.

## Pinned bootstrap and release publication

The public key is supplied at compile time as `RUST_DUTY_UPDATE_PUBLIC_KEY`. `rust-duty-launcher trust-status` prints `UNCONFIGURED` or `CONFIGURED <public-key>` without touching an install directory. There is no runtime trust override or insecure update mode.

After actual owner-local setup is verified, review `.github/workflow-drafts/publish-updates.yml.disabled` before promoting it into active workflows. It is a manual-only publication draft. It:

1. Builds the game payload and bootstrap for Windows MSVC/Linux GNU, pinning the approved public variable
2. If a previous version is supplied, downloads only its exact repository release bundle/manifest, verifies that manifest with the pinned public key and verifies the baseline hash
3. Builds real copy/add deltas against that exact full baseline; the first release has no previous baseline
4. Signs only prepared manifest bytes using the dedicated secret via stdin, verifies the public signature, and packages the pinned bootstrap with actual dependency notices
5. Creates a versioned GitHub release with a monotonic sequence and exact asset names; marks it latest only after assets have uploaded

A previous version is required for subsequent differential releases; supply its actual stable version, not an unrelated CI artifact ZIP. Keep old full `.rdb` release assets available. Sequence and semantic version must both increase. The workflow must never overwrite an existing published version or silently replace the signing key. Signing does not make private source assets redistributable: only explicitly approved public runtime files belong in payloads.

No workflow is automatically enabled by the setup script. No production release operation has been tested against a live channel yet. Windows/Linux CI build results and the initial signed-release install/update smoke test must be verified before claiming automatic updates are live.

## Optional: finish the already-approved HK416 upload

This is separate from signing setup and never runs automatically. Use only if the exact approved converted HK416 file still needs to be added to the existing feature branch. The file is in the previously downloaded game bundle at `assets\weapons\hk416a5.vrm`.

```powershell
powershell -NoProfile -File .\publish-approved-weapon.ps1 -WeaponPath "C:\path\to\game\assets\weapons\hk416a5.vrm"
```

The script requires the exact SHA-256:

```
082b8302a39c8fd3218f3c732f8c3a06c1af1fb40f703f8d64f581b38b32d4aa
```

It then asks you to type `UPLOAD APPROVED HK416`. Only that one file can be uploaded, to `assets/weapons/hk416a5.vrm` on the existing **aella/weapon-asset-pipeline** branch of **RHS059/rust_duty**. It never writes main, creates a branch, uploads FBX/GLB originals, imports a private folder, uploads arms or exposes signing keys. An already-identical file causes a no-op. The final output is the verified feature-branch commit link.

## Source references

- [GitHub CLI secret set](https://cli.github.com/manual/gh_secret_set): local encryption and stdin input
- [GitHub CLI variable set](https://cli.github.com/manual/gh_variable_set): separate public configuration
- [GitHub CLI authentication status](https://cli.github.com/manual/gh_auth_status): existing login verification
- [Microsoft Set-Acl](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.security/set-acl): explicit local directory access control
