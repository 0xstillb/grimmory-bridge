# Grimmory Bridge

**OPF to Embedded and JSON**

Grimmory Bridge scans folders for adjacent `.opf` files, embeds metadata into `.epub` and `.pdf` books, and writes Grimmory-compatible sidecar files in the same run.

It is designed for libraries where books and metadata share the same stem, for example:

- `Book 1.epub`
- `Book 1.pdf`
- `Book 1.opf`
- `Book 1.jpg`

## What It Does

- Reads metadata from adjacent `.opf` files
- Embeds metadata into EPUB and PDF files
- Writes Grimmory sidecars as `BookName.metadata.json`
- Writes Grimmory cover sidecars as `BookName.cover.jpg` when a cover exists
- Shows compatibility summaries for KOReader, Grimmory, and Calibre
- Supports dry-run and write modes
- Supports batch processing across multiple folders from the GUI

## Included Files

- `opf_to_embedded_metadata.py`: main app and GUI
- `opf_to_grimmory_json.py`: OPF parsing and Grimmory sidecar helpers
- `opf_to_embedded_metadata.bat`: Windows launcher
- `README_EMBEDDED_METADATA.md`: detailed metadata behavior notes
- `release.md`: release packaging and publishing notes

## Quick Start

### Windows GUI

Double-click `opf_to_embedded_metadata.bat` or run:

```powershell
.\opf_to_embedded_metadata.bat
```

With no arguments, Grimmory Bridge opens the GUI and lets you:

- add multiple folders
- preview changes before writing
- inspect `Changes`, `Compatibility`, and `JSON` output
- switch the log between `Compact` and `Detailed`

### Dry Run

```powershell
.\opf_to_embedded_metadata.bat --root "D:\Books"
```

### Write Changes

```powershell
.\opf_to_embedded_metadata.bat --root "D:\Books" --write
```

### Inspect One File

```powershell
.\opf_to_embedded_metadata.bat --inspect "D:\Books\Novel\Book.epub"
```

## Runtime Behavior

The batch launcher tries these runtimes in order:

1. Codex bundled `pythonw.exe` for GUI mode
2. Codex bundled `python.exe`
3. `py`
4. `pythonw`
5. `python`

CLI mode uses the normal console Python path. GUI mode prefers detached startup so the caller console is not left waiting on Tkinter.

## Metadata Mapping

From the OPF, Grimmory Bridge maps:

- `dc:title`
- `dc:creator`
- `dc:publisher`
- `dc:date`
- `dc:description`
- `dc:language`
- `dc:subject`
- ISBN identifiers
- Calibre and EPUB3 series metadata

For detailed field behavior, see `README_EMBEDDED_METADATA.md`.

## Output Files

When `--write` is used, Grimmory Bridge may create or update:

- embedded metadata inside `.epub`
- embedded metadata inside `.pdf`
- `BookName.metadata.json`
- `BookName.cover.jpg`

The original external cover file is preserved.

## Validation

Validated locally in this workspace with:

```powershell
python -m py_compile opf_to_embedded_metadata.py opf_to_grimmory_json.py
```

Full `unittest` execution is currently blocked in this environment by Windows temp-directory permission errors, so release users should rerun tests in a normal local shell if needed.

## Intended Use

This repo is meant to be ready to clone, download, and run on Windows for OPF-driven EPUB/PDF metadata embedding plus Grimmory JSON sidecar generation.
