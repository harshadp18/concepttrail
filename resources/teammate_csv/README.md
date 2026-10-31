# Teammate CSV drop-zone

Place the original CSV export(s) made by the teammate in `resources/teammate_csv/incoming/`. Do not edit the source file to fix it before Claude profiles it; preserve the evidence of the incoming dataset. Keep any accompanying notes in a separate text/Markdown file, not by changing CSV data.

Claude Code must not assume this export is the canonical curriculum inventory. It first profiles the file and identifies its purpose, columns and data-quality issues. It then applies only explicit, documented transformations, keeps accepted/rejected records separate and asks for owner review of ambiguous mapping. If it is a curriculum inventory, mapping to the single exact 29-column `data_pipeline/curriculum.csv` requires field-by-field approval.

Run `python -m data_pipeline.clean_teammate_csv`. Outputs: `processed/` (cleaned, rejected and quarantined rows, reports, manifests) and `mappings/` (field mapping and merge proposal), both Git-ignored. Rules: `data_pipeline/README.md`, "Teammate inventory cleaning".

### Module specification

1. **Purpose:** teammate CSV input boundary.
2. **Updates:** required profiling and cleaning pipeline with PDF cross-check support.
3. **Manifest:** `incoming/` for original CSVs and this README.
4. **Schema:** source schema is profiled, not presumed; canonical schema is selected only after identifying dataset purpose.
5. **File behavior:** original file is read-only; raw snapshots/profiles/cleaned outputs/rejections use separate paths.
6. **Integration:** CSV profile, clean and validate stages; optional PDF evidence cross-check.
7. **Verification:** all rows accounted for; source hash unchanged; transformations and rejections documented.
