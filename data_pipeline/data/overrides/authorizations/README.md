# Purpose-specific authorisation records (private: not published)

The JSON records in this folder are **private and Git-ignored**. They are never published; only this README is.

## How they work

- Each record is write-once. It names a basis, a scope, the specific **uses** it grants, and the exact documents it covers, each bound by `source_id` and SHA-256.
- `data_pipeline/authorization.py::check_use()` is the gate that every processing stage calls. A use is permitted only when a record grants that use for that document's exact bytes. If a document's bytes change, its hash no longer matches and the gate refuses it.
- With no records present the gate **fails closed**: every use is refused and nothing is processed.
- Records are never edited. A changed scope needs a new record with a new `record_id`.
- Records contain no textbook content.
- Inventory permission fields are never rewritten; a record may be applied as a documented overlay in derived outputs only, with each change logged.
- A record states its basis. An owner-provided record is the owner's own statement and is not independent legal verification.

## Always refused by the gate

Model training or fine-tuning and redistribution are refused whatever a record lists; they need a dedicated authorisation. Training stays `not_permitted`. A provider being selected, or configured, never authorises sending content to it (see `docs/PUBLIC_DECISIONS.md`).

See `docs/PUBLICATION_AND_REPRODUCIBILITY.md` for how private records are supplied to a checkout.
