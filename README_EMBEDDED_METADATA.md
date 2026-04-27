# Grimmory Bridge Metadata Notes

This document describes the embedded metadata behavior used by **Grimmory Bridge: OPF to Embedded and JSON**.

The tool scans for adjacent `.opf` files and embeds their metadata directly into `.pdf` and `.epub` files so Grimmory and KOReader can read the metadata from the file itself.

It is designed for folders where files share the same stem, for example:

- `Book 1.pdf`
- `Book 1.opf`
- `Book 1.jpg`

or:

- `Book 1.epub`
- `Book 1.opf`
- `Book 1.jpg`

The `.jpg` is ignored by this tool. It is only there to show the common Calibre-style folder layout.

## What gets embedded

From the adjacent `.opf`, the script maps:

- `dc:title` -> PDF title / EPUB title
- `dc:creator` -> PDF author / EPUB creator
- `dc:publisher` -> PDF publisher / EPUB publisher
- `dc:date` -> PDF creation date / EPUB date
- `dc:description` -> PDF subject / EPUB description
- `dc:language` -> PDF language / EPUB language
- `dc:subject` -> PDF keywords + XMP subjects / EPUB subjects
- ISBN -> PDF XMP identifiers / EPUB identifier
- `calibre:series` + `calibre:series_index` -> PDF XMP Booklore fields / EPUB series metadata
- EPUB3 series metadata is also written as `belongs-to-collection` + `collection-type` + `group-position` for broader reader compatibility

## Double-click mode

If you double-click `opf_to_embedded_metadata.py` or run `opf_to_embedded_metadata.bat` with no arguments, it will:

- open the GUI
- let you add multiple folders in one picker step
- show a cleaner log window with KOReader / Grimmory / Calibre compatibility lines
- show a progress bar and percentage while the job runs
- write both embedded metadata and Grimmory `.metadata.json` sidecars in the same run

## Dry run

```powershell
py .\opf_to_embedded_metadata.py --root "D:\Books"
```

## Inspect one file

```powershell
py .\opf_to_embedded_metadata.py --inspect "D:\Books\Novel\Book.epub"
```

This prints a compatibility report for:

- KOReader
- Grimmory
- Calibre

## Write changes

```powershell
py .\opf_to_embedded_metadata.py --root "D:\Books" --write
```

This writes:

- embedded metadata into `.pdf` and `.epub`
- `.metadata.json` sidecars for Grimmory
- `.cover.jpg` copies for Grimmory when a cover image exists, while keeping the original cover file too

Sidecar naming follows Grimmory's `BookName.metadata.json` convention, so EPUB/PDF files that share the same stem also share the same sidecar file.

## Only PDF

```powershell
py .\opf_to_embedded_metadata.py --root "D:\Books" --ext pdf --write
```

## Only EPUB

```powershell
py .\opf_to_embedded_metadata.py --root "D:\Books" --ext epub --write
```

## Windows launcher

You can also use:

```powershell
.\opf_to_embedded_metadata.bat --root "D:\Books" --write
```

The batch file tries:

1. Codex bundled Python
2. `py`
3. `python`

## Notes

- Default mode is dry-run.
- The script only matches `.opf` to `.pdf` and `.epub`.
- It prefers a same-stem `.opf` such as `Book 1.opf`.
- If the `.opf` is named `metadata.opf`, it can also match that pattern when the book file is in the same folder.
- `.metadata.json` is written once per book stem, so same-stem EPUB/PDF siblings reuse the same Grimmory sidecar.
- When a cover image exists, the tool also creates a Grimmory-style `BookName.cover.jpg` next to the book without deleting the original cover file.
