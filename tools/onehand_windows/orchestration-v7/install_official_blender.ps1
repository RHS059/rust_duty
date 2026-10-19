param([Parameter(Mandatory=$true)][string]$Destination, [Parameter(Mandatory=$true)][string]$Receipt)
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $Destination) { throw 'Fresh Blender installation directory required' }
if (Test-Path -LiteralPath $Receipt) { throw 'Preserve previous installer receipt' }
$root = 'https://download.blender.org/release/Blender4.3/'
$name = 'blender-4.3.2-windows-x64.zip'
$sha = '933a62a770c941e316535f893629ff106ddd2aa5a956f0081ec557439073d4f6'
$checksum = "$Destination.vendor.sha256"
Invoke-WebRequest ($root + 'blender-4.3.2.sha256') -OutFile $checksum
$pattern = '(?m)^([0-9a-fA-F]{64})\s+\*?' + [regex]::Escape($name) + '\r?$'
$matches = [regex]::Matches([IO.File]::ReadAllText($checksum), $pattern)
if ($matches.Count -ne 1 -or $matches[0].Groups[1].Value.ToLowerInvariant() -ne $sha) { throw 'Official vendor checksum missing, ambiguous or different; no secondary-manifest fallback' }
$zip = "$Destination.zip"
if (Test-Path -LiteralPath $zip) { throw 'Fresh archive target required' }
Invoke-WebRequest ($root + $name) -OutFile $zip
if ((Get-Item -LiteralPath $zip).Length -ne 405138423 -or (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sha) { throw 'Official Blender archive size or SHA256 differs' }
Expand-Archive -LiteralPath $zip -DestinationPath $Destination
$bundleHome = Join-Path $Destination 'blender-4.3.2-windows-x64'
$exe = Join-Path $bundleHome 'blender.exe'
if (!(Test-Path -LiteralPath $exe -PathType Leaf)) { throw 'Official archive lacks expected Blender executable' }
$result = [ordered]@{schema='rust-duty-onehand-official-blender-install/v1'; version='4.3.2'; vendor_checksum_url=($root+'blender-4.3.2.sha256'); archive_url=($root+$name); vendor_sha256=$sha; archive_sha256=$sha; archive_bytes=405138423; archive_path=$zip; bundle_root=$bundleHome; executable_sha256=(Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant(); vendor_checksum_verified=$true; vendor_checksum_file=@{path=$checksum;sha256=(Get-FileHash -LiteralPath $checksum -Algorithm SHA256).Hash.ToLowerInvariant()}}
[IO.File]::WriteAllText($Receipt, ($result | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
# No native executable is run during installation. The actual safe-read probe
# is subsequently run under the reviewed Windows owned-process supervisor.
