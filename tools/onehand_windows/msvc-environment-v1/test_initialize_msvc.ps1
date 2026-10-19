#requires -Version 7.3
param([Parameter(Mandatory=$true)][string]$Initializer)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if (!$IsWindows) { throw 'MSVC execution regression requires Windows; do not report a non-Windows skip as a pass' }
if (!(Test-Path -LiteralPath $Initializer -PathType Leaf)) { throw 'Production initializer required' }

function Assert-True([bool]$Condition,[string]$Message) {
  if (!$Condition) { throw ('MSVC regression: '+$Message) }
}
function Write-Fixture([string]$Directory,[string]$Body) {
  [IO.Directory]::CreateDirectory($Directory) | Out-Null
  $path=Join-Path $Directory 'VsDevCmd.bat'
  [IO.File]::WriteAllText($path,($Body -replace "`r?`n","`r`n"),[Text.Encoding]::ASCII)
  return [IO.Path]::GetFullPath($path)
}
function Assert-Failure([string]$Batch,[string]$Expected,[string]$File) {
  [IO.File]::WriteAllText($File,"UNCHANGED=sentinel`n",[Text.UTF8Encoding]::new($false))
  $before=[IO.File]::ReadAllBytes($File)
  $caught=$null
  try { & $Initializer -DeveloperCommandPath $Batch -EnvironmentFile $File | Out-Null } catch { $caught=$_.Exception.Message }
  Assert-True ($null -ne $caught -and $caught.Contains($Expected)) ('expected failure: '+$Expected)
  Assert-True ([Convert]::ToBase64String($before) -ceq [Convert]::ToBase64String([IO.File]::ReadAllBytes($File))) 'failure appended environment data'
}

$root=Join-Path ([IO.Path]::GetTempPath()) ('MSVC regression (space & '+[char]0x03A9+') ! '+[Guid]::NewGuid().ToString('N'))
$originalMode=$PSNativeCommandArgumentPassing
$originalPath=$env:PATH
$originalGitHubEnv=$env:GITHUB_ENV
$success=@'
@echo off
if not "%*"=="-arch=x64 -host_arch=x64" exit /b 81
set "PATH=%~dp0bin;%PATH%"
set "INCLUDE=%~dp0include with spaces=preserved"
set "LIB=%~dp0lib with spaces"
set "LIBPATH=%~dp0metadata"
set "VCToolsInstallDir=%~dp0VC tools\"
set "WindowsSdkDir=%~dp0Windows SDK\"
set "VSCMD_ARG_HOST_ARCH=x64"
set "VSCMD_ARG_TGT_ARCH=x64"
set "VCToolsVersion=regression-version"
set "GITHUB_ENV=must-not-escape"
set "GITHUB_TOKEN=must-not-escape"
set "GITHUB_OUTPUT=must-not-escape"
set "RUNNER_TEMP=must-not-escape"
set "ACTIONS_RUNTIME_TOKEN=must-not-escape"
set "NODE_OPTIONS=must-not-escape"
set "ONEHAND_PACKAGE=must-not-escape"
set "PROOF_COMMIT=must-not-escape"
set "CUSTOM_SECRET=must-not-escape"
exit /b 0
'@
try {
  $batch=Write-Fixture (Join-Path $root 'Program Files (x86)/Microsoft Visual Studio/Common7/Tools') $success
  # Execute the exact production helper in every native-argument mode. The
  # production ProcessStartInfo launch must be independent of all three modes.
  foreach ($mode in @('Legacy','Standard','Windows')) {
    $PSNativeCommandArgumentPassing=$mode
    $output=Join-Path $root ($mode+'.env')
    & $Initializer -DeveloperCommandPath $batch -EnvironmentFile $output | Out-Null
    $lines=[IO.File]::ReadAllLines($output,[Text.Encoding]::UTF8)
    $prefix=(Split-Path $batch)+[IO.Path]::DirectorySeparatorChar
    Assert-True ($lines -ccontains ('INCLUDE='+$prefix+'include with spaces=preserved')) 'space/Unicode/equals value changed'
    Assert-True ($lines -ccontains ('PATH='+$prefix+'bin;'+$originalPath)) 'PATH was truncated or changed'
    Assert-True ($lines -ccontains 'VSCMD_ARG_HOST_ARCH=x64') 'x64 host argument missing'
    Assert-True ($lines -ccontains 'VSCMD_ARG_TGT_ARCH=x64') 'x64 target argument missing'
    Assert-True ($lines -ccontains 'VCToolsVersion=regression-version') 'optional toolchain variable missing'
    Assert-True (($lines -join "`n") -notmatch 'must-not-escape|GITHUB_|RUNNER_|ACTIONS_|NODE_OPTIONS|ONEHAND_|PROOF_COMMIT|CUSTOM_SECRET') 'unrelated runner/control/credential variable exported'
    Assert-True ([IO.File]::ReadAllBytes($output)[0] -ne 0xEF) 'environment file has a UTF-8 BOM'
    Assert-True ($env:PATH -ceq $originalPath -and $env:GITHUB_ENV -ceq $originalGitHubEnv) 'initializer mutated parent process environment'

    $failed=Write-Fixture (Join-Path $root ('failure '+$mode)) ($success.Replace('exit /b 0','exit /b 37'))
    Assert-Failure $failed 'exit code 37' (Join-Path $root ($mode+'-failure.env'))
    $early=Write-Fixture (Join-Path $root ('early failure '+$mode)) "@echo off`nexit /b 23`n"
    Assert-Failure $early 'exit code 23' (Join-Path $root ($mode+'-early.env'))
  }
  $missing=Write-Fixture (Join-Path $root 'missing required field') ($success.Replace('set "LIB=%~dp0lib with spaces"','set "LIB="'))
  Assert-Failure $missing 'missing required LIB' (Join-Path $root 'missing.env')
  $wrong=Write-Fixture (Join-Path $root 'wrong architecture') ($success.Replace('set "VSCMD_ARG_TGT_ARCH=x64"','set "VSCMD_ARG_TGT_ARCH=x86"'))
  Assert-Failure $wrong 'must target and host x64' (Join-Path $root 'wrong.env')
  $unsafe=Write-Fixture (Join-Path $root 'percent %PATH% expression') $success
  Assert-Failure $unsafe 'Unsupported characters' (Join-Path $root 'unsafe.env')
  Assert-Failure (Join-Path $root 'absent/VsDevCmd.bat') 'Existing installed VsDevCmd.bat required' (Join-Path $root 'absent.env')
  Write-Output 'MSVC Windows execution regression passed: 3 argument modes, space/Unicode paths, preserved values, restricted export, and fail-closed native exits/required inputs'
} finally {
  $PSNativeCommandArgumentPassing=$originalMode
  if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
}
