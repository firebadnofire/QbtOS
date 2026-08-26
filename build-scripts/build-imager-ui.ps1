#requires -Version 5.1

[CmdletBinding()]
param(
    [ValidateSet('win-x64', 'win-arm64')]
    [string] $Runtime = 'win-x64'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($env:OS -ne 'Windows_NT') {
    throw 'The qbtOS imager GUI can only be built on Windows.'
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$project = Join-Path $PSScriptRoot 'imager-ui\QbtOs.Imager.Ui.csproj'
$publishDirectory = Join-Path $repositoryRoot 'output\imager-ui'
$buildDirectory = Join-Path $repositoryRoot 'output\imager-ui-build'
$dotnet = Get-Command dotnet.exe, dotnet -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1

if (-not $dotnet) {
    throw 'Building the qbtOS imager GUI requires the .NET 8 SDK. Install it from https://dotnet.microsoft.com/download/dotnet/8.0.'
}

$sdkVersions = @(& $dotnet.Source --list-sdks)
if ($LASTEXITCODE -ne 0) { throw "dotnet --list-sdks failed with exit code $LASTEXITCODE." }
if (-not ($sdkVersions | Where-Object { $_ -match '^8\.' })) {
    throw "Building the qbtOS imager GUI requires the .NET 8 SDK; installed SDKs: $($sdkVersions -join ', ')."
}

New-Item -ItemType Directory -Path $publishDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $buildDirectory -Force | Out-Null

Write-Host "Publishing qbtOS Imager for $Runtime..."
& $dotnet.Source publish $project `
    --configuration Release `
    --runtime $Runtime `
    --self-contained true `
    -p:PublishSingleFile=true `
    -p:EnableWindowsTargeting=true `
    --output $publishDirectory `
    "-p:BaseOutputPath=$buildDirectory\bin\" `
    "-p:BaseIntermediateOutputPath=$buildDirectory\obj\"
if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed with exit code $LASTEXITCODE." }

$executable = Join-Path $publishDirectory 'qbtOS Imager.exe'
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "The build completed without producing the expected executable: $executable"
}

Write-Host "Built: $executable" -ForegroundColor Green
