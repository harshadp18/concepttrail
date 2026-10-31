# Textbook PDF drop-zone

Copy original textbook/source PDFs into this folder. You may create descriptive subfolders, for example `Class_08/Mathematics/Edition_or_Session/`, but do not rename a source if its original filename is needed for tracing. Flat placement is also accepted. Preserve the original bytes.

Claude Code must record each file's SHA-256, page count and candidate source metadata. It must ask for/confirm the source-to-CSV relationship when uncertain. Do not extract text, OCR, send to a model or embed until the applicable rights status and local-processing permission are explicitly recorded. PDF page references in any cross-check must distinguish zero/one-based PDF page index from printed page label.

### Module specification

1. **Purpose:** non-destructive user intake for textbook PDFs.
2. **Updates:** paired with the teammate CSV intake; no processing on unknown rights.
3. **Manifest:** PDF files placed by user; this README; `.gitkeep`.
4. **Schema:** no standalone source inventory; link to the one master `data_pipeline/curriculum.csv` by reviewed `source_id`.
5. **File behavior:** read only; snapshot by hash under `data_pipeline/data/raw/textbooks/`; do not alter/overwrite.
6. **Integration:** `compare_csv_to_pdfs.py` and permitted `extract_pdf.py`.
7. **Verification:** original hash unchanged; source ID and permission verified; all cited page locators resolve.
