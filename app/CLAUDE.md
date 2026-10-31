# Instructions for `app/`

- Keep routes thin; route → service → repository.
- Use Pydantic v2 schemas and SQLAlchemy 2.x typed mappings.
- Derive learner identity from authentication, never a request body field.
- Use PostgreSQL transaction handling for attempt + mastery changes.
- Do not call LLMs from repositories or database model hooks.
- Do not let LLMs determine correct answers or BKT states.
- Mock provider clients in tests; never make paid/external model calls in default test runs.
- Match the deployed 26-table schema; inspect database nullability, types, and schema name before writing Alembic migrations.
