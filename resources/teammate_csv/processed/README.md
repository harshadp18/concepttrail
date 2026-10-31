# Teammate CSV cleaning outputs (generated)

Written by `python -m data_pipeline.clean_teammate_csv`. Do not edit by hand: change the
source export or an approved rule and re-run. Everything here except this README is
Git-ignored.

| Folder | Contents |
|---|---|
| `cleaned/` | `<stem>.cleaned.csv`: accepted rows, exact canonical 29-column header, source order |
| `rejected/` | `<stem>.rejected.csv` and `<stem>.quarantined.csv`: original values plus `__` reason columns |
| `reports/` | profile, quality (JSON + Markdown), duplicates, missing fields, coverage, PDF paths, SHA-256, reviewer notes |
| `manifests/` | `<stem>.manifest.json` (hashes, versions, reconciliation), `<stem>.decisions.jsonl`, `<stem>.reconciliation.csv` |

See `data_pipeline/README.md` ("Teammate inventory cleaning") for the rules.
