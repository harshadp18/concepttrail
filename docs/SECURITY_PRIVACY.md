# Security, privacy, copyright and responsible educational AI

## Student data

- Collect the minimum data needed for login, classroom assignment, learning state and progress.
- Use internal UUID/pseudonymous IDs in model prompts; do not send names, emails, phone numbers, school identifiers or auth credentials to providers.
- Do not log full student messages or response content by default. Use request IDs and safe operational metadata.
- Define retention/deletion, account offboarding, export and backup policies before a student pilot.
- Restrict teacher dashboard queries to assigned classrooms and enforce access on the backend, not only in the UI.
- Review applicable Indian child-data/privacy requirements, consent/authority, school responsibilities and provider terms with qualified advisors before production use. This document is an engineering checklist, not legal advice.

## Secrets and auth

- `.env` is local and Git-ignored; only placeholders in `.env.example`.
- Use password hashing, expiry/rotation, HTTPS, rate limits and least-privilege DB credentials.
- Never expose stack traces, API keys, database URLs or hidden answer keys to clients.

## Source rights

For each source, track rights for internal processing, external model processing, indexing/retrieval, model training, display/excerpting and redistribution independently. A public PDF is not automatically usable as a software knowledge base. Stop the affected stage if permission is unknown. Respect source terms and do not bypass access controls.

## Responsible AI

- Give age-appropriate explanations and transparent source references.
- Abstain or clarify when context/evidence is insufficient.
- Never fabricate textbook citations, answer keys, curriculum status or learning outcomes.
- Human review for uncertain academic content, maps/diagrams, subjective language responses, generated prerequisite edges and teacher activities.
- Monitor unsupported claims, wrong citations, language quality and subject/class regressions.
- Provide teacher escalation and correction mechanisms.
