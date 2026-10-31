-- Run in pgAdmin Query Tool against the ConceptTrail database.
-- Expected schema name: concepttrail. This script is read-only.

-- 1) Table count and names
SELECT COUNT(*) AS table_count
FROM information_schema.tables
WHERE table_schema = 'concepttrail'
  AND table_type = 'BASE TABLE';

SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'concepttrail'
  AND table_type = 'BASE TABLE'
ORDER BY table_name;

-- 2) All columns, types and nullability
SELECT table_name, ordinal_position, column_name,
       data_type, udt_name, is_nullable
FROM information_schema.columns
WHERE table_schema = 'concepttrail'
ORDER BY table_name, ordinal_position;

-- 3) PK, FK and UNIQUE constraints
SELECT tc.table_name, tc.constraint_name, tc.constraint_type,
       kcu.column_name,
       ccu.table_name AS referenced_table,
       ccu.column_name AS referenced_column
FROM information_schema.table_constraints tc
LEFT JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name
 AND tc.constraint_schema = kcu.constraint_schema
LEFT JOIN information_schema.constraint_column_usage ccu
  ON tc.constraint_name = ccu.constraint_name
 AND tc.constraint_schema = ccu.constraint_schema
WHERE tc.table_schema = 'concepttrail'
  AND tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY', 'UNIQUE')
ORDER BY tc.table_name, tc.constraint_type, tc.constraint_name;

-- 4) pgvector extension
SELECT extname, extversion
FROM pg_extension
WHERE extname = 'vector';
