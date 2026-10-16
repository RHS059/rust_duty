param([Parameter(Mandatory=$true)][string]$Toolchain, [Parameter(Mandatory=$true)][string]$Receipt)
$ErrorActionPreference='Stop'
if ($Toolchain -notmatch '^\d+\.\d+\.\d+-x86_64-pc-windows-msvc$') { throw 'Exact reviewed Rust toolchain required' }
if (Test-Path -LiteralPath $Receipt) { throw 'Fresh Rust toolchain receipt required' }
# GitHub Windows images provide official rustup. Use its official distribution;
# an arbitrary RUSTUP_DIST_SERVER/RUSTUP_UPDATE_ROOT cannot redirect this install.
$env:RUSTUP_DIST_SERVER='https://static.rust-lang.org'
$env:RUSTUP_UPDATE_ROOT='https://static.rust-lang.org/rustup'
$rustup=(Get-Command rustup.exe -CommandType Application).Source
& $rustup toolchain install $Toolchain --profile minimal --target x86_64-pc-windows-msvc
if ($LASTEXITCODE -ne 0) { throw 'Official Rust toolchain installation failed' }
$rustc=(& $rustup which --toolchain $Toolchain rustc).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Actual rustc path unavailable' }
$cargo=(& $rustup which --toolchain $Toolchain cargo).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Actual Cargo path unavailable' }
$toolchainHome=Split-Path (Split-Path $rustc)
$manifest=Join-Path $toolchainHome 'lib/rustlib/multirust-channel-manifest.toml'
if (!(Test-Path -LiteralPath $manifest -PathType Leaf)) { throw 'Official installed Rust distribution manifest missing' }
function Record([string]$Path) { $f=Get-Item -LiteralPath $Path; return @{path=$f.FullName;sha256=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant();bytes=$f.Length} }
# The explicit SDK environment is populated by the official installed VS tools
# before this script. Pin all used compiler/linker tools plus selected SDK libs.
$tools=@((Get-Command link.exe -CommandType Application).Source,(Get-Command cl.exe -CommandType Application).Source,(Get-Command lib.exe -CommandType Application).Source)
$toolRoot=Split-Path $tools[0]
$tools+=@(Get-ChildItem -LiteralPath $toolRoot -File | Where-Object {$_.Extension -in @('.dll','.exe')} | ForEach-Object {$_.FullName})
foreach ($dir in ($env:LIB -split ';' | Where-Object {$_})) { $tools+=@(Get-ChildItem -LiteralPath $dir -Filter '*.lib' -File | ForEach-Object {$_.FullName}) }
$tools+=@(Get-ChildItem -LiteralPath (Join-Path $toolchainHome 'bin') -File | ForEach-Object {$_.FullName})
$tools+=@(Get-ChildItem -LiteralPath (Join-Path $toolchainHome 'lib') -Recurse -File | Where-Object {$_.Extension -in @('.dll','.rlib','.lib','.exe')} | ForEach-Object {$_.FullName})
$tools=@($tools | Sort-Object -Unique)
if ($tools.Count -eq 0) { throw 'Explicit native linker/SDK inventory missing' }
$result=[ordered]@{schema='rust-duty-onehand-rustup-install/v1';toolchain=$Toolchain;distribution='official-rustup';distribution_server='https://static.rust-lang.org';rustup=(Record $rustup);rustc=(Record $rustc);cargo=(Record $cargo);manifest=(Record $manifest);compiler_tool_files=$tools;compiler_tools=@($tools | ForEach-Object {Record $_})}
[IO.File]::WriteAllText($Receipt,($result | ConvertTo-Json -Depth 12),[Text.UTF8Encoding]::new($false))
