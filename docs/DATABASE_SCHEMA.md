# Database schema and relational model

## 1. Database facts and implementation boundary

The owner reports PostgreSQL 18 and pgvector 0.8.7 installed locally and the 26-table schema created successfully. The target PostgreSQL schema namespace is `concepttrail`. The package contains a bootstrap SQL snapshot in `db/schema/001_initial_schema.sql`; do not rerun against the user's populated database.

The current ERD/DDL baseline uses string IDs for `subject_id` and other curriculum/content IDs (`VARCHAR`), UUID IDs for user/attempt/job/embedding records, and `VECTOR` without a fixed dimension. An INTEGER `subject_id` was discussed but not applied in the executed script. Preserve the current schema until an explicit migration is approved.

## 2. The 26 tables and purpose

| Table | Purpose | Key relationships |
|---|---|---|
| `subject` | Master subject lookup: Mathematics, Science, English, Hindi, Social Science | referenced by curriculum_item, source_document, knowledge_component |
| `curriculum_version` | Board/session/class/course/language version | parent of curriculum_item; optional source_document version |
| `source_document` | Source title, URL, edition/hash, rights/use status | belongs to subject/version; parent of content_unit and ingestion job mapping |
| `curriculum_item` | Chapter/topic/subtopic/objective hierarchy | belongs to version/subject; self-parent; covers content units; maps to KCs |
| `content_unit` | Extracted structured section/example/table/passage | belongs to source; optionally maps to curriculum item; parent of chunks/KC map |
| `knowledge_component` | Atomic skill/concept | belongs to subject; maps to curriculum/content/questions/notes/edges/mastery |
| `content_unit_kcs` | M:N bridge content_unit ↔ KC | composite PK `(content_unit_id, kc_id)` |
| `kc_curriculum_map` | M:N bridge KC ↔ curriculum_item | composite PK `(kc_id, item_id)` |
| `kc_edge` | Recursive prerequisite/dependent KC relation | composite PK `(prerequisite_kc_id, dependent_kc_id)` |
| `questions` | Question bank and expected answer/rubric/verification | parent of options, attempts and question-KC map |
| `question_kcs` | M:N bridge question ↔ KC | composite PK `(question_id, kc_id)` |
| `question_options` | MCQ choices | FK to question |
| `note` | Notes/explanations linked to one KC | FK to KC; optional approver user |
| `users` | Login/account records | parent of learners, user roles, jobs and note approvals |
| `learners` | Learner profile | 1:1 optional profile to user; parent of attempts/state/enrollments |
| `role` | Role lookup: student, teacher, admin | parent of user_roles |
| `user_roles` | M:N bridge users ↔ roles | composite PK `(user_id, role_code)` |
| `attempts` | Immutable student response attempts | FK to learner and question |
| `bkt_config_version` | Versioned BKT parameters | parent of student_kc_state |
| `student_kc_state` | Current mastery estimate per learner/KC | composite PK `(learner_id, kc_id)` |
| `embedding_chunk` | Chunk text, embedding model ID, vector and index generation | FK to content_unit |
| `ingestion_job` | Processing job record | parent of ingestion_job_documents; optional creator user |
| `ingestion_job_documents` | M:N bridge job ↔ source document with per-document status | composite PK `(job_id, source_id)` |
| `classroom` | School/class/section/session grouping | parent of enrollments and teacher assignments |
| `class_enrollments` | Learner ↔ classroom enrollment history | learner and classroom FKs |
| `teacher_class_assignments` | User ↔ classroom assignment history/type | composite PK `(classroom_id, user_id)` in current baseline |

## 3. Relationship and participation rules

Mermaid cardinality notation used by the ERD: `||` exactly one; `o|` zero or one; `|{` one or many; `o{` zero or many. Participation is a separate concept: total participation means each row on that side must take part; partial means it may exist without a related row.

| Relationship | Type | Intended participation / note |
|---|---|---|
| subject → curriculum_item | 1:M | subject partial; item total by design |
| curriculum_version → curriculum_item | 1:M | version partial; item total |
| curriculum_item → child curriculum_item | recursive 1:M | both partial; root chapters have no parent |
| subject → source_document | 1:M | subject partial; source belongs to one subject in current design |
| curriculum_version → source_document | 1:M optional | version partial; source may have no single curriculum version |
| source_document → content_unit | 1:M | source partial before extraction; content unit total |
| curriculum_item → content_unit | 1:M optional | both can be partial during mapping/review; item_id nullable |
| subject → knowledge_component | 1:M | subject partial; KC belongs to one subject |
| content_unit ↔ KC | M:N | implemented by `content_unit_kcs`; parent rows may be unmapped during drafts |
| curriculum_item ↔ KC | M:N | implemented by `kc_curriculum_map` |
| KC ↔ KC | recursive M:N | implemented by `kc_edge`; source and dependent roles are separate FKs |
| question ↔ KC | M:N | implemented by `question_kcs`; require at least one approved mapping before publishing a question |
| KC → note | 1:M | KC may have no note; each note references one KC |
| question → option | 1:M | question may have zero options for non-MCQ; each option belongs to one question |
| question → attempt | 1:M | question may have no attempts; every attempt belongs to one question |
| learner → attempt | 1:M | learner may have no attempts; every attempt belongs to one learner |
| user → learner | optional 1:1 | user may have zero/one learner profile; learner must map to one user; unique FK |
| user ↔ role | M:N | implemented by `user_roles` |
| learner ↔ KC | M:N | implemented by `student_kc_state`; only KCs with an initial/current estimate need rows |
| BKT config → learner KC state | 1:M | config may be unused; each state stores the config used |
| content_unit → embedding_chunk | 1:M | content unit may be unindexed; each chunk belongs to one content unit |
| ingestion_job ↔ source_document | M:N | implemented by `ingestion_job_documents`; enforce at least one job document in application/transaction logic if required |
| learner ↔ classroom | M:N over time | implemented by `class_enrollments` |
| user ↔ classroom | M:N | implemented by `teacher_class_assignments`; user must have teacher role by authorization rule |

## 4. Table field groups

The exact columns and types are in `db/schema/001_initial_schema.sql`. The following details are particularly important:

- `subject.subject_id`: `VARCHAR` in current baseline. Do not silently change to integer.
- `curriculum_version.class_level`, `classroom.grade_level`: `SMALLINT` with intended range 6–10.
- `source_document.permitted_uses`, `curriculum_item.learning_objectives`, `content_unit.asset_refs`, `knowledge_component.misconceptions`, `questions.expected_answer`, `questions.rubric`, `questions.misconception_map`, `questions.source_refs`, `questions.verification`, `attempts.submitted_answer`, `bkt_config_version.parameters`: `JSONB` for structured flexible payloads.
- `content_unit` retains source ID, curriculum item mapping, extracted text, PDF page index, printed page label, asset references, content hash and pipeline version.
- `content_unit_kcs`, `kc_curriculum_map`, `kc_edge`, `question_kcs`, `user_roles`, `student_kc_state`, `ingestion_job_documents`, `teacher_class_assignments` use composite primary keys in the baseline.
- `learners.user_id` and `users.login_identifier` are unique.
- `attempts.idempotency_key` is unique.
- `embedding_chunk.embedding` is `VECTOR` with no dimension in the current baseline. Its only content FK is `content_unit_id`; do not add a source_document FK not present in the ERD.

## 5. Constraints the current bootstrap may not enforce

The first script used PKs, FKs, and stated UNIQUE constraints, but did not declare `NOT NULL` for every foreign key or add all business checks. Therefore:

- An FK does not imply NOT NULL.
- ERD total participation is not fully enforced unless the FK column is NOT NULL.
- Multi-column business rules (one active enrollment per learner/class, at least one question KC before publication, at least one document per ingestion job) need extra unique/partial indexes, triggers, or transaction/application validation.
- `kc_edge` needs self-edge and directed-cycle checks at service/publish time.
- `student_kc_state.mastery_probability` should be constrained to [0,1] in a reviewed migration.
- class levels should be constrained to 6–10.
- question options should have `UNIQUE(question_id, option_key)`.

Do not add these to the live DB without checking existing data and preparing a migration.

## 6. Introspection queries

List tables:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema='concepttrail' AND table_type='BASE TABLE'
ORDER BY table_name;
```

List columns/types/nullability:

```sql
SELECT table_name, ordinal_position, column_name,
       data_type, udt_name, is_nullable
FROM information_schema.columns
WHERE table_schema='concepttrail'
ORDER BY table_name, ordinal_position;
```

List constraints:

```sql
SELECT tc.table_name, tc.constraint_name, tc.constraint_type,
       kcu.column_name, ccu.table_name AS referenced_table,
       ccu.column_name AS referenced_column
FROM information_schema.table_constraints tc
LEFT JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name=kcu.constraint_name
 AND tc.constraint_schema=kcu.constraint_schema
LEFT JOIN information_schema.constraint_column_usage ccu
  ON tc.constraint_name=ccu.constraint_name
 AND tc.constraint_schema=ccu.constraint_schema
WHERE tc.table_schema='concepttrail'
ORDER BY tc.table_name, tc.constraint_type;
```

Check extension:

```sql
SELECT extname, extversion FROM pg_extension WHERE extname='vector';
```

## 7. Migration policy

The user already ran the initial schema. Introspect and baseline. Future changes use Alembic; review autogenerated migrations. Take a backup before altering production-like data. Never drop/recreate the schema to fix migration state.

Implemented 2026-10-31:
- Alembic is configured, with `public.alembic_version` as the version table.
- Baseline revision `0001` builds this exact schema from an empty database and was verified on disposable databases.
- The owner's database matches `0001` with zero differences (read-only comparison), but it is **not stamped**. Stamping needs explicit owner approval.

Procedures are in `app/db/migrations/README.md`.
