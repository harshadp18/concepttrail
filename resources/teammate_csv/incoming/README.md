# Put teammate CSV originals here

Copy the untouched `.csv` file(s) that your teammate created into this directory. Keep the original filename and do not manually edit the rows before the first profile run. You can place multiple exports here; Claude must process each as a separate dataset/run unless the owner explicitly says they are parts of one dataset.

Claude Code reads this directory only. It writes a byte-identical, read-only snapshot to `data_pipeline/data/raw/teammate_csv/<stem>/<sha256>/` and all cleaning outputs to `resources/teammate_csv/processed/` and `resources/teammate_csv/mappings/` (D-030).

Do not store student names, phone numbers, roll numbers, credentials or other personal data unless explicitly approved. Never commit incoming data to Git.

### Module specification

1. **Purpose:** exact file intake path used by the cleaning pipeline.
2. **Updates:** no edits in-place; original files remain immutable.
3. **Manifest:** user-supplied CSV files plus `.gitkeep` and this README.
4. **Schema:** unknown until profile stage has inspected each file.
5. **File behavior:** only read; snapshot and hash first.
6. **Integration:** `profile_csv.py` is the first processing stage.
7. **Verification:** input bytes unchanged and each discovered CSV has a profile/run record.
