# ConceptTrail
### Understand the gap. Adapt the learning. Empower every student.

ConceptTrail is an AI-assisted adaptive learning platform designed for **CBSE students in Classes 6–10**. It helps students practise, understand concepts, identify learning gaps and receive personalised learning recommendations. It also gives teachers insights into class performance so they can identify topics that need additional attention.

Unlike a conventional quiz application or an AI chatbot wrapper, ConceptTrail combines deterministic learning algorithms, knowledge tracing, prerequisite relationships and retrieval-grounded AI assistance.

**Our core principle: Algorithms decide. AI writes.**

---

## 1. The problem we are solving

Students do not all learn at the same pace. When a student answers a question incorrectly, simply showing the correct answer does not necessarily address the underlying problem.

The difficulty may come from an earlier concept that the current topic depends on.

Teachers also need more than individual test scores. They need to identify patterns across their classes and understand which topics require additional support.

ConceptTrail addresses these challenges through:

- Personalised practice based on estimated learner mastery.
- Identification of possible prerequisite knowledge gaps.
- Adaptive question selection and learning recommendations.
- Curriculum-grounded AI tutoring.
- Class-level learning insights for teachers.
- Topic-specific classroom warm-up planning through Bell Ringer.

## 2. Key features

### Student experience

**Personalised learning dashboard**

Students can view their subjects, available chapters, learning progress, recent activity and areas that need additional practice.

**Adaptive practice**

Questions are delivered through the backend's assessment and adaptive-learning services. Student answers are evaluated deterministically, and eligible attempts update the learner's knowledge state.

**Knowledge tracing**

ConceptTrail uses Bayesian Knowledge Tracing (BKT) to estimate mastery of individual Knowledge Components (KCs), based on the learner's recorded response history.

**Prerequisite awareness**

A knowledge graph represents relationships between concepts. When a student struggles, ConceptTrail can use available prerequisite relationships to identify earlier concepts that may need revision.

**Learning recommendations**

The adaptive engine uses learner state, prerequisite readiness, question history and available content to determine suitable next learning activities.

**Progress and revision**

Students can review chapter and subject progress, activity history, weak areas and retry questions.

### Buddy — AI learning companion

Buddy helps students ask questions and understand concepts using relevant retrieved learning material.

Its workflow includes:

1. Processing the student's question.
2. Retrieving relevant, eligible learning content.
3. Constructing a context grounded in retrieved evidence.
4. Generating an explanation using the configured local language model.
5. Validating citations and returning a grounded answer or an abstention.

Buddy supports follow-up questions within a conversation.

When available evidence is insufficient, it can explicitly decline to answer rather than inventing an explanation or source.

### Teacher experience

**Class dashboard**

Teachers can inspect their assigned classes, learner rosters, progress summaries and common weak areas.

**Learning heatmap**

The interactive heatmap presents learners against topics or Knowledge Components. It helps teachers identify patterns of mastery and difficulty across a class.

- Numeric mastery values are displayed where sufficient data exists.
- Missing data is shown as unavailable, not incorrectly represented as zero mastery.
- Filters, tooltips and topic/learner details support exploration.
- Teacher access is restricted to assigned classes by backend authorization.

**Bell Ringer**

Bell Ringer helps teachers identify topics where multiple learners may need additional support.

Rather than creating one generic classroom plan, ConceptTrail creates separate topic-specific cycles.

Each topic card can show:

- Number of unique learners struggling.
- Learners with insufficient attempts for an estimate.
- Recent incorrect-answer patterns.
- Estimated mastery and the criteria used to flag a topic.
- Related prerequisite or root-gap signals where available.
- A structured warm-up activity.

The warm-up follows a short classroom format:

- 1 minute of individual thinking.
- 3 minutes of pair discussion.
- 1 minute of sharing.

It includes a board question, a bridge question, an answer key and the most common wrong answer in the available class data.

The warm-up is created from stored questions using a fixed template rather than relying on an LLM to invent an activity. Cycles can move through planned, run and completed states, with follow-up information where data is available.

Bell Ringer thresholds are configurable. Current demonstration thresholds were chosen for sparse synthetic data and should not be interpreted as universally validated classroom intervention criteria. Some prerequisite relationships in the demonstration are AI-proposed and are not independently academically verified.

---

## 3. How ConceptTrail works

ConceptTrail separates deterministic learning decisions from AI-generated language.

### Adaptive-learning workflow

1. A student receives a question from the backend.
2. The student submits an answer.
3. The backend evaluates it using the question's scoring rules.
4. The attempt is persisted.
5. The relevant Knowledge Component state is updated through BKT.
6. Prerequisite relationships and readiness are considered.
7. The adaptive policy selects a suitable next activity.

### AI tutoring workflow

1. The student asks Buddy a question.
2. The retrieval service finds relevant learning content.
3. Curriculum and source filters restrict the retrieved material.
4. The local LLM drafts an explanation using the available evidence.
5. The response is checked for valid citations.
6. Buddy responds with grounded information or abstains when evidence is inadequate.

**The LLM does not determine objective answer correctness, independently calculate mastery or own adaptive question selection.**

---

## 4. Technology stack

| Layer | Technology |
|---|---|
| Frontend | React, TypeScript and Vite |
| UI and interaction | Existing frontend component system and Motion for React |
| Charts and visualisations | Recharts and interactive UI components |
| Backend | Python and FastAPI |
| Database | PostgreSQL 18 |
| Vector search | pgvector |
| ORM | SQLAlchemy 2.x |
| Validation | Pydantic v2 |
| Migrations | Alembic |
| Knowledge tracing | Bayesian Knowledge Tracing |
| Prerequisite graph | NetworkX-based graph services |
| Local LLM | Qwen 3.5 9B through Ollama |
| Embeddings | BGE-M3 |
| Testing | pytest, Vitest and Playwright |
| Code quality | Ruff |

The application uses a modular-monolith backend architecture. PostgreSQL remains the relational source of truth for structured curriculum, questions, attempts, learner state and other application records.

The frontend communicates with the backend through versioned HTTP APIs. It does not connect directly to PostgreSQL, Redis or Ollama.

---

## 5. Current implementation status

The project has progressed from an initial backend prototype to an integrated, locally running MVP.

### Latest reported verification

| Verification | Result |
|---|---:|
| MVP readiness gate | 15/15 checks passed |
| Backend automated tests | 1,005 passed, 1 skipped |
| Frontend unit tests | 53 passed |
| Browser end-to-end tests | 6 passed |
| Frontend type-check | Passed |
| Frontend production build | Passed |
| Ruff checks and formatting | Clean |
| OpenAPI drift check | Clean |
| Git diff check | Clean |
| OpenAPI routes | 40 paths |

The skipped backend test is the seed-rollback test. It had passed previously on a clean disposable database but was not rerun in the latest verification session.

The reported browser visual review covered 1440, 1280, 1024 and 390 pixel viewport widths, with the final review reporting no horizontal overflow or browser console errors.

### Live local AI verification

The local Buddy integration was tested using Qwen and BGE-M3.

The reported verification included a grounded response with three textbook citations and two cases where Buddy correctly declined to answer because suitable evidence could not be found.

These are implementation and demonstration results, not independent academic-quality evaluations.

---

## 6. Curriculum scope and content coverage

The initial product scope covers five subject families across CBSE Classes 6–10:

| Subject | Classes |
|---|---|
| English | 6–10 |
| Hindi | 6–10 |
| Mathematics | 6–10 |
| Science | 6–10 |
| Social Science | 6–10 |

This represents 25 possible class-subject combinations.

**The platform's intended scope should not be confused with complete content coverage.** Actual chapter and learning-content availability varies by class and subject. The catalog reports unavailable combinations rather than inventing content to fill gaps.

Content and prerequisite relationships may include AI-generated drafts. They should not be described as independently teacher-reviewed or academically validated unless that review has actually occurred.

---

## 7. Running ConceptTrail locally

The following instructions describe the current Mac development/demo setup. Refer to `docs/LOCAL_DEVELOPMENT.md` for initial setup and troubleshooting.

### Prerequisites

- macOS.
- Python virtual environment and backend dependencies.
- Node.js and npm.
- Docker with the required disposable demo database and Redis containers.
- Ollama.
- Required local models: `qwen3.5:9b` and `bge-m3`.

### Start supporting services

From the ConceptTrail project root:

```bash
docker start ct-disposable-migrations ct-disposable-redis
```

Start Ollama if it is not already running:

```bash
pgrep -x ollama >/dev/null || ollama serve &
```

### Start the backend

In Terminal 1, from the project root:

```bash
./scripts/run_demo_backend.sh
```

The demo launcher is designed to refuse database URLs that do not use the `ct_demo` naming convention.

### Start the frontend

In Terminal 2:

```bash
cd frontend
npm run dev
```

### Local application URLs

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Demo backend | http://localhost:8020 |
| API base | http://localhost:8020/api/v1 |
| Interactive API documentation | http://localhost:8020/docs |

### Demo accounts

Presentation and development credentials are stored in ignored local files under `.local/`. They are not included in this README or intended for real accounts.

Use the documented local demo credential files and the correct login tab:

- Students: username and eight-digit PIN.
- Teachers: school email and password.

Do not publish demo credentials or reuse them for real accounts.

### Stop the local services

The current local development instructions use:

```bash
kill $(lsof -tiTCP:5173 -sTCP:LISTEN) $(lsof -tiTCP:8020 -sTCP:LISTEN)
docker stop ct-disposable-migrations ct-disposable-redis
```

See `docs/LOCAL_DEVELOPMENT.md` if a service does not stop or restart as expected.

---

## 8. Project structure

The repository contains the integrated frontend and backend, data-processing pipeline, tests, evaluation tools and documentation.

```text
concepttrail/
├── frontend/                 # React frontend
├── app/                      # FastAPI backend
│   ├── api/                  # Versioned API routes
│   ├── core/                 # Application configuration and security
│   ├── db/                   # Database models, sessions and repositories
│   ├── schemas/              # Request and response schemas
│   └── services/             # Learning, AI and teacher services
├── data_pipeline/            # Curriculum and content processing
├── db/                       # SQL schema references and verification
├── deploy/                   # Local/deployment configuration
├── docs/                     # Architecture, integration and operating guides
├── evaluation/               # Algorithm and system evaluations
├── resources/                # Source and data intake locations
├── scripts/                  # Demo, ingestion and operational scripts
├── tests/                    # Backend tests
├── training/                 # Reserved ML experiment area
├── .env.example
├── pyproject.toml
└── README.md
```

---

## 9. Data protection, content rights and demo limitations

ConceptTrail currently uses fictional learner and teacher identities and synthetic learner activity for demonstration.

The demo data is not evidence of actual school performance or real-world learning improvement.

The current educational content includes AI-drafted material that has not all undergone independent teacher or subject-expert review. Some prerequisite links are AI-proposed.

The project maintains separate controls for source processing, external-model processing, retrieval/indexing, training, display and redistribution.

A source being publicly downloadable does not automatically grant permission to redistribute its content or use it for every processing purpose.

Certain AI-drafted and textbook-derived content review artifacts are subject to publication restrictions until redistribution rights are established. Do not add restricted datasets, textbook extracts, credentials, private learner data or other protected material to public Git commits.

The source code and algorithms can be published separately from content whose rights have not been established.

### Database and migrations

The persistent database remains at Alembic revision `0001` in the latest reported verification.

Migrations `0002`, `0003` and `0004` have been tested and applied to the disposable `ct_demo` database, but have not been applied to the persistent database.

Do not run migrations against a persistent database without explicit owner approval and a verified backup.

### Production readiness

ConceptTrail is an MVP demonstration platform, not a production-approved educational service.

Its production release gate intentionally remains blocked by outstanding requirements, including academic and content validation, real learner evidence, curriculum coverage, rights decisions, migration approval and other operational checks.

Synthetic BKT calibration does not establish real-world model calibration. Synthetic adaptive simulations do not demonstrate proven learning gains.

---

## 10. Future scope

ConceptTrail is designed with a class- and subject-neutral architecture so it can expand beyond its initial curriculum.

Planned areas of development include:

- **More subjects:** extending the platform into additional academic and skill-based subjects.
- **More education boards:** exploring support for ICSE and different State Boards, alongside CBSE.
- **More curriculum variants:** accommodating different courses, language options, academic sessions and syllabus structures.
- **Multilingual learning:** improving explanations, retrieval and learning support across Indian languages.
- **Improved adaptivity:** evaluating prerequisite discovery, question selection, knowledge tracing and revision schedules using suitable reviewed data.
- **More teacher tools:** richer classroom analytics, intervention tracking and topic-specific learning support.
- **Offline and low-connectivity support:** investigating reliable access for students with limited internet connectivity.
- **Stronger validation:** independent academic review, real learner evaluation and controlled studies before making educational-impact claims.

These are planned expansion areas, not claims that the capabilities are already implemented.

---

## 11. Documentation

For technical details, refer to:

| Document | Purpose |
|---|---|
| `docs/MVP_SCOPE.md` | MVP objectives and scope |
| `docs/BACKEND_MVP_REPORT.md` | Backend implementation and verification |
| `docs/API_CONTRACTS.md` | Actual API contracts |
| `docs/FRONTEND_INTEGRATION.md` | Frontend and backend integration |
| `docs/FRONTEND_UI_AUDIT.md` | Frontend design corrections and visual audit |
| `docs/LOCAL_DEVELOPMENT.md` | Local setup, startup and troubleshooting |
| `docs/openapi/openapi-v1.json` | OpenAPI specification |

---

## 12. Project philosophy

We believe personalised education should do more than give a learner another question or generate another explanation.

It should understand the learner's current knowledge, recognise possible gaps, choose meaningful next steps and help teachers respond to classroom needs.

**ConceptTrail — because every student deserves a learning path that adapts to them.**
