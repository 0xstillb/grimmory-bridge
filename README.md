# Grimmory Bridge

**OPF to Embedded Metadata and JSON Sidecar**

Grimmory Bridge reads `.opf` metadata files and embeds them directly into `.epub` and `.pdf` books, then writes Grimmory-compatible sidecar files in the same run. It is designed for Calibre-style libraries where books and metadata share the same stem.

## Why This Exists

### The Problem

Book management apps like **Grimmory** extract metadata by reading what is embedded inside the file. Calibre stores rich metadata in external `.opf` sidecar files but does not always write it back into the book files themselves. This leaves a gap: the OPF knows the series name, ISBN, and subjects, but the PDF or EPUB the reader opens has none of that embedded.

### The PDF Stale-XMP Problem

PDF editors (Foxit PhantomPDF, Adobe Acrobat, etc.) perform **incremental saves** that append new objects to the file without removing old ones. Each save can leave behind orphaned XMP Metadata stream objects. A single PDF can end up with **multiple XMP packets** inside it, only one of which is referenced by the document catalog.

When a tool like pypdf writes new XMP metadata, it correctly updates the catalog-referenced object. But `clone_document_from_reader()` faithfully copies every object in the file, including the stale ones. PDF readers like **PDFium** (used by Grimmory's Java backend via PDFium4j) may read a stale XMP object instead of the catalog-referenced one, causing fields like **Series Name** and **ISBN** to appear empty even though they exist in the correct XMP packet.

**Grimmory Bridge v1.1.0** fixes this by **nullifying all orphaned XMP Metadata objects** before writing, so the PDF contains exactly one authoritative XMP packet.

## How It Works

```
                         Grimmory Bridge
                         ===============

  Calibre Library                              Grimmory / KOReader
  ---------------                              --------------------

  Book.opf ──────┐
                 │
  Book.epub ─────┤       ┌─────────────────┐
                 ├──────>│  Parse OPF       │
  Book.pdf ──────┤       │  metadata        │
                 │       └────────┬─────────┘
  Book.jpg ──────┘                │
                                  v
                     ┌────────────────────────┐
                     │  For each .epub / .pdf  │
                     └────────────┬────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    v                           v
          ┌──────────────────┐       ┌───────────────────┐
          │   EPUB: update   │       │   PDF: remove     │
          │   OPF + Dublin   │       │   stale XMP       │
          │   Core inside    │       │   objects, write   │
          │   the ZIP        │       │   clean XMP with   │
          │                  │       │   all fields       │
          └──────────────────┘       └───────────────────┘
                    │                           │
                    └─────────────┬─────────────┘
                                  v
                     ┌────────────────────────┐
                     │  Write sidecars:       │
                     │  Book.metadata.json    │
                     │  Book.cover.jpg        │
                     └────────────────────────┘
                                  │
                                  v
                     ┌────────────────────────┐
                     │  Grimmory backend      │
                     │  reads embedded XMP    │
                     │  -> Series, ISBN,      │
                     │     subjects all       │
                     │     visible            │
                     └────────────────────────┘
```

## Metadata Mapping

From the OPF, Grimmory Bridge maps:

| OPF Field | PDF Target | EPUB Target |
|---|---|---|
| `dc:title` | Info Dict + XMP | `<dc:title>` |
| `dc:creator` | Info Dict + XMP | `<dc:creator>` |
| `dc:publisher` | XMP Dublin Core | `<dc:publisher>` |
| `dc:date` | Info Dict + XMP | `<dc:date>` |
| `dc:description` | Info Dict (Subject) + XMP | `<dc:description>` |
| `dc:language` | XMP Dublin Core | `<dc:language>` |
| `dc:subject` | Keywords + XMP Subjects | `<dc:subject>` |
| ISBN | XMP Identifier (Bag) | `<dc:identifier>` |
| `calibre:series` | XMP Calibre + Booklore | `belongs-to-collection` |
| `calibre:series_index` | XMP Calibre + Booklore | `group-position` |

For detailed field behavior, see [README_EMBEDDED_METADATA.md](README_EMBEDDED_METADATA.md).

## Quick Start

### Requirements

- Windows with Python 3 available as `py` or `python`
- Dependencies from `requirements.txt` (just `pypdf`)

### Install

```powershell
.\setup_grimmory_bridge.bat
```

### Run the GUI

```powershell
.\grimmory_bridge.bat
```

The GUI lets you add multiple folders, preview changes before writing, and inspect `Changes`, `Compatibility`, and `JSON` output.

### Dry Run (CLI)

```powershell
.\grimmory_bridge.bat --root "D:\Books"
```

### Write Changes

```powershell
.\grimmory_bridge.bat --root "D:\Books" --write
```

### Inspect One File

```powershell
.\grimmory_bridge.bat --inspect "D:\Books\Novel\Book.epub"
```

## Windows EXE

A standalone `.exe` package is available on the [Releases](https://github.com/0xstillb/grimmory-bridge/releases) page. It does not require a separate Python install.

After extracting:

1. Open the `Grimmory Bridge` folder.
2. Run `Grimmory Bridge.exe`.
3. Keep the `_internal` folder beside the `.exe`.

## Included Files

| File | Purpose |
|---|---|
| `opf_to_embedded_metadata.py` | Main app and GUI |
| `opf_to_grimmory_json.py` | OPF parsing and sidecar helpers |
| `grimmory_bridge.bat` | Windows launcher |
| `setup_grimmory_bridge.bat` | Dependency installer |
| `opf_to_embedded_metadata.bat` | Alternative launcher |
| `build_release_package.ps1` | Build portable zip |
| `build_windows_exe.ps1` | Build standalone exe zip |

## Building Release Packages

### Portable (requires Python)

```powershell
.\build_release_package.ps1
```

### Standalone EXE

```powershell
.\build_windows_exe.ps1
```

If auto-detection picks the wrong Python:

```powershell
$env:GB_BUILD_PYTHON = 'C:\path\to\python.exe'
.\build_windows_exe.ps1
```

## Runtime Behavior

The batch launcher tries these runtimes in order:

1. Codex bundled `pythonw.exe` (GUI mode)
2. Codex bundled `python.exe`
3. `py`
4. `pythonw`
5. `python`

## Changelog

### v1.1.0

- Fixed PDF stale XMP metadata bug that caused Grimmory backend to miss Series Name and ISBN
- Added `_remove_stale_xmp_objects()` to nullify orphaned `/Type /Metadata` stream objects before writing
- PDFs now contain exactly one authoritative XMP packet referenced by the document catalog

### v1.0.0

- Initial release with batch GUI, dry-run/write modes, EPUB/PDF embedding, and Grimmory sidecar generation
