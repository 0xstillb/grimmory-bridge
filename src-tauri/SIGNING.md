# Tauri Updater Signing (Windows)

This project is configured to sign updater artifacts during `tauri build`.

## One-time setup

1. Generate keys (private key outside repo):
   - Private key: `C:\Users\x_boa\AppData\Roaming\grimmory-bridge\updater.key`
   - Public key: `C:\Users\x_boa\AppData\Roaming\grimmory-bridge\updater.key.pub`
2. Persist user env:
   - `TAURI_SIGNING_PRIVATE_KEY` = `C:\Users\x_boa\AppData\Roaming\grimmory-bridge\updater.key`
   - Optional: `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` (if your key is password-protected)

## Build command

Use:

```powershell
pnpm build:signed
```

`scripts/build-signed.ps1` will:

- Resolve `TAURI_SIGNING_PRIVATE_KEY` from user env
- If env is a file path, read key contents securely at runtime
- Set `CI=true` to avoid interactive password prompts
- Run `pnpm tauri build`

## Output

Signed installer artifacts are produced under:

- `src-tauri/target/release/bundle/nsis/*.exe`
- `src-tauri/target/release/bundle/msi/*.msi`
- plus matching `.sig` files for updater
