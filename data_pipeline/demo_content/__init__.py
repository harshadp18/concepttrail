"""AI-generated, textbook-grounded DEVELOPMENT/DEMO content (owner instruction 2026-11-01).

Pipeline: select chapters → extract only what is missing (existing Phase 4 pipeline) →
local Qwen drafts KCs, prerequisite edges and original questions in small persisted batches →
deterministic validation → import into existing tables with `review_status = "demo_release"`.

Demo content is never human-approved and never production-released: it is served only when
`CONTENT_RELEASE_MODE=demo` in a development environment (`app.core.content_release`).
"""

DEMO_STATUS = "demo_release"
WORK_DIR_NAME = "demo_generation"
