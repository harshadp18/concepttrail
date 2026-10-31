# Raw teammate CSV snapshots

Byte-identical copies of CSV files from `resources/teammate_csv/incoming/`. Path convention: `<dataset_slug>/<sha256>/<original_filename>.csv`. Never clean, rewrite, re-encode or normalise a file in this directory.

### Module specification

1. **Purpose:** preserve incoming CSV evidence for reproducibility.
2. **Updates:** first-class input snapshot alongside source PDFs.
3. **Manifest:** per-dataset/per-hash directory with original file and snapshot manifest.
4. **Schema:** raw CSV retains unknown teammate header/row schema; manifest records byte hash, byte size, filename and detected profile run IDs.
5. **File behavior:** copy atomically and verify SHA-256; no in-place writes.
6. **Integration:** profile stage reads snapshot, not a changing drop-zone file.
7. **Verification:** source and snapshot SHA-256 are equal.
