# Run personally on your Windows computer after approving dedicated release-signing setup.
# This script never logs private key material, enables workflows, publishes releases,
# changes GitHub authentication scopes, or grants an agent access to your computer.
[CmdletBinding()]
param([string]$SignerPath = "")
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Repository = "RHS059/rust_duty"
$QualifiedRepository = "github.com/$Repository"
$ExpectedRepositoryId = "1398577887"
$SecretName = "RUST_DUTY_RELEASE_SIGNING_KEY"
$VariableName = "RUST_DUTY_UPDATE_PUBLIC_KEY"

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "Run this setup personally on Windows. No key was created."
}
if (-not $env:LOCALAPPDATA) { throw "LOCALAPPDATA is unavailable. No key was created." }
$Gh = Get-Command gh -CommandType Application -ErrorAction Stop
& $Gh.Source auth status --hostname github.com
if ($LASTEXITCODE -ne 0) {
    throw "GitHub CLI is not already authenticated. Stop here and sign in personally; this script will not sign you in or expand token permissions."
}
$RepositoryId = (& $Gh.Source api --hostname github.com "repos/$Repository" --jq '.id' | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $RepositoryId -cne $ExpectedRepositoryId) { throw "The exact approved GitHub repository identity could not be verified. No key or setting was changed." }
if (-not $SignerPath) {
    $Adjacent = Join-Path $PSScriptRoot "rust-duty-release-sign.exe"
    $SourceBuild = Join-Path (Split-Path $PSScriptRoot -Parent) "updater\target\release\rust-duty-release-sign.exe"
    if (Test-Path -LiteralPath $Adjacent -PathType Leaf) { $SignerPath = $Adjacent }
    elseif (Test-Path -LiteralPath $SourceBuild -PathType Leaf) { $SignerPath = $SourceBuild }
    else { throw "Use the extracted Windows updater artifact containing rust-duty-release-sign.exe, or supply -SignerPath. No key was created." }
}
$SignerPath = (Resolve-Path -LiteralPath $SignerPath).Path
$KeyDirectory = Join-Path $env:LOCALAPPDATA "RustDutyReleaseSigning"
$PrivatePath = Join-Path $KeyDirectory "release-signing.key"
$PublicPath = Join-Path $KeyDirectory "release-public-key.hex"

Write-Host "Repository: $Repository"
Write-Host "This creates (or reuses) one dedicated Ed25519 release-signing key on THIS computer."
Write-Host "The private file stays outside the repository in a current-user-only folder."
Write-Host "Your existing gh login will encrypt/upload it as repository Actions secret $SecretName."
Write-Host "The separate PUBLIC key will be saved as repository variable $VariableName."
Write-Host "Anyone who can modify trusted release workflow code could use the signing secret; protect repository write access."
Write-Host "No workflow is enabled and no release is published by this script."
$Confirmation = Read-Host "Type SET UP RUST DUTY SIGNING to approve these exact local key/ACL and repository secret/variable actions"
if ($Confirmation -cne "SET UP RUST DUTY SIGNING") { throw "Cancelled. No key or repository setting was changed." }

# Do not operate through a junction/symlink or inside a checkout.
$Cursor = [IO.DirectoryInfo]::new($KeyDirectory)
while ($null -ne $Cursor) {
    if ($Cursor.Exists -and (($Cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) { throw "Key path contains a reparse point. Stopping." }
    if (Test-Path -LiteralPath (Join-Path $Cursor.FullName ".git")) { throw "Refusing to place private key material inside a repository." }
    $Cursor = $Cursor.Parent
}
if (-not (Test-Path -LiteralPath $KeyDirectory)) { [void][IO.Directory]::CreateDirectory($KeyDirectory) }
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Acl = [Security.AccessControl.DirectorySecurity]::new()
$Acl.SetOwner($Identity.User)
$Acl.SetAccessRuleProtection($true, $false)
$Rule = [Security.AccessControl.FileSystemAccessRule]::new(
    $Identity.User,
    [Security.AccessControl.FileSystemRights]::FullControl,
    ([Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit),
    [Security.AccessControl.PropagationFlags]::None,
    [Security.AccessControl.AccessControlType]::Allow)
[void]$Acl.AddAccessRule($Rule)
Set-Acl -LiteralPath $KeyDirectory -AclObject $Acl

function Read-GhCaptured([string]$Arguments) {
    $Info = [Diagnostics.ProcessStartInfo]::new()
    $Info.FileName = $Gh.Source; $Info.Arguments = $Arguments; $Info.UseShellExecute = $false
    $Info.RedirectStandardOutput = $true; $Info.RedirectStandardError = $true
    $Process = [Diagnostics.Process]::new(); $Process.StartInfo = $Info; [void]$Process.Start()
    $OutputTask = $Process.StandardOutput.ReadToEndAsync(); $ErrorTask = $Process.StandardError.ReadToEndAsync()
    $Process.WaitForExit()
    $Output = $OutputTask.GetAwaiter().GetResult(); $Errors = $ErrorTask.GetAwaiter().GetResult()
    $Result = @{ Code = $Process.ExitCode; Output = $Output; Errors = $Errors }; $Process.Dispose(); return $Result
}
$ExistingVariable = Read-GhCaptured "api --hostname github.com repos/$Repository/actions/variables/$VariableName"
$ExistingPublicKey = $null
if ($ExistingVariable.Code -eq 0) { $ExistingPublicKey = ($ExistingVariable.Output | ConvertFrom-Json).value }
elseif ($ExistingVariable.Errors -notmatch 'HTTP 404') { throw "Could not inspect existing public trust. Stop before creating or replacing a key." }
$ExistingSecretResponse = Read-GhCaptured "secret list --repo $QualifiedRepository --app actions --json name"
if ($ExistingSecretResponse.Code -ne 0) { throw "Could not inspect existing secret names. Stop before creating a key." }
$ExistingSecrets = @($ExistingSecretResponse.Output | ConvertFrom-Json)
$HasRemoteSecret = @($ExistingSecrets | Where-Object { $_.name -ceq $SecretName }).Count -gt 0

$HasPrivate = Test-Path -LiteralPath $PrivatePath -PathType Leaf
$HasPublic = Test-Path -LiteralPath $PublicPath -PathType Leaf
if ($HasPrivate -ne $HasPublic) { throw "Only one key-pair file exists. Stop and restore the missing file; this script will not replace or rotate your key." }
if (-not $HasPrivate -and ($ExistingPublicKey -or $HasRemoteSecret)) {
    throw "Repository signing trust already exists but this computer has no local pair. Restore the existing owner key; this setup will not rotate deployed trust."
}
if ($HasRemoteSecret -and -not $ExistingPublicKey) { throw "A signing secret exists without a public variable. Resolve that partial setup personally before continuing." }
if (-not $HasPrivate) {
    & $SignerPath keygen --private-key $PrivatePath --public-key $PublicPath --confirm-create-release-key
    if ($LASTEXITCODE -ne 0) { throw "Local key generation failed. No repository secret was set." }
}
$PrivateItem = Get-Item -LiteralPath $PrivatePath -Force
if (($PrivateItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Private key file is a reparse point. Stopping." }
$PrivateAcl = [Security.AccessControl.FileSecurity]::new()
$PrivateAcl.SetOwner($Identity.User)
$PrivateAcl.SetAccessRuleProtection($true, $false)
$PrivateRule = [Security.AccessControl.FileSystemAccessRule]::new($Identity.User, [Security.AccessControl.FileSystemRights]::FullControl, [Security.AccessControl.AccessControlType]::Allow)
[void]$PrivateAcl.AddAccessRule($PrivateRule)
Set-Acl -LiteralPath $PrivatePath -AclObject $PrivateAcl
$PublicKey = [IO.File]::ReadAllText($PublicPath).Trim()
if ($PublicKey -notmatch '^[0-9a-f]{64}$') { throw "Public key file is malformed." }
if ($ExistingPublicKey -and $ExistingPublicKey -cne $PublicKey) { throw "Existing repository public trust differs from this local key. Refusing an implicit key rotation." }
$DerivedPublicKey = (& $SignerPath public-key --private-key $PrivatePath | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $DerivedPublicKey -cne $PublicKey) { throw "Private/public key files do not match. Stopping." }

function Set-GhValueViaStdin([string]$Arguments, [string]$Value) {
    # Never put sensitive material in a command argument, terminal output, or a repository file.
    $Info = [Diagnostics.ProcessStartInfo]::new()
    $Info.FileName = $Gh.Source
    $Info.Arguments = $Arguments
    $Info.UseShellExecute = $false
    $Info.RedirectStandardInput = $true
    $Info.RedirectStandardOutput = $true
    $Info.RedirectStandardError = $true
    $Process = [Diagnostics.Process]::new()
    $Process.StartInfo = $Info
    [void]$Process.Start()
    # Drain both pipes concurrently; never reflect unexpected private CLI output into a transcript.
    $OutputTask = $Process.StandardOutput.ReadToEndAsync()
    $ErrorTask = $Process.StandardError.ReadToEndAsync()
    $Process.StandardInput.Write($Value)
    $Process.StandardInput.Close()
    $Process.WaitForExit()
    $Output = $OutputTask.GetAwaiter().GetResult()
    $Errors = $ErrorTask.GetAwaiter().GetResult()
    if ($Process.ExitCode -ne 0) {
        throw "GitHub CLI rejected the repository setting. Check your existing account's permissions personally; no auth/scope changes were attempted. The local key files were preserved."
    }
    $Process.Dispose()
}
$PrivateMaterial = [IO.File]::ReadAllText($PrivatePath)
try {
    Set-GhValueViaStdin "secret set $SecretName --repo $QualifiedRepository --app actions" $PrivateMaterial
} finally { $PrivateMaterial = $null }
Set-GhValueViaStdin "variable set $VariableName --repo $QualifiedRepository" $PublicKey

$RemotePublicKey = (& $Gh.Source variable get $VariableName --repo $QualifiedRepository | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $RemotePublicKey -cne $PublicKey) { throw "Public variable verification failed. Do not enable releases yet." }
$SecretNames = (& $Gh.Source secret list --repo $QualifiedRepository --app actions --json name --jq '.[].name' | Out-String)
if ($LASTEXITCODE -ne 0 -or ($SecretNames -split '\r?\n') -notcontains $SecretName) { throw "Secret-name verification failed. Do not enable releases yet." }

Write-Host "Signing setup completed for $Repository. Secret presence and public variable verified."
Write-Host "Private key: kept in your protected local folder. Back it up securely; never paste or upload it to chat."
Write-Host "Public key file: $PublicPath"
Write-Host "PUBLIC KEY (safe to share back for the pinned bootstrap):"
Write-Host $PublicKey
Write-Host "Send only that PUBLIC key and 'setup completed'. Release publication still needs the reviewed workflow enabled separately."
