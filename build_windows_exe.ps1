$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$version = "1.0.0"
$appName = "Grimmory Bridge"
$packageName = "Grimmory-Bridge-$version-windows-exe"
$distRoot = Join-Path $root "dist"
$bundleRoot = Join-Path $distRoot $appName
$packageRoot = Join-Path $distRoot $packageName
$zipPath = Join-Path $distRoot "$packageName.zip"
$generatedSpec = Join-Path $root "$appName.spec"

function Invoke-PythonCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$CommandParts,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $command = $CommandParts[0]
    $prefix = @()
    if ($CommandParts.Count -gt 1) {
        $prefix = $CommandParts[1..($CommandParts.Count - 1)]
    }

    & $command @prefix @Arguments
}

function Resolve-PythonCommand {
    $candidates = @()

    if ($env:GB_BUILD_PYTHON) {
        $candidates += , @($env:GB_BUILD_PYTHON)
    }

    $codexPython = Join-Path $HOME ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (Test-Path $codexPython) {
        $candidates += , @($codexPython)
    }

    $candidates += , @("py", "-3")
    $candidates += , @("py")
    $candidates += , @("python")

    foreach ($candidate in $candidates) {
        try {
            $resolved = Invoke-PythonCommand -CommandParts $candidate -Arguments @("-c", "import sys; print(sys.executable)")
            if ($LASTEXITCODE -eq 0 -and $resolved) {
                return $candidate
            }
        } catch {
        }
    }

    throw "Could not find a usable Python interpreter. Set GB_BUILD_PYTHON or install Python on PATH."
}

$pythonCommand = Resolve-PythonCommand
$pythonExecutable = (Invoke-PythonCommand -CommandParts $pythonCommand -Arguments @("-c", "import sys; print(sys.executable)")).Trim()

try {
    Invoke-PythonCommand -CommandParts $pythonCommand -Arguments @("-c", "import PyInstaller")
} catch {
    throw "PyInstaller is not installed for $pythonExecutable. Install it with: `"$pythonExecutable`" -m pip install pyinstaller"
}

try {
    Invoke-PythonCommand -CommandParts $pythonCommand -Arguments @(
        "-c",
        "import tkinter as tk; t = tk.Tcl(); print(t.eval('info library'))"
    ) | Out-Null
} catch {
    throw "Tkinter is not usable for $pythonExecutable. Set GB_BUILD_PYTHON to a Python runtime with working Tcl/Tk."
}

if (Test-Path $bundleRoot) {
    Remove-Item -LiteralPath $bundleRoot -Recurse -Force
}

if (Test-Path $packageRoot) {
    Remove-Item -LiteralPath $packageRoot -Recurse -Force
}

if (Test-Path $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

$buildArguments = @(
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--onedir",
    "--name",
    $appName,
    "opf_to_embedded_metadata.py"
)

Invoke-PythonCommand -CommandParts $pythonCommand -Arguments $buildArguments

if (Test-Path $generatedSpec) {
    Remove-Item -LiteralPath $generatedSpec -Force
}

New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null
Copy-Item -LiteralPath $bundleRoot -Destination (Join-Path $packageRoot $appName) -Recurse

$files = @(
    "README.md",
    "README_EMBEDDED_METADATA.md",
    "README_OPF_CONVERTER.md",
    "release.md"
)

foreach ($file in $files) {
    Copy-Item -LiteralPath (Join-Path $root $file) -Destination (Join-Path $packageRoot $file)
}

Compress-Archive -Path (Join-Path $packageRoot "*") -DestinationPath $zipPath -Force

Write-Host "Built executable bundle: $bundleRoot"
Write-Host "Created package: $zipPath"
