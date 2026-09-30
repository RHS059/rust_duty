# OPTIONAL user-run upload for exactly the previously approved converted HK416 file.
# No other files, branches, authentication grants, or repository settings are changed.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$WeaponPath)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Repository = "RHS059/rust_duty"
$ExpectedRepositoryId = "1398577887"
$Branch = "aella/weapon-asset-pipeline"
$Destination = "assets/weapons/hk416a5.vrm"
$ExpectedHash = "082b8302a39c8fd3218f3c732f8c3a06c1af1fb40f703f8d64f581b38b32d4aa"
$Gh = Get-Command gh -CommandType Application -ErrorAction Stop
& $Gh.Source auth status --hostname github.com
if ($LASTEXITCODE -ne 0) { throw "Sign in personally first. This script does not log in or change token permissions." }
$RepositoryId = (& $Gh.Source api --hostname github.com "repos/$Repository" --jq '.id' | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $RepositoryId -cne $ExpectedRepositoryId) { throw "The exact approved GitHub repository identity could not be verified. Nothing was uploaded." }
$WeaponPath = (Resolve-Path -LiteralPath $WeaponPath).Path
if ((Get-FileHash -LiteralPath $WeaponPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ExpectedHash) {
    throw "File hash does not match the single approved HK416 asset. Nothing was uploaded."
}
$ExistingBranch = (& $Gh.Source api --hostname github.com "repos/$Repository/branches/aella%2Fweapon-asset-pipeline" --jq '.name' | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $ExistingBranch -cne $Branch) { throw "The existing approved feature branch could not be verified; nothing was uploaded." }
Write-Host "Optional public upload: only $Destination in $Repository, branch $Branch."
Write-Host "Verified SHA-256: $ExpectedHash"
Write-Host "This uploads the converted runtime model from your game bundle. It does not upload source FBX/GLB files, arms, settings, signing keys or any private directory."
if ((Read-Host "Type UPLOAD APPROVED HK416 to confirm this single-file public upload") -cne "UPLOAD APPROVED HK416") { throw "Cancelled. Nothing was uploaded." }

function Invoke-GhCaptured([string]$Arguments, [string]$InputText = "") {
    $Info = [Diagnostics.ProcessStartInfo]::new()
    $Info.FileName = $Gh.Source; $Info.Arguments = $Arguments; $Info.UseShellExecute = $false
    $Info.RedirectStandardInput = $true; $Info.RedirectStandardOutput = $true; $Info.RedirectStandardError = $true
    $Process = [Diagnostics.Process]::new(); $Process.StartInfo = $Info; [void]$Process.Start()
    $OutputTask = $Process.StandardOutput.ReadToEndAsync(); $ErrorTask = $Process.StandardError.ReadToEndAsync()
    $Process.StandardInput.Write($InputText); $Process.StandardInput.Close(); $Process.WaitForExit()
    $Output = $OutputTask.GetAwaiter().GetResult(); $Errors = $ErrorTask.GetAwaiter().GetResult()
    $Result = @{ Code = $Process.ExitCode; Output = $Output; Errors = $Errors }; $Process.Dispose(); return $Result
}
$Existing = Invoke-GhCaptured "api --hostname github.com --method GET repos/$Repository/contents/$Destination`?ref=aella%2Fweapon-asset-pipeline"
$PreviousSha = $null
if ($Existing.Code -eq 0) { $PreviousSha = ($Existing.Output | ConvertFrom-Json).sha }
elseif ($Existing.Errors -notmatch 'HTTP 404') { throw "Could not inspect the destination file. Nothing was uploaded." }
$Bytes = [IO.File]::ReadAllBytes($WeaponPath)
# Verify the exact immutable byte buffer that will be uploaded, not only an earlier file snapshot.
$Sha256 = [Security.Cryptography.SHA256]::Create()
$BufferedHash = ([BitConverter]::ToString($Sha256.ComputeHash($Bytes))).Replace("-", "").ToLowerInvariant()
$Sha256.Dispose()
if ($BufferedHash -cne $ExpectedHash) { throw "The selected file changed after confirmation. Nothing was uploaded." }
$GitHeader = [Text.Encoding]::UTF8.GetBytes("blob $($Bytes.Length)`0")
$BlobBytes = [byte[]]::new($GitHeader.Length + $Bytes.Length)
[Array]::Copy($GitHeader, 0, $BlobBytes, 0, $GitHeader.Length)
[Array]::Copy($Bytes, 0, $BlobBytes, $GitHeader.Length, $Bytes.Length)
$Sha1 = [Security.Cryptography.SHA1]::Create()
$LocalBlobSha = ([BitConverter]::ToString($Sha1.ComputeHash($BlobBytes))).Replace("-", "").ToLowerInvariant()
$Sha1.Dispose()
if ($PreviousSha -ceq $LocalBlobSha) { Write-Host "The exact approved file is already present on the feature branch. No commit created."; exit 0 }
$Payload = @{ message = "Package the approved HK416 runtime asset"; content = [Convert]::ToBase64String($Bytes); branch = $Branch }
if ($PreviousSha) { $Payload.sha = $PreviousSha }
$Result = Invoke-GhCaptured "api --hostname github.com --method PUT repos/$Repository/contents/$Destination --input -" ($Payload | ConvertTo-Json -Compress)
if ($Result.Code -ne 0) { throw "The single-file upload failed. No broader upload or permission changes were attempted." }
$Response = $Result.Output | ConvertFrom-Json
if ($Response.content.sha -cne $LocalBlobSha -or $Response.content.path -cne $Destination) { throw "Upload response verification failed. Check the feature branch before retrying." }
Write-Host "Verified approved single-file upload to the existing feature branch:"
Write-Host $Response.commit.html_url
