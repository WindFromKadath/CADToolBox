#requires -Version 7.2
[CmdletBinding()]
param(
    [ValidateSet('Staged','Index','History')][string]$Mode = 'Staged',
    [string]$CommitMessagePath,
    [string]$ReportPath
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$privacyArgs = @('-NoProfile', '-File', (Join-Path $repoRoot '.privacy-tools/Invoke-PrivacyCheck.ps1'),
    '-Repo', $repoRoot, '-Mode', $Mode, '-Policy', (Join-Path $repoRoot '.privacy-tools/privacy-policy.json'))
if ($CommitMessagePath) { $privacyArgs += @('-CommitMessagePath', $CommitMessagePath) }
if ($ReportPath) { $privacyArgs += @('-ReportPath', $ReportPath) }
& pwsh @privacyArgs
exit $LASTEXITCODE
