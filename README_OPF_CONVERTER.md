# Grimmory Bridge Sidecar-Only Notes

This document describes the sidecar-only helper flow for Grimmory Bridge.

The script scans a Calibre-style library for `metadata.opf` files and creates Grimmory-style sidecar JSON files next to each book file.

## Double-click mode

If you open `opf_to_grimmory_json.py` by double-clicking it, the script will:

- open a folder picker
- ask whether to do a dry-run or actually write files
- optionally ask whether to overwrite existing `.metadata.json` files
- show a simple log window with the results

## Dry run

```bash
python3 opf_to_grimmory_json.py --root /media/QNAP_Books/Books
```

## Write files

```bash
python3 opf_to_grimmory_json.py --root /media/QNAP_Books/Books --write
```

## Overwrite existing sidecars

```bash
python3 opf_to_grimmory_json.py --root /media/QNAP_Books/Books --write --overwrite
```

## Only PDF

```bash
python3 opf_to_grimmory_json.py --root /media/QNAP_Books/Books --ext pdf --write
```

## Grimmory setting

After creating the sidecars, set Grimmory's metadata source to:

- `Metadata source: Prefer Sidecar`
- or `Sidecar Only`

## Safety note

This script only creates `.metadata.json` sidecar files. It does not rename books, delete anything, modify `metadata.opf`, or touch the PDF/ebook files themselves.
