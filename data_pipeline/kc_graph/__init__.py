"""Phase 5 KC and prerequisite-graph pipeline: load, validate, review, release, import.

See `docs/PHASE_5_IMPLEMENTATION_HANDOFF.md`. Read-only by default; no module here calls an
external provider, and only `import_plan.execute` writes to the database (owner approval
required). Run `python -m data_pipeline.kc_graph --help`.
"""
