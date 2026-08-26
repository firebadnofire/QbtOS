#requires -Version 5.1

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd([IO.Path]::DirectorySeparatorChar)
$repositoryPrefix = $repositoryRoot + [IO.Path]::DirectorySeparatorChar
$targets = @(
    (Join-Path $repositoryRoot 'output\imager-ui'),
    (Join-Path $repositoryRoot 'output\imager-ui-build'),
    (Join-Path $repositoryRoot 'output\imager-ui-release'),
    (Join-Path $repositoryRoot 'output\imager-ui-download'),
    (Join-Path $repositoryRoot 'build-scripts\imager-ui\bin'),
    (Join-Path $repositoryRoot 'build-scripts\imager-ui\obj')
)

foreach ($target in $targets) {
    $resolvedTarget = [IO.Path]::GetFullPath($target).TrimEnd([IO.Path]::DirectorySeparatorChar)
    if (-not $resolvedTarget.StartsWith($repositoryPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside the repository: $resolvedTarget"
    }
    if (Test-Path -LiteralPath $resolvedTarget) {
        Write-Host "Removing $resolvedTarget"
        Remove-Item -LiteralPath $resolvedTarget -Recurse -Force -ErrorAction Stop
    } else {
        Write-Host "Already clean: $resolvedTarget"
    }
}
