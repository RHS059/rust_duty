#Requires -Version 7.2
<#
.SYNOPSIS
Stages a pinned, app-local Windows OpenGL reference without installing a driver.
.DESCRIPTION
Validates official package and member hashes, x64 PE imports and their complete
app-local closure before atomically publishing a new output directory. It does
not run DLLs, launch the game, change PATH/registry/security, or install a driver.
PackageDirectory is an optional read-only offline source; missing files there
are errors rather than permission to download. PowerShell 7 and a tar supporting
Zstandard are required. Staging is also testable on Linux; rendering is Windows.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Manifest,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [string]$PackageDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-Hash([string]$Path, [string]$Expected) {
    if ($Expected -cnotmatch '^[0-9a-f]{64}$' -or
        (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ine $Expected) {
        throw "SHA256 mismatch: $Path"
    }
}
function Assert-Member([string]$Name) {
    if ($Name -cnotmatch '^ucrt64/(bin|share/licenses)/[A-Za-z0-9+_.\-/]+$' -or
        $Name.Contains('//') -or ($Name.Split('/') -contains '..') -or
        ($Name.Split('/') -contains '.') -or $Name.EndsWith('/')) {
        throw "Unsafe archive member: $Name"
    }
}
function Test-WindowsImport([string]$Name) {
    return $Name -imatch '^(api-ms-win-(core|crt)-[a-z0-9-]+|kernel32|user32|gdi32|ntdll|advapi32|shell32|ole32|ws2_32|version|bcrypt|ucrtbase)\.dll$'
}
function Assert-SameNames($Actual, $Expected, [string]$Context) {
    $a = @($Actual | ForEach-Object { $_.ToLowerInvariant() } | Sort-Object)
    $e = @($Expected | ForEach-Object { $_.ToLowerInvariant() } | Sort-Object)
    if ($a.Count -ne $e.Count -or (Compare-Object -ReferenceObject $a -DifferenceObject $e)) {
        throw "Name inventory differs: $Context"
    }
}

$manifestPath = [IO.Path]::GetFullPath($Manifest)
$output = [IO.Path]::GetFullPath($OutputDirectory).TrimEnd([IO.Path]::DirectorySeparatorChar)
if (Test-Path -LiteralPath $output) { throw 'OutputDirectory already exists; nothing will be overwritten.' }
$parent = [IO.Path]::GetDirectoryName($output)
if (!$parent -or !(Test-Path -LiteralPath $parent -PathType Container)) {
    throw 'The output parent directory must already exist.'
}
if ((Get-Item -LiteralPath $manifestPath).Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw 'Manifest must be a regular file, not a link.'
}
$manifestBytes = [IO.File]::ReadAllBytes($manifestPath)
$manifestHash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
$lock = [Text.Encoding]::UTF8.GetString($manifestBytes) | ConvertFrom-Json -Depth 32
if ($lock.schema -cne 'rust-duty-windows-gl-reference/v1' -or $lock.architecture -cne 'x86_64' -or
    $lock.packages -isnot [array] -or $lock.dlls -isnot [array] -or
    $lock.packages.Count -lt 1 -or $lock.packages.Count -gt 64 -or
    $lock.dlls.Count -lt 2 -or $lock.dlls.Count -gt 128 -or $lock.dll_count -ne $lock.dlls.Count -or
    $lock.runtime_environment.GALLIUM_DRIVER -cne 'llvmpipe' -or
    $lock.runtime_environment.LIBGL_ALWAYS_SOFTWARE -cne 'true') {
    throw 'Unsupported or invalid Windows GL reference manifest.'
}
$packages = @{}
foreach ($package in $lock.packages) {
    if ($package.name -cnotmatch '^mingw-w64-ucrt-x86_64-[a-z0-9+_-]+$' -or
        $packages.ContainsKey($package.name) -or $package.sha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw 'Invalid or duplicate pinned package.'
    }
    $uri = [Uri]$package.url
    if ($uri.Scheme -cne 'https' -or $uri.Host -cne 'repo.msys2.org' -or !$uri.IsDefaultPort -or
        $uri.UserInfo -or $uri.Query -or $uri.Fragment -or
        $uri.AbsolutePath -cnotmatch '^/mingw/ucrt64/[^/]+\.pkg\.tar\.zst$' -or
        [Uri]::UnescapeDataString([IO.Path]::GetFileName($uri.AbsolutePath)) -cne $package.archive -or
        $package.archive -cne ($package.name + '-' + $package.version + '-any.pkg.tar.zst')) {
        throw "Package must use its pinned official MSYS2 UCRT64 URL: $($package.name)"
    }
    if ($package.licenses -isnot [array] -or $package.licenses.Count -eq 0) {
        throw "Pinned license files are required: $($package.name)"
    }
    foreach ($license in $package.licenses) {
        Assert-Member $license.member
        if (!$license.member.StartsWith('ucrt64/share/licenses/') -or
            $license.sha256 -cnotmatch '^[0-9a-f]{64}$' -or $license.size -le 0) {
            throw 'Invalid pinned license entry.'
        }
    }
    $packages[$package.name] = $package
}
$dlls = @{}
foreach ($dll in $lock.dlls) {
    Assert-Member $dll.member
    if ($dll.dll -cnotmatch '^[A-Za-z0-9+_.-]+\.dll$' -or $dlls.ContainsKey($dll.dll) -or
        (Test-WindowsImport $dll.dll) -or $dll.dll -imatch 'vulkan|^dxgi\.|^d3d' -or
        !$packages.ContainsKey($dll.package) -or $dll.member -cne ('ucrt64/bin/' + $dll.dll) -or
        $dll.sha256 -cnotmatch '^[0-9a-f]{64}$' -or $dll.size -le 0 -or
        $dll.imports -isnot [array]) {
        throw "Invalid, duplicate, or disallowed DLL entry: $($dll.dll)"
    }
    $dlls[$dll.dll] = $dll
}
if (!$dlls.ContainsKey('opengl32.dll') -or !$dlls.ContainsKey('libgallium_wgl.dll') -or
    ($lock.dlls | Measure-Object -Property size -Sum).Sum -ne $lock.dll_total_bytes) {
    throw 'The pinned GL entrypoints or total DLL size are invalid.'
}
foreach ($package in $lock.packages) {
    if (@($lock.dlls | Where-Object { $_.package -ceq $package.name }).Count -eq 0) {
        throw "Unused package in runtime manifest: $($package.name)"
    }
}
foreach ($dll in $lock.dlls) {
    foreach ($import in $dll.imports) {
        if (!$dlls.ContainsKey($import) -and !(Test-WindowsImport $import)) {
            throw "Unresolved pinned import: $($dll.dll) -> $import"
        }
    }
}

# Read PE headers as data only. Reject unsupported delayed imports instead of
# silently omitting them from the dependency closure.
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Text;
using System.Collections.Generic;
public static class RustDutyGlReferencePe {
    public static string[] Imports(string path) {
        byte[] b = File.ReadAllBytes(path);
        Action<long,long> check = (p,n) => { if(p<0 || n<0 || p>b.LongLength-n) throw new InvalidDataException("Truncated PE data"); };
        Func<long,ushort> u16 = p => { check(p,2); return BitConverter.ToUInt16(b,(int)p); };
        Func<long,uint> u32 = p => { check(p,4); return BitConverter.ToUInt32(b,(int)p); };
        if(u16(0)!=0x5a4d) throw new InvalidDataException("Missing DOS header");
        long pe=u32(60), opt=pe+24;
        if(u32(pe)!=0x4550 || u16(pe+4)!=0x8664 || (u16(pe+22)&0x2000)==0 || u16(opt)!=0x20b)
            throw new InvalidDataException("Expected an x86-64 PE32+ DLL");
        int count=u16(pe+6), optionalSize=u16(pe+20);
        if(count<1 || count>96 || optionalSize<224 || u32(opt+108)<14)
            throw new InvalidDataException("Unsupported PE directory layout");
        check(opt,optionalSize);
        long sections=opt+optionalSize; check(sections,count*40L);
        Func<uint,long> offset = rva => {
            if(rva<u32(opt+60)) { check(rva,1); return rva; }
            for(int i=0;i<count;i++) {
                long s=sections+i*40L; uint va=u32(s+12), rawSize=u32(s+16), raw=u32(s+20);
                if(rva>=va && (ulong)rva-va<rawSize) { long p=raw+(long)rva-va; check(p,1); return p; }
            }
            throw new InvalidDataException("PE RVA is outside raw sections");
        };
        if(u32(opt+112+13*8)!=0 || u32(opt+116+13*8)!=0)
            throw new InvalidDataException("Delayed imports require a new reviewed manifest/parser");
        uint importRva=u32(opt+120), importSize=u32(opt+124);
        if(importRva==0 || importSize<20) throw new InvalidDataException("Missing import directory");
        long first=offset(importRva); check(first,importSize);
        var names=new List<string>(); bool terminated=false;
        for(uint cursor=0; cursor<=importSize-20; cursor+=20) {
            long d=first+cursor; check(d,20);
            if(u32(d)==0 && u32(d+4)==0 && u32(d+8)==0 && u32(d+12)==0 && u32(d+16)==0) { terminated=true; break; }
            long p=offset(u32(d+12)); int n=0;
            while(n<260) { check(p+n,1); if(b[p+n]==0) break; if(b[p+n]>127) throw new InvalidDataException("Non-ASCII import name"); n++; }
            if(n==0 || n==260) throw new InvalidDataException("Invalid import name");
            names.Add(Encoding.ASCII.GetString(b,(int)p,n));
        }
        if(!terminated || names.Count==0) throw new InvalidDataException("Unterminated import directory");
        return names.ToArray();
    }
}
'@

$tarName = if ($IsWindows) { 'tar.exe' } else { 'tar' }
$tar = (Get-Command $tarName -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$offline = if ($PackageDirectory) { [IO.Path]::GetFullPath($PackageDirectory) } else { $null }
if ($offline -and !(Test-Path -LiteralPath $offline -PathType Container)) {
    throw 'PackageDirectory must be an existing, read-only source of pinned archives.'
}
$temporary = Join-Path $parent ('.gl-reference-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
$payload = Join-Path $temporary 'runtime'
$downloads = Join-Path $temporary 'packages'
$extracts = Join-Path $temporary 'extract'
try {
    New-Item -ItemType Directory -Path $payload, $downloads, $extracts | Out-Null
    foreach ($package in $lock.packages) {
        $archive = if ($offline) { Join-Path $offline $package.archive } else { Join-Path $downloads $package.archive }
        if ($offline) {
            if (!(Test-Path -LiteralPath $archive -PathType Leaf) -or
                (Get-Item -LiteralPath $archive).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Missing or linked offline package: $($package.archive)"
            }
        } else {
            Invoke-WebRequest -Uri $package.url -OutFile $archive -MaximumRedirection 0 -TimeoutSec 120
        }
        Assert-Hash $archive $package.sha256
        $selected = @($lock.dlls | Where-Object { $_.package -ceq $package.name })
        $members = @($selected.member) + @($package.licenses.member)
        $listed = @(& $tar -tf $archive)
        if ($LASTEXITCODE -ne 0) { throw 'tar must support .pkg.tar.zst; package listing failed.' }
        foreach ($member in $members) {
            if (@($listed | Where-Object { $_ -ceq $member }).Count -ne 1) {
                throw "Missing or duplicate selected archive member: $member"
            }
        }
        $extract = Join-Path $extracts $package.name
        New-Item -ItemType Directory -Path $extract | Out-Null
        & $tar -xf $archive -C $extract -- @members
        if ($LASTEXITCODE -ne 0) { throw "Selected-member extraction failed: $($package.name)" }
        foreach ($entry in (@($selected) + @($package.licenses))) {
            $source = Join-Path $extract $entry.member
            $item = Get-Item -LiteralPath $source
            if ($item.PSIsContainer -or $item.Attributes -band [IO.FileAttributes]::ReparsePoint -or
                $item.Length -ne $entry.size) { throw "Invalid extracted file: $($entry.member)" }
            Assert-Hash $source $entry.sha256
        }
        foreach ($dll in $selected) {
            $source = Join-Path $extract $dll.member
            $actualImports = [RustDutyGlReferencePe]::Imports($source)
            Assert-SameNames $actualImports $dll.imports $dll.dll
            Copy-Item -LiteralPath $source -Destination (Join-Path $payload $dll.dll)
        }
        foreach ($license in $package.licenses) {
            $destination = Join-Path (Join-Path $payload 'licenses') $license.member.Substring('ucrt64/share/licenses/'.Length)
            New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($destination)) -Force | Out-Null
            if (Test-Path -LiteralPath $destination) { throw "Duplicate staged license path: $destination" }
            Copy-Item -LiteralPath (Join-Path $extract $license.member) -Destination $destination
        }
        Remove-Item -LiteralPath $extract -Recurse -Force
    }
    # Every DLL must be reachable from opengl32, not merely named in the lock.
    $seen = @{}; $pending = [Collections.Generic.Stack[string]]::new(); $pending.Push('opengl32.dll')
    $systemImports = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    while ($pending.Count -gt 0) {
        $name = $pending.Pop()
        if ($seen.ContainsKey($name)) { continue }
        $seen[$name] = $true
        $imports = [RustDutyGlReferencePe]::Imports((Join-Path $payload $dlls[$name].dll))
        foreach ($import in $imports) {
            if ($dlls.ContainsKey($import)) { $pending.Push($import) }
            elseif (Test-WindowsImport $import) { [void]$systemImports.Add($import) }
            else { throw "Unresolved actual import: $name -> $import" }
        }
    }
    Assert-SameNames @($seen.Keys) @($dlls.Keys) 'reachable DLL closure'
    Assert-SameNames @($systemImports) $lock.windows_supplied_imports 'Windows-supplied imports'
    Assert-SameNames @((Get-ChildItem -LiteralPath $payload -File -Filter '*.dll').Name) @($dlls.Keys) 'staged DLL inventory'
    foreach ($dll in $lock.dlls) { Assert-Hash (Join-Path $payload $dll.dll) $dll.sha256 }
    [IO.File]::WriteAllBytes((Join-Path $payload 'windows_gl_reference_lock.json'), $manifestBytes)
    $receipt = [ordered]@{ schema='rust-duty-windows-gl-reference-staging/v1'; manifest_sha256=$manifestHash;
        mesa_version=$lock.mesa_version; dll_count=$dlls.Count; dll_total_bytes=$lock.dll_total_bytes;
        package_source= $(if ($offline) { 'offline-pinned-archives' } else { 'official-msys2-https' });
        native_windows_verified=$false; rendering_executed=$false }
    $receipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $payload 'staging-receipt.json') -Encoding utf8NoBOM
    # Directory.Move refuses an existing destination, including a racing writer.
    [IO.Directory]::Move($payload, $output)
    Write-Output "Staged $($dlls.Count) verified app-local DLLs at $output. No native rendering was run."
} finally {
    # Only our newly generated temporary tree is disposable. Existing paths,
    # the optional package source and a successfully published output are kept.
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
