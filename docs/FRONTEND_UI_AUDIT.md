# Frontend audit and redesign (2026-11-01)

Scope: the frontend generated in Antigravity (kept unchanged in its original folder as the
source and recovery copy) was integrated into `frontend/`, repaired, connected to the real API and
checked in a browser at 1440×900, 1280×800, 1024×768 and 390×844. Screenshots are kept locally in
`.local/ui-audit/` (Git-ignored): `before/` (the original), `pass1/`, `pass2/`, `mobiletop/`.

## What was wrong with the original

| Area | Problem |
|---|---|
| Data | Almost every number, name, class, chart and message came from `mockData.ts` or was hard-coded in the page (for example "08 Topics mastered", "Class 8A", "Aarav Sharma", "150 learners"). Service functions called the API and then returned mock data regardless of the answer. |
| Authentication | Visitors were signed in automatically as a demo student. When the API failed, login fell back to fake sessions. The login form was pre-filled with credentials. A "Figma review" bar let anyone switch between student and teacher without signing in. |
| Practice | Answers were "scored" in the browser (`option B` or `5` was correct) when the API failed; feedback text was hard-coded for one equation. |
| Buddy | Any failure returned a canned "grounded" answer with invented sources. |
| Teacher | Class cards, roster, review queue and plans were mock data; Bell Ringer and the heatmap did not exist; "Plan cycle" was a single shared plan. |
| Landing page | A search button that did nothing; claims of "authentic 3D visual concepts" and "3D artwork"; invented "Class 8 core topics" behind a class switcher that changed nothing; a fabricated citation ("NCERT Class 8 Mathematics, Chapter 2, Page 23"); "Real-time Class 8A mastery heatmaps"; "streak counter" and "worked examples" that do not exist; Log in, Get started and Start learning for free all went to `/login`. |
| Login | The Learn / Practise / Grow chips and student-style card stayed on the teacher tab; teacher sign-in was labelled "School username" although the API uses the school email. |
| Visuals | Subject card images were low-resolution screenshot crops with a clipped "Class" badge baked into the pixels; the Continue Learning banner was a cropped image with a visible seam; the sidebar "mark" was a bad crop that included part of the wordmark; the logo image carried a large white margin, so it rendered tiny; cards in one row had different heights; "CURRENT CLASS" badge overflowed its card. |
| Accessibility | `user-scalable=no` blocked zoom; colour-only status; tiny 10px labels; no skip link. |

## What was changed

### Data and integration
- A single API layer (`src/api/`): typed responses, the backend error envelope, timeouts, 401
  handling, React Query caching and invalidation after writes. All mock data and fake fallbacks
  were removed. A contract test fails if the app calls a path that is not in the OpenAPI file.
- Real authentication: student username + 8-digit PIN, teacher school email + password, session
  restore through `/me`, role mismatch refused with a clear message, sign-out clears everything.
- Every screen shows loading, empty, error, forbidden, not-found, network and "not available yet"
  states. Missing data is shown as "Not started" / "—", never as 0.

### New teacher features (backend and frontend)
- **Bell Ringer** (from the ConceptTrail deck, slides 4, 6 and 8): topic-level analysis per class
  with unique-learner counts and denominators, transparent and configurable flagging criteria,
  root-gap tracing through the prerequisite graph, and a five-minute warm-up card built from stored
  questions (board question, bridge question, answer key, "watch for"). Each topic gets its own
  cycle (planned → run in class → completed) with a baseline and a follow-up; repeated requests
  never create duplicates. Cycle storage is a proposed migration (0004), disabled until approved.
- **Learning heatmap**: learners × topics for one class, one request per view, legend, numeric
  values in every cell, tooltips, keyboard navigation (one tab stop, arrow keys), a detail panel,
  filters by subject, chapter and attempt window, and a plain-text summary.

### Landing page
- Search removed completely (button, icon, import).
- 3D claims, invented topic lists, the fake class switcher and the fabricated citation removed;
  the "how it works" tabs now describe what the product really does.
- Audience cards: "Get clear, real-time insights into class progress and learning needs" and
  other general, accurate bullets; no class-specific copy.
- Three distinct calls to action: **Log in** → sign-in screen; **Get started** → the "Choose your
  ConceptTrail" section with separate student and teacher sign-in; **Explore the student
  journey** (formerly "Start learning for free") → the step-by-step tour. No public sign-up is
  implied.

### Login
- Student: "Learn, practise and grow." with a learning-trail illustration and Learn / Practise /
  Grow chips. Teacher: "See progress. Support every learner." with a class-heatmap illustration
  and Understand / Guide / Empower chips. Panel colour, copy, illustration and help text change
  with the tab; each tab keeps its own typed values; the PIN field accepts 8 digits only.

### Visual system
- Tokens in `tailwind.config.js` (brand `#287A9F`, text `#444444`, surfaces `#F0F2F3`/white,
  soft subject tints) and shared classes in `index.css` (type scale, cards, buttons, fields,
  pills). One app shell for both roles: 88px sidebar, 64px top bar, 76rem content width, mobile
  bottom navigation.
- Mastery bands use a palette checked for colour-vision deficiency and contrast (green
  `#1E7D45`, blue `#2F7FB5`, orange `#D0591B`), always paired with text labels.

### Images
| Asset | Use | Decision |
|---|---|---|
| Official logo (`assets/concepttrail-logo.png`) | everywhere | Kept. `brand/concepttrail-logo.png` and `brand/concepttrail-mark.png` are trims of the same artwork (background margin removed, pixels unchanged); one `BrandLogo` component. |
| Subject card images (`card-top-*`, `subject-*`) | home, subjects, landing | Replaced by five original SVGs in one flat style (`illustrations/subject-*.svg`). |
| Continue Learning banner (`banner-calculator*.png`) | student home | Replaced by a gradient banner and an original SVG learning trail (`trail-banner.svg`). |
| Hero (`hero-sketched-reference-hq.png`, 744 KB) | landing | Kept the artwork, converted to WebP (58 KB), rounded to sit in the layout. |
| — | login (student / teacher), empty states, Bell Ringer | New SVGs: `student-learning.svg`, `teacher-insights.svg`, `empty-trail.svg`, `bell-ringer.svg`. |
| Other generated PNGs (unused variants) | none | Removed from `frontend/` (still in the original folder). |

Claude Design was not available in this environment, so no assets were produced with it; all new
illustrations are hand-written SVG. If the owner wants Claude Design versions, export them at the
same file names and aspect ratios (subject art 3:2, login art 16:11, trail banner 18:11).

### Motion
Framer Motion only: page transitions (fade/slide, 0.28 s), staggered card entrances, card hover
lift, an animated active-nav indicator, animated mastery bars and counters (counting from the
previous value, exact final value), question transitions and answer feedback, segmented practice
progress, hint and citation reveals, Buddy typing indicator, Bell Ringer expand/collapse and share
bars, heatmap cell entrance on filter changes, cycle-status and alert list updates, and a short
confetti burst only when a topic estimate first reaches mastery. All motion uses transform and
opacity, and `prefers-reduced-motion` is respected (`MotionConfig reducedMotion="user"` plus a CSS
override; counters jump straight to their value).

### Responsive and accessibility
Mobile bottom navigation, two-column subject cards on phones, stacked teacher cards, horizontally
scrollable heatmap and tables with a sticky first column, wrapped labels instead of truncation,
zoom allowed, skip link, visible focus rings, labelled form fields, radio/checkbox roles for
answers, `role="meter"` with text values for mastery bars, live regions for feedback and Buddy,
and a keyboard-operable heatmap grid.

## Bugs found and fixed while testing
- Page transitions mounted the next page twice (an `<Outlet>` inside the exiting animated
  element), so an answer submitted during the transition was lost; fixed by capturing the outlet
  per route. Found by the end-to-end test.
- Heading colour overrode the white text on the Continue Learning banner.
- An 18px horizontal overflow on the mobile Bell Ringer page (a non-wrapping toggle).
- Truncated stat labels and a crowded teacher top bar on phones.
- Buddy showed raw `**bold**` markdown and numbered sources 1–3 while the answer cited E1/E2/E4.

## Verification
- Frontend: TypeScript strict build clean; 53 unit tests (contract, format, components, login,
  landing); 6 end-to-end browser journeys plus 1 live-model Buddy test, all passing.
- Backend: full suite 1005 passed, 1 skipped; Ruff clean; OpenAPI 40 paths.
- Visual: every page at the four viewports, two refinement passes; the automated overflow check
  reports no horizontal overflow after the fixes.

## Known limitations
- No lesson notes exist in the demo content, so topic pages show an honest empty "Learn" section
  and the old "worked examples" page was retired.
- The backend does not reveal the correct answer to students after a wrong attempt, so practice
  feedback says "not quite" and offers a retry or a Buddy hint rather than showing the key.
- Alerts, support plans, chat history and saved Bell-Ringer cycles depend on proposed migrations
  0002–0004; on a backend without them they show "not available yet".
- Demo data is sparse (each topic has evidence from only a few learners), so the Bell-Ringer
  thresholds are set low for the demo (coverage 30%); they are configurable.
- The local model can take tens of seconds per Buddy answer and often abstains on narrow
  questions; that is the intended behaviour when evidence is thin.
