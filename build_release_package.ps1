$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$version = "1.1.0"
$packageName = "Grimmory-Bridge-$version-windows"
$distRoot = Join-Path $root "dist"
$packageRoot = Join-Path $distRoot $packageName
$zipPath = Join-Path $distRoot "$packageName.zip"

if (Test-Path $packageRoot) {
    Remove-Item -LiteralPath $packageRoot -Recurse -Force
}

if (Test-Path $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null

$files = @(
    "grimmory_bridge.bat",
    "setup_grimmory_bridge.bat",
    "opf_to_embedded_metadata.bat",
    "opf_to_embedded_metadata.py",
    "opf_to_grimmory_json.py",
    "requirements.txt",
    "README.md",
    "README_EMBEDDED_METADATA.md",
    "README_OPF_CONVERTER.md",
    "release.md"
)

foreach ($file in $files) {
    Copy-Item -LiteralPath (Join-Path $root $file) -Destination (Join-Path $packageRoot $file)
}

Compress-Archive -Path (Join-Path $packageRoot "*") -DestinationPath $zipPath -Force
Write-Host "Created package: $zipPath"
