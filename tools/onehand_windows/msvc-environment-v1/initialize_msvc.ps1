#requires -Version 7.0
param(
  [Parameter(Mandatory=$true)][string]$DeveloperCommandPath,
  [Parameter(Mandatory=$true)][string]$EnvironmentFile
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if (!$IsWindows) { throw 'MSVC initialization requires Windows' }
if (![IO.Path]::IsPathFullyQualified($DeveloperCommandPath) -or
    !(Test-Path -LiteralPath $DeveloperCommandPath -PathType Leaf) -or
    [IO.Path]::GetFileName($DeveloperCommandPath) -ine 'VsDevCmd.bat') {
  throw 'Existing installed VsDevCmd.bat required'
}
# cmd expands percent expressions even in quotes. Reject them, quotes and line
# breaks rather than interpreting a path as command text. /v:off preserves !.
if ($DeveloperCommandPath -match '[%"\r\n\x00]') { throw 'Unsupported characters in MSVC command path' }
$DeveloperCommandPath=[IO.Path]::GetFullPath($DeveloperCommandPath)
if (![IO.Path]::IsPathFullyQualified($EnvironmentFile)) { throw 'Absolute environment output path required' }
if ([string]::IsNullOrWhiteSpace($env:ComSpec) -or
    !(Test-Path -LiteralPath $env:ComSpec -PathType Leaf)) { throw 'Windows command processor unavailable' }

$start=[Diagnostics.ProcessStartInfo]::new()
$start.FileName=$env:ComSpec
$start.UseShellExecute=$false
$start.CreateNoWindow=$true
$start.RedirectStandardOutput=$true
$start.RedirectStandardError=$true
$start.StandardOutputEncoding=[Text.Encoding]::Unicode
# Raw Arguments is intentional: PowerShell's native argument binder and the
# CRT escaping used by ArgumentList must not rewrite cmd's /s /c quotation.
# cmd /s strips ONLY the outermost quotes; the batch path stays quoted.
# && prevents environment capture after a failing VsDevCmd. /u makes SET UTF-16.
$start.Arguments='/d /u /v:off /s /c ""'+$DeveloperCommandPath+'" -arch=x64 -host_arch=x64 >nul && set"'
$process=[Diagnostics.Process]::Start($start)
try {
  $stdout=$process.StandardOutput.ReadToEndAsync()
  $stderr=$process.StandardError.ReadToEndAsync()
  if (!$process.WaitForExit(120000)) {
    $process.Kill($true)
    $process.WaitForExit()
    throw 'MSVC environment initialization timed out'
  }
  $text=$stdout.GetAwaiter().GetResult()
  $discard=$stderr.GetAwaiter().GetResult()
  if ($process.ExitCode -ne 0) { throw ('MSVC environment initialization failed (exit code '+$process.ExitCode+')') }
} finally {
  $process.Dispose()
}

# Never replay the full runner environment into GITHUB_ENV. Preserve the
# installed toolchain's values for this explicit compiler/SDK-only allowlist.
$required=@('PATH','INCLUDE','LIB','LIBPATH','VCToolsInstallDir','WindowsSdkDir','VSCMD_ARG_HOST_ARCH','VSCMD_ARG_TGT_ARCH')
$allowed=$required+@(
  'VCINSTALLDIR','VCToolsVersion','VCToolsRedistDir','VSINSTALLDIR',
  'VisualStudioVersion','DevEnvDir','WindowsSDKVersion','WindowsSDKLibVersion',
  'WindowsSdkBinPath','WindowsSdkVerBinPath','WindowsLibPath',
  'UniversalCRTSdkDir','UCRTVersion','ExtensionSdkDir','NETFXSDKDir'
)
$values=@{}
foreach ($line in ($text -split "`r?`n")) {
  if ($line -match '^([^=]+)=(.*)$' -and $Matches[1] -in $allowed) {
    $name=$Matches[1];$value=$Matches[2]
    if ($values.ContainsKey($name) -or $value -match '[\r\n\x00]') { throw 'Malformed MSVC environment output' }
    $values[$name]=$value
  }
}
foreach ($name in $required) {
  if (!$values.ContainsKey($name) -or [string]::IsNullOrWhiteSpace($values[$name])) { throw ('MSVC environment missing required '+$name) }
}
foreach ($name in @('VSCMD_ARG_HOST_ARCH','VSCMD_ARG_TGT_ARCH')) {
  if ($values[$name] -ine 'x64') { throw 'Installed MSVC environment must target and host x64' }
}
# All validation precedes the single append. Do not print raw stdout/stderr,
# which may contain unrelated runner variables or credentials.
$output=foreach ($name in $allowed) {
  if ($values.ContainsKey($name)) { $name+'='+$values[$name]+"`n" }
}
[IO.File]::AppendAllText($EnvironmentFile,($output -join ''),[Text.UTF8Encoding]::new($false))
Write-Output 'Installed x64 MSVC environment initialized with compiler/SDK-only variables'
