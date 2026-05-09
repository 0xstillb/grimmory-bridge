# Release Notes

## Grimmory Bridge 1.1.0

### Fixed

- PDF stale XMP metadata bug: PDFs edited by tools like Foxit PhantomPDF accumulate orphaned XMP Metadata stream objects through incremental saves. PDFium4j (used by Grimmory's Java backend) could read a stale empty XMP object instead of the catalog-referenced one, causing Series Name and ISBN to appear empty.
- Added `_remove_stale_xmp_objects()` that nullifies all `/Type /Metadata` stream objects not referenced by the PDF catalog before writing new XMP.
- PDFs processed by Grimmory Bridge now contain exactly one authoritative XMP packet.

### Download Options

- `Grimmory-Bridge-1.1.0-windows.zip`: portable Python-based package
- `Grimmory-Bridge-1.1.0-windows-exe.zip`: bundled Windows executable (no Python required)

## Grimmory Bridge 1.0.0

### Highlights

- Batch GUI for multi-folder processing
- Dry-run and write modes
- EPUB and PDF embedded metadata updates
- Grimmory `.metadata.json` sidecar generation
- Grimmory `.cover.jpg` normalization
- Compatibility summaries for KOReader, Grimmory, and Calibre
- Detached GUI startup from the Windows `.bat` launcher

### Download Options

- `Grimmory-Bridge-1.0.0-windows.zip`: portable Python-based package
- `Grimmory-Bridge-1.0.0-windows-exe.zip`: bundled Windows executable package
