# Troubleshooting guide

| Symptom | Likely cause | Diagnose | Fix / verify |
|---|---|---|---|
| `DATABASE_URL` connection refused | PostgreSQL service stopped or wrong port/host | Check Windows Services / pgAdmin server status; `SHOW port;` | Start correct service, verify port and URL, rerun DB check |
| Password authentication failed | Wrong DB credentials or unescaped URL characters | Connect in pgAdmin; inspect URL encoding (do not paste secret into chat/log) | Correct `.env`, percent-encode reserved password characters; restart app |
| `relation does not exist` | Wrong schema/search path or table wasn't migrated | Query `information_schema.tables` for schema `concepttrail` | Set SQLAlchemy schema explicitly or verify migration; do not rerun destructive bootstrap |
| Alembic says relation already exists | Existing tables not baselined | Inspect current schema vs migration metadata | Review and stamp baseline only after matching; do not drop tables |
| `type vector does not exist` | Extension not installed/enabled in current database/search path | `SELECT extname, extversion FROM pg_extension WHERE extname='vector';` | Install pgvector server files and `CREATE EXTENSION vector` in correct DB |
| `vector dimensions do not match` | Different embedding models/dimensions mixed | Compare model ID and vector lengths | Re-embed consistently or separate model/index generations; do not compare incompatible vectors |
| Empty PDF extraction | Scanned/image-only PDF or encrypted file | Compare page count and per-page text lengths | OCR only permitted pages; inspect errors and language pack |
| OCR garbles Hindi/math | Wrong/missing language pack or low-quality scan | Review page image and OCR diagnostics | Install correct Tesseract language data; manual correction; retain original |
| Chapter boundaries wrong | TOC/heading structure ambiguous | Compare extracted JSON with original PDF pages | Fix structure stage or human override; add regression fixture |
| Duplicate content on rerun | Pipeline not idempotent | Compare source hash, stage version and record IDs | Use stable IDs and input/config hash; upsert only reviewed versions |
| Poor retrieval | Chunks too large/small, wrong metadata, weak embedding model | Inspect top-k chunks and metadata filters; evaluate Recall@k/MRR | Improve chunk strategy/filtering/model based on benchmark; don't start by fine-tuning LLM |
| Irrelevant class/subject result | Filter missing or applied after retrieval | Inspect query plan and returned metadata | Apply hard SQL/vector metadata filters before returning chunks |
| Primary/fallback provider timeout or 429 | Provider quota or outage | Inspect redacted provider status/latency logs and current account quota | Bounded timeout/retry; transient fallback only; rate limit and backoff |
| LLM returns invented citations | Output not checked against retrieved IDs | Run citation resolver against actual retrieved set | Reject citation, ask regenerate once or abstain; citations come from DB |
| Duplicate attempt updates mastery twice | Missing idempotency/transaction | Submit same idempotency key twice in integration test | Unique idempotency key and transaction guard; only update BKT once |
| BKT probability outside [0,1] | Bad config or math/numerical edge case | Inspect config version and update unit tests | Validate parameter range and clamp only with explicitly justified numerical policy |
| Graph cycle | Incorrect prerequisite edge | Run directed cycle detection and inspect edge provenance | Quarantine/review edge; never publish cyclic graph |
| Teacher sees another class | Missing server-side assignment check | Test access with unassigned teacher | Enforce classroom assignment in repository/service and API dependency |
| Windows `nmake` not found | Not using x64 Native Tools prompt | `where nmake`, `where cl` | Open Visual Studio x64 Native Tools prompt; check PGROOT points to matching PostgreSQL |
| `PGROOT is not set` | Build environment lacks PostgreSQL path | `echo %PGROOT%` | Set `PGROOT=C:\Program Files\PostgreSQL\18` in that prompt (adjust actual version) |
