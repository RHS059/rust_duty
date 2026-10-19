"""Narrow source and real-PowerShell application-selection regressions.

Only tiny temporary PATH fixtures and copies of the installed Windows command
shell are used. No Git, compiler, installer, Blender or game is launched.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parent
BEGIN = '# BEGIN single application selection'
END = '# END single application selection'


def resolver(name):
    text = (ROOT / name).read_text()
    start = text.index(BEGIN)
    body = text[start:text.index(END, start) + len(END)]
    lines = body.splitlines()
    # YAML's fixed run-block indent is removed without changing function code.
    if name.endswith('.yml'):
        lines = [lines[0]] + [line[10:] for line in lines[1:]]
    return '\n'.join(lines)


class ApplicationSelection(unittest.TestCase):
    def test_bootstrap_and_installer_use_identical_resolver(self):
        self.assertEqual(resolver('onehand-windows-proof.yml'),
                         resolver('install_official_rust.ps1'))

    def test_first_application_is_selected_before_source_validation(self):
        body = resolver('onehand-windows-proof.yml')
        self.assertIn('-CommandType Application -All -ErrorAction Stop | Select-Object -First 1', body)
        self.assertLess(body.index('Select-Object -First 1'), body.index('$command.Source'))
        self.assertIn('$command.Source -isnot [string]', body)
        self.assertIn('[string]::IsNullOrWhiteSpace($command.Source)', body)
        self.assertIn('Test-Path -LiteralPath $path -PathType Leaf', body)

    def test_all_affected_application_selectors_use_resolver(self):
        workflow = (ROOT / 'onehand-windows-proof.yml').read_text()
        installer = (ROOT / 'install_official_rust.ps1').read_text()
        self.assertIn("$git=Resolve-Application 'git.exe'", workflow)
        for name in ('rustup.exe', 'link.exe', 'cl.exe', 'lib.exe'):
            self.assertIn("Resolve-Application '" + name + "'", installer)
        self.assertEqual(workflow.count('Get-Command '), 2)  # Comment plus resolver.
        self.assertEqual(installer.count('Get-Command '), 2)

    def test_real_powershell_multiple_matches_spaces_and_invalid_sources(self):
        if os.name != 'nt':
            self.skipTest('Actual PowerShell execution is required on Windows CI')
        pwsh = shutil.which('pwsh')
        if not pwsh:
            self.fail('PowerShell is required for the Windows selection regression')
        body = resolver('onehand-windows-proof.yml')
        script = body + '\n' + textwrap.dedent(r'''
            $ErrorActionPreference='Stop'
            $root=$env:SELECTION_FIXTURE_ROOT
            $name='selection-'+[Guid]::NewGuid().ToString('N')+'.exe'
            $dirs=@('First Application Space','Second Application Space','Third Application Space') | ForEach-Object { Join-Path $root $_ }
            foreach ($dir in $dirs) {
              New-Item -ItemType Directory -Path $dir | Out-Null
              Copy-Item -LiteralPath $env:ComSpec -Destination (Join-Path $dir $name)
            }
            $originalPath=$env:PATH
            $env:PATH=($dirs -join [IO.Path]::PathSeparator)+[IO.Path]::PathSeparator+$env:PATH
            Set-Alias -Name $name -Value Write-Output
            $matches=@(Get-Command -Name $name -CommandType Application -All -ErrorAction Stop)
            if ($matches.Count -lt 3) { throw 'Multiple application fixture not established' }
            $first=Join-Path $dirs[0] $name
            $selected=@(Resolve-Application $name)
            if ($selected.Count -ne 1 -or $selected[0] -isnot [string] -or $selected[0] -ne $first) { throw 'First PATH match or spaced scalar path lost' }
            $output=& $selected[0] /d /c 'echo selected application argument with spaces'
            if ($LASTEXITCODE -ne 0 -or $output -ne 'selected application argument with spaces') { throw 'Call operator lost selected executable or spaced arguments' }
            $start=[Diagnostics.ProcessStartInfo]::new()
            $start.FileName=$selected[0];$start.UseShellExecute=$false;$start.RedirectStandardOutput=$true
            foreach ($arg in @('/d','/c','echo process start argument with spaces')) { $start.ArgumentList.Add($arg) }
            $process=[Diagnostics.Process]::Start($start)
            $actual=$process.StandardOutput.ReadToEnd().TrimEnd();$process.WaitForExit()
            if ($process.ExitCode -ne 0 -or $actual -ne 'process start argument with spaces') { throw 'ProcessStartInfo lost scalar executable or spaced arguments' }
            $process.Dispose()
            $env:PATH=($dirs[2..0] -join [IO.Path]::PathSeparator)+[IO.Path]::PathSeparator+$originalPath
            $reversed=@(Resolve-Application $name)
            if ($reversed.Count -ne 1 -or $reversed[0] -ne (Join-Path $dirs[2] $name)) { throw 'PATH precedence reversal ignored' }
            $missingRejected=$false
            try { Resolve-Application ('absent-'+[Guid]::NewGuid().ToString('N')+'.exe') | Out-Null } catch { $missingRejected=$true }
            if (!$missingRejected) { throw 'Missing command did not reject' }
            # Inject only discovery results to exercise malformed/invalid first
            # matches; the production resolver and literal leaf test are real.
            function Get-Command {
              param([string]$Name,[string]$CommandType,[switch]$All,[string]$ErrorAction)
              return $script:SelectionCandidates
            }
            $invalid=@(
              [pscustomobject]@{Source=''},
              [pscustomobject]@{Source='   '},
              [pscustomobject]@{Source=@($first,$first)},
              [pscustomobject]@{Source=(Join-Path $root 'absent.exe')},
              [pscustomobject]@{Source=$dirs[0]}
            )
            foreach ($bad in $invalid) {
              $script:SelectionCandidates=@($bad,[pscustomobject]@{Source=$first})
              $rejected=$false
              try { Resolve-Application 'fixture.exe' | Out-Null } catch { $rejected=$true }
              if (!$rejected) { throw 'Invalid first path silently fell back or was coerced' }
            }
            Write-Output 'application-selection-regression-passed'
        ''')
        with tempfile.TemporaryDirectory(prefix='application-selection-') as tmp:
            path = Path(tmp) / 'regression.ps1'
            path.write_text(script, encoding='utf-8')
            env = dict(os.environ, SELECTION_FIXTURE_ROOT=tmp)
            result = subprocess.run([pwsh, '-NoLogo', '-NoProfile', '-NonInteractive',
                                     '-File', str(path)], env=env, capture_output=True,
                                    text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('application-selection-regression-passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
