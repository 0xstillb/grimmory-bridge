Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$userKey = [System.Environment]::GetEnvironmentVariable("TAURI_SIGNING_PRIVATE_KEY", "User")
if ([string]::IsNullOrWhiteSpace($userKey)) {
  throw "Missing user env TAURI_SIGNING_PRIVATE_KEY. Set it to your updater private key path or key contents."
}

$resolvedKey = $userKey
if (Test-Path -LiteralPath $userKey) {
  $resolvedKey = Get-Content -LiteralPath $userKey -Raw
}

$env:TAURI_SIGNING_PRIVATE_KEY = $resolvedKey
$userPassword = [System.Environment]::GetEnvironmentVariable("TAURI_SIGNING_PRIVATE_KEY_PASSWORD", "User")
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = if ([string]::IsNullOrWhiteSpace($userPassword)) { "" } else { $userPassword }
$env:CI = "true"

& "C:\Users\x_boa\AppData\Local\pnpm\pnpm.cmd" tauri build
exit $LASTEXITCODE
