# Human-approved CSV cleaning overrides

Store only explicitly reviewed corrections or field mappings here. Do not use overrides to silently invent missing facts. Each override must include dataset slug, original input SHA-256, logical row number or stable record key, column name, original value hash, approved replacement/mapping, reviewer, review timestamp and reason/evidence. A source hash mismatch makes the override stale and it must not be applied automatically.

### Module specification

1. **Purpose:** explicit human-approved exceptional corrections and mappings.
2. **Updates:** supports teammate CSV mapping and discrepancy resolution.
3. **Manifest:** versioned YAML/JSON override records.
4. **Schema:** dataset/hash, target row/key, field, before/after, reviewer, timestamp, reason.
5. **File behavior:** validate target and hash; reject stale overrides.
6. **Integration:** clean/validate stages apply approved overrides in deterministic order.
7. **Verification:** replay idempotency, stale-source rejection and auditability.
