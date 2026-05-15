# Grimmory Bridge

Desktop bridge for Grimmory metadata workflows.

Grimmory Bridge reads OPF metadata, previews diffs, writes embedded metadata for EPUB/PDF, and writes Grimmory sidecars (`.metadata.json`, `.cover.jpg`) in one flow.

## Highlights

- Tauri desktop app (Rust + React + TypeScript)
- Python sidecar RPC runtime for metadata processing
- AES-encrypted PDF write support (decrypt -> write -> optional re-encrypt)
- Dry-run first workflow with halt/retry/rollback UX
- Updater-ready release artifacts with signatures

## Current Release Line

- Repository: `https://github.com/0xstillb/grimmory-bridge`
- Updater endpoint: `https://github.com/0xstillb/grimmory-bridge/releases/latest/download/latest.json`

## Local Development

### Prerequisites

- Node 20+
- pnpm 10+
- Rust stable toolchain
- Python 3.11+

### Install

```powershell
pnpm install
python -m pip install -r requirements.txt
```

### Run dev app

```powershell
pnpm tauri dev
```

### Build web UI

```powershell
pnpm build
```

## Signed Desktop Build (Local Windows)

One-time key setup:

1. Generate updater keys:
   - `pnpm tauri signer generate -w C:\Users\<you>\AppData\Roaming\grimmory-bridge\updater.key`
2. Set user env:
   - `TAURI_SIGNING_PRIVATE_KEY` = key file path (or key content)
   - `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` = password (optional)

Build:

```powershell
pnpm build:signed
```

Artifacts:

- `src-tauri/target/release/bundle/nsis/*.exe`
- `src-tauri/target/release/bundle/msi/*.msi`
- matching `.sig` files

## CI/CD (#6.4)

Workflow: `.github/workflows/release.yml`

- Trigger: pushed tag `v*`
- Matrix:
  - macOS `universal-apple-darwin`
  - Windows `x86_64-pc-windows-msvc`
- Output:
  - `.dmg` and `.msi`/`.exe` artifacts
  - updater signatures
  - `latest.json` updater manifest (uploaded to GitHub Release)

Required GitHub secrets:

- `TAURI_SIGNING_PRIVATE_KEY`
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` (optional if key has no password)

## Project Layout

- `src/`: React UI
- `src-tauri/`: Tauri host app
- `python/grimmory_bridge/`: RPC sidecar implementation
- `scripts/build-sidecar.py`: cross-platform sidecar build helper for CI
- `scripts/build-signed.ps1`: local signed build helper

## Notes

- Existing legacy batch scripts are kept for compatibility with older Python-first workflows.
- For release automation, prefer the Tauri pipeline in this repository.
