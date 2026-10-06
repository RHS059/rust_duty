# Independent bounded GL package/source review

Reviewed 2026-10-06. The recovered MSYS2 package chain, combined with the existing original native context receipt and implementation review, is sufficient to apply the audited Mesa 26.2.4 implementation to the bounded OpenGL source obligations. This uses ordinary trust in the official distribution and compiler toolchain. It does not assert reproducible compilation, a new native observation, comprehensive loaded-module attestation, or final migration acceptance.

## Verified provenance

- Official package catalog: https://packages.msys2.org/packages/mingw-w64-ucrt-x86_64-mesa . Its 26.2.4-1 SHA-256 matches both the downloaded archive and the original committed reference lock: `82a30042848b6393f2a21cdee66b164e4cf4fe15a9721a5f1d1c7280e004ebdc`.
- Raw archive `.BUILDINFO` and `.PKGINFO` members equal the inspected files byte-for-byte. SHA-256: `a513fc93b5398ceeacd9db6807569c801159e7400eaddb22325ef311b8375470` and `7fe60dab4ed88b035ff459cf552d3aab227a0f9316f7deb281951fa88b173938` respectively.
- `.BUILDINFO` pins the inspected PKGBUILD SHA-256 `ccdd1282167328984429b2275813015efd4e11d3a108f06ac116ca74bba61932`. The recipe selects upstream source SHA-256 `bce5f7fbebb934373b86c999a064d52fb5065878dc57f287f95346648ec832e9`, matching the independently inspected Mesa archive. Its preparation extracts that source, excluding only CI/formatting files; it applies no source patches. The release configuration includes llvmpipe and shared LLVM. The runtime environment and native adapter receipt select llvmpipe from the configured drivers. Build metadata identifies LLVM 22.1.8.
- Raw package `ucrt64/bin/opengl32.dll`: 131,693 bytes, SHA-256 `f73078a77b51c634faa36f616a8eb9f7f1b30f82b21d689267b9146dbbc8b943`.
- Raw package `ucrt64/bin/libgallium_wgl.dll`: 23,835,212 bytes, SHA-256 `42362a4b7063591ad1f2bf5d1dbf26fb808ac49cb419ac237d63c8f1cb49bc75`.
- Both DLL identities match the original capture input manifest. That manifest has SHA-256 `67b4116706f49eb8f8a7883474002055407227288d7b65ae6532b12eda45da9f`.
- The original commit's lock bytes have SHA-256 `4c0e0033797ed12bacf7f3055fb66d680f4d2eda40491e108642cf8d8d943d8b`. Explicit LF-to-CRLF conversion produces `d33d42c7e859e75aae2475494103c12691f4cda81335fc6783ebe1bafad268dd`, exactly the retained native lock digest. The normalization is disclosed rather than assigning a new digest as historical provenance.

## Original runtime link

The retained `native-source-oracle-success-diagnostics-37427554951.zip` member `evidence/revalidation/summary.json` has SHA-256 `58e9bdef84be99b577b275c4c942cb7a631bb9012eb8c7e66dd807a2c3e67790`. Its capture context identifies commit `8f571464be706d0abde862e124582a188f633baf`, run `37415102452`, attempt 1. Its original ADS capability receipt identifies capture `9939cde2ee400f0b2812e150526ea2e5b8088224a806550e4713ff6bf5e06897`, Mesa 26.2.4, llvmpipe LLVM 22.1.8, a complete measurement, and app-local-only procedure resolution. Its target receipt identifies the 960x540 target with depth and the plain non-resolving allocation.

`src/legacy_macroquad/precision_receipt.rs` matches the original capture commit exactly: SHA-256 `2f1a2a689926ae51643fa353a1aaa1c759a6dc81f4653dbf4fb840765eb3a4be`. It derives the full adjacent `opengl32.dll` path from the running executable, requires that module to be already loaded, resolves its WGL exports, and requires a current context. It never loads a fallback DLL. Failed path, context, export, or query checks remain unavailable or blocked. This agrees with Microsoft's documented full-path GetModuleHandle behavior: https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-getmodulehandlew .

The receipt does not hash every mapped dependency or certify compiler equivalence. Accordingly, `loaded_modules_verified=false` and the original profile/acceptance flags remain unchanged. Those limitations do not require another rendering run merely to establish ordinary package-to-source provenance.

## Verification performed

Recomputed package, source, recipe, metadata, lock, and DLL hashes; compared raw archive metadata with the inspected copies; compared both DLL members against the original manifest; reran `verify_binding.py`; reviewed the recipe and original receipt code; and independently checked the official package catalog and retained native context. No downloaded binary was executed and no native rendering was performed.

The package/source binding record has SHA-256 `f635a05e054757fd9406b43a624cfec242ca342c421e4cfa84207634adaff8d6`.

## Relation to the finite source supplement

The previously reviewed corrected GL geometry input has SHA-256 `458655709d010fd004eccc04234094ec09d66428e286e47c892ab5578d9a3204`; its geometry summary is `44d0fa29fa6707d1b59fcfda05dc2c1fe2f4b12ca25972a8d00f855237314635`. The arithmetic summary is `e485bdeba46480f14911e44fa3e83c7dfcc3f24ec4ba4ef88f4427047064ab25`; the full fragment narrowing result is `edaecbca5d3a485187a02d2662588170b32b6df59f9e1cc1e032ebfc99648696`.

Independent review verified 210 arithmetic rows per backend, including 160 strictly separated or hidden empty rows, and 50 positive GL rows after fragment narrowing. Required support totals 47,558 samples, with a minimum of four; 1,487 uncertain subtriangles have their entire possible support excluded. Every final required mask is a subset of its original, and every original possible mask is contained in its corrected counterpart. Thus the preserved successful unchanged-pixel comparison entails the adjusted comparison by set inclusion. Tests passed: 24 Rust, 10 clipping, and 10 fragment tests, including the corrected empty-variant regression.

Normal-path consumption must still bind these exact reviewed identities, backend/profile, extent, complete expected frame set, and complete triangle/cull inventory; positive sample retention alone is not acceptance. DX12/WARP requires its own bounded native implementation corroboration. This package review supplies no WARP premise.
