# Build & Release Notes

## Python sidecar (`#6.1`)

Build the sidecar binary with PyInstaller:

```powershell
python python/build.py --triple host
```

Supported output naming triples:

- `x86_64-pc-windows-msvc`
- `x86_64-apple-darwin`
- `aarch64-apple-darwin`

`python/build.py` always builds on the current host and writes binaries to:

- `src-tauri/binaries/grimmory-bridge-py-<triple>[.exe]`

Note: PyInstaller does not cross-compile. Build each target on its matching OS/arch host.

## Tauri updater (`#6.3`)

Updater config is enabled in `src-tauri/tauri.conf.json`:

- `bundle.createUpdaterArtifacts = true`
- `plugins.updater.endpoints = ["https://github.com/0xstillb/grimmory-bridge/releases/latest/download/latest.json"]`
- `plugins.updater.pubkey = "<real minisign public key>"`

The updater plugin is enabled at runtime through `tauri_plugin_updater::Builder::new().build()`.

Generate updater key pair:

```powershell
pnpm tauri signer generate -- --ci --force --write-keys ~/.tauri/grimmory-bridge.key
```

Use:

- Public key (`*.pub`) -> copy the key content into `src-tauri/tauri.conf.json` `plugins.updater.pubkey`.
- Private key (`*.key`) -> keep secret; use only in signing pipelines via:
  - `TAURI_SIGNING_PRIVATE_KEY_PATH=~/.tauri/grimmory-bridge.key`
  - optional `TAURI_SIGNING_PRIVATE_KEY_PASSWORD=<password>`

Never commit private keys to the repository.

## Code signing notes (`#6.2`)

### macOS

- Sign with Developer ID Application certificate.
- Notarize artifacts via `notarytool`.
- Staple notarization ticket before distribution.

### Windows

- Sign installers with Authenticode certificate (EV recommended).
- Keep certificate and timestamp configuration in CI secrets.

## CI build matrix (`#6.4`)

Workflow: `.github/workflows/build.yml`

- Matrix OS: `macos-latest`, `windows-latest`
- Steps:
  - setup Python + Rust + Node/pnpm
  - `python/build.py --triple host`
  - `pytest`
  - `pnpm tauri build`
  - upload `src-tauri/target/release/bundle/**` and sidecar binaries
