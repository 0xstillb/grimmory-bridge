# Release Notes

## Grimmory Bridge 1.0.0

Initial GitHub-ready release of **Grimmory Bridge: OPF to Embedded and JSON**.

## Highlights

- Batch GUI for multi-folder processing
- Dry-run and write modes
- EPUB and PDF embedded metadata updates
- Grimmory `.metadata.json` sidecar generation
- Grimmory `.cover.jpg` normalization
- Compatibility summaries for KOReader, Grimmory, and Calibre
- Cleaner `Changes` and `Compatibility` log sections
- Detached GUI startup from the Windows `.bat` launcher

## Included In This Release

- `grimmory_bridge.bat`
- `setup_grimmory_bridge.bat`
- `opf_to_embedded_metadata.py`
- `opf_to_grimmory_json.py`
- `opf_to_embedded_metadata.bat`
- `requirements.txt`
- `README.md`
- `README_EMBEDDED_METADATA.md`
- tests for the metadata pipeline

## Recommended Download / Usage Flow

1. Download or clone the repository.
2. Run `setup_grimmory_bridge.bat` once to install Python dependencies.
3. On Windows, start with `grimmory_bridge.bat`.
4. Use dry-run first.
5. Review the `Changes`, `Compatibility`, and `JSON` sections.
6. Run again with write mode when the preview looks correct.

## Notes

- The launcher prefers `pythonw.exe` for GUI startup when available.
- A Windows release zip can be built with `build_release_package.ps1`.
- Sidecar naming follows Grimmory conventions:
  - `BookName.metadata.json`
  - `BookName.cover.jpg`
- The original external cover image is preserved.

## Validation Notes

- `py_compile` passes in the current workspace.
- Full `unittest` execution is currently blocked in this environment by temp-directory permission issues, so tests should be rerun in a normal local shell or CI environment before a tagged production release.
