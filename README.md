# AI-Based Adaptive Learning Path Generator

A full-stack web application that turns a learner's **goal** and **what they already know** into a
personalised, phase-wise learning roadmap, tracks **per-skill mastery** from quiz results, and
**adapts** the roadmap as the learner progresses. A progress-aware AI tutor answers questions using the
learner's own goal, current phase and quiz history.

The project also includes an offline **evaluation study** that compares LLM-only path generation with
prerequisite-aware, rule-based planning (see [Evaluation study](#evaluation-study)).

<!-- Screenshots: add images under docs/screenshots/ and reference them here, e.g.
![Roadmap page](docs/screenshots/roadmap.png) -->

---

## Table of contents

1. [Key ideas](#key-ideas)
2. [Features](#features)
3. [Architecture](#architecture)
4. [How a roadmap is generated](#how-a-roadmap-is-generated)
5. [Mastery tracking (BKT)](#mastery-tracking-bkt)
6. [The planner rules](#the-planner-rules)
7. [Quizzes and adaptation](#quizzes-and-adaptation)
8. [Tech stack](#tech-stack)
9. [Project structure](#project-structure)
10. [Data and database](#data-and-database)
11. [Getting started](#getting-started)
12. [Configuration](#configuration)
13. [API overview](#api-overview)
14. [Frontend pages](#frontend-pages)
15. [Testing](#testing)
16. [Evaluation study](#evaluation-study)
17. [Operational notes](#operational-notes)
18. [Known limitations](#known-limitations)
19. [Authors](#authors)

---

## Key ideas

- **Personalised from what you already know.** Skills you have mastered are not re-taught; skills you
  are weak in are emphasised.
- **Sound ordering.** A prerequisite graph guarantees that a skill is not scheduled before the skills it
  depends on.
- **Mastery is estimated, not assumed.** Bayesian Knowledge Tracing (BKT) updates a probability of
  mastery for each skill from every quiz answer, with time decay so unreviewed skills fade.
- **The LLM writes, the rules decide.** A language model drafts titles, durations, resources and project
  ideas, while deterministic code validates (or, in planner mode, fully decides) which skills appear,
  in what order, and whether each is a `learn` or `review` item.
- **A closed loop.** Quiz result, then BKT update, then recommendation (insert a remedial phase or move
  faster), then the roadmap changes.

## Features

**Roadmaps**
- Goal-based roadmaps with phases, skills, resources and project ideas
- 25 goals in the catalogue (for example ML Engineer, Frontend Developer, Data Engineer, Cybersecurity
  Analyst), each with a reviewed curriculum; goals outside the catalogue are supported too
- Skills you list are matched to the skill catalogue **semantically** with sentence-transformer
  embeddings, so "JS" matches "JavaScript"
- Resource discovery with Tavily web search (optional YouTube ranking), link validation, and a curated
  resource list as a fallback
- Roadmap generation runs as a queued job: the browser starts it and polls until it completes
- Version history for every roadmap, with restore; export and import as JSON; PDF progress reports

**Learning and adaptation**
- Phase-end quizzes with server-issued sessions (answers are checked on the server)
- Quiz difficulty moves one level up or down from two signals: the latest phase score and tracked BKT
  mastery (when both agree)
- An adaptive recommendation engine: insert a remedial review phase when a learner is struggling, or
  flag that they are ready to move faster
- Spaced review queue driven by time-decayed mastery
- Explain-my-answer feedback on quiz questions

**AI tutor**
- Chat tutor with live context: your goal, current phase, mastery and quiz history
- Streaming replies over Server-Sent Events (`POST /chat/stream`) and a non-streaming endpoint

**Study tools**
- Dashboard with progress, mastery breakdown, activity streaks and "pick up where you left off"
- Study planner with reminders, deadlines and an iCalendar feed (`/learning/calendar.ics`)
- Optional reminder emails
- Shareable, read-only progress links
- Resource reports (flag a broken or irrelevant resource)

**Accounts and operations**
- JWT authentication with a cookie, email-based password reset, profile and personal information pages
- Per-action rate limiting (in-memory in development, Redis in production)
- Alembic database migrations, structured logging with request IDs
- Admin endpoints to add goals and skills (restricted by `ADMIN_EMAILS`)

## Architecture

```
React 19 + Vite (frontend)
        |  HTTP / JSON  (+ Server-Sent Events for tutor streaming)
        v
FastAPI routes  --  auth, rate limiting, request IDs, CORS
        |  calls
        v
Services
  roadmap_service     orchestrates generation
  llm_service         Groq client, strict JSON handling
  roadmap_validator   checks an LLM proposal against the graph and mastery
  path_planner        deterministic prerequisite and mastery planner (pure Python)
  skill_extraction    skill matching and the BKT update
  mastery_decay       time decay of mastery, review scheduling
  adaptive_service    quiz difficulty and remedial recommendations
  quiz_service        quiz sessions and grading
  chat_service        context-aware tutor
  web_search_service  Tavily and YouTube resource discovery
        |  reads / writes
        v
SQLite via SQLAlchemy (schema managed with Alembic)
```

Routes are thin; business logic lives in `app/services/`. The planner is pure Python with no framework
imports, so the same module is used by the app and by the evaluation harness.

## How a roadmap is generated

1. **Input.** The learner picks a goal and states the skills they know. Skills are matched to the
   catalogue with embeddings.
2. **Mastery.** Each skill has a goal-scoped BKT mastery with time decay. Skills the learner reports as
   known count as mastered.
3. **Scope.** Curated goals use their reviewed curriculum as the allowed skill set (with the prerequisite
   graph restricted to those skills). Other goals use the target skills plus all their prerequisites.
4. **Proposal and validation.** The LLM proposes phases, skills and project ideas. The validator checks
   skill IDs, duplicates, mastery and prerequisite order, and repairs the proposal.
5. **Fallbacks.** If LLM generation fails, curated goals fall back to their reviewed curriculum. Other
   goals fall back to the graph planner, and then to a simple topological plan.
6. **Saved as a job.** The roadmap is stored and the browser polls `/roadmap/generation-jobs/{job_id}`.

Roadmap generation is controlled by two flags (see [Configuration](#configuration)):
`USE_LLM_FIRST_VALIDATED_ROADMAP` (default `true`) and `USE_PATH_PLANNER` (default `true`).
The validator guarantees consistency with the supplied graph, not that the graph itself is
pedagogically correct. Keep the curated curricula as the source of truth for each goal's intended scope.

## Mastery tracking (BKT)

Each answer updates the probability that a skill is known:

```
correct:  num = P * (1 - slip)      den = num + (1 - P) * guess
wrong:    num = P * slip            den = num + (1 - P) * (1 - guess)
post = num / den
P'   = post + (1 - post) * learn
```

| Parameter | Value | Meaning |
|-----------|-------|---------|
| Initial P(known) | 0.20 | starting knowledge |
| learn | 0.15 | chance of learning per answer |
| guess | 0.20 | right answer without knowing |
| slip | 0.10 | wrong answer despite knowing |

A skill counts as **mastered** at or above 0.85. Stored mastery **decays over time** with a 45-day
half-life towards a baseline of 0.20, and review intervals are capped at 30 days. These parameters are
hand-set and have not been fitted to learner data (see [Known limitations](#known-limitations)).

## The planner rules

`app/services/path_planner.py` decides which skills belong in a path, their order and their action:

| Rule | Behaviour |
|------|-----------|
| **R1** closure | Every target skill and all of its transitive prerequisites become candidates |
| **R2** order | Topological order, so no skill comes before its prerequisites |
| **R3** skip | Mastery at or above 0.85 is skipped and reported as skipped |
| **R4** action | Below 0.50: `learn`. From 0.50 up to 0.85: `review` |

Kept skills are split into at most 7 phases of about 4 skills. The planner makes no LLM call; the LLM
only elaborates titles, durations and resources (`generate_roadmap_from_plan`). Thresholds are
configurable through `PLANNER_WEAK_THRESHOLD` and `PLANNER_STRONG_THRESHOLD`.

## Quizzes and adaptation

- A quiz is issued per phase and graded on the server; every answer feeds the BKT update.
- The next quiz's difficulty changes by at most one level, only from the latest phase score and the
  phase's tracked mastery. If the two disagree, the difficulty stays level. Mastery is trusted only
  after a minimum number of labelled answers.
- After a quiz the recommendation endpoint proposes either a **remedial phase** (insert it with
  `POST /roadmap/{goal_id}/phase/{phase_index}/insert-remedial`) or a **faster pace**.
- If LLM quiz generation fails, a deterministic fallback quiz is used, and its scores still feed BKT.

## Tech stack

| Layer | Technology |
|-------|------------|
| Frontend | React 19, Vite, React Router 7, Axios, react-icons |
| Backend | FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, Uvicorn |
| Database | SQLite (default); `DATABASE_URL` allows another SQLAlchemy URL |
| LLM | [Groq](https://console.groq.com), default `openai/gpt-oss-120b` |
| Mastery | Bayesian Knowledge Tracing with time decay |
| Skill matching | `sentence-transformers` (`all-MiniLM-L6-v2`) with cosine similarity |
| Resources | Tavily search API, optional YouTube Data API |
| Auth | JWT (python-jose), bcrypt password hashing |
| Reports | ReportLab (PDF) |
| Rate limiting | In-process, or Redis in production |
| Tests | pytest, httpx / FastAPI TestClient |

## Project structure

```
.
├── app/
│   ├── main.py             FastAPI app, middleware, router registration
│   ├── routes/             thin HTTP handlers (auth, user, roadmap, chat, learning, share, admin)
│   ├── services/           business logic (planner, BKT, adaptive engine, quiz, chat, resources, ...)
│   ├── db/                 SQLAlchemy engine/session and models
│   ├── models/             Pydantic request/response schemas
│   └── utils/              config, security, logging, rate limiting, iCal, time helpers
├── frontend/               React + Vite single-page app
│   └── src/ {pages, components, api, context, hooks, styles}
├── dataset/                skills, goals, goal-skill mapping, prerequisite edges,
│                           curated curricula and curated resources
├── migrations/             Alembic migration chain
├── scripts/                seeding and maintenance scripts
├── experiments/            evaluation harness, data, logs and analysis results
├── tests/                  pytest suite
├── alembic.ini
├── requirements.txt
└── .env.example
```

## Data and database

**Catalogue (in `dataset/`)**

| File | Contents |
|------|----------|
| `skills.csv` | 229 skills with category, difficulty, estimated hours, description and aliases |
| `goals.csv` | 25 learning goals |
| `goal_skills.csv` | 370 goal-to-skill mappings with an importance level |
| `skill_dependencies.csv` | 226 prerequisite edges with a strength value |
| `goal_curricula.json` | reviewed phase-by-phase curricula for the 25 goals |
| `curated_resources.json` | hand-picked learning resources per skill |

**Database tables:** `users`, `skills`, `skill_dependencies`, `goals`, `goal_skills`, `user_skills`,
`goal_user_skills` (goal-scoped BKT mastery), `roadmaps`, `roadmap_versions`, `roadmap_generation_jobs`,
`quiz_attempts`, `quiz_question_history`, `issued_quizzes`, `review_schedules`, `study_reminders`,
`share_links`, `resource_reports`, `user_feedback`, `activity_log`, `chat_messages`.

## Getting started

### Prerequisites

- Python 3.11 or newer
- Node.js 18 or newer
- A [Groq](https://console.groq.com/keys) API key (required for roadmap generation, quizzes and the tutor)
- Optional: a [Tavily](https://tavily.com) key for live resource search, a YouTube Data API key, and SMTP
  details for real emails

### 1. Backend

```bash
python -m venv venv
# Windows (PowerShell):
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

pip install -r requirements.txt
```

`pip install` pulls in PyTorch (a large download). The first run also downloads the sentence-transformer
model (about 90 MB) from Hugging Face, so internet access is needed once.

### 2. Configure

```bash
cp .env.example .env
```

On Windows PowerShell use `Copy-Item .env.example .env`. Then edit `.env`:

- set `SECRET_KEY` to a long random value:
  `python -c "import secrets; print(secrets.token_hex(32))"`
- set `GROQ_API_KEY`

### 3. Create and seed the database

Run these once, from the repository root, on a fresh database:

```bash
alembic upgrade head
python scripts/migrate_csv_to_db.py
```

`alembic upgrade head` creates the schema. `migrate_csv_to_db.py` loads the goals and skills from
`dataset/` (25 goals, 229 skills, 226 prerequisite edges, 370 goal-skill rows). It is safe to re-run
because it skips rows that already exist.

> If you have an older database created before Alembic was introduced, back it up and compare its schema
> with the migration chain before using Alembic on it. Do not run `alembic upgrade head` blindly on such a
> database: the initial migration can try to recreate existing tables.

### 4. Run the backend

```bash
uvicorn app.main:app --reload
```

The API runs at `http://localhost:8000`, with interactive documentation at `http://localhost:8000/docs`
and a health check at `http://localhost:8000/health`.

### 5. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

The app runs at `http://localhost:5173`. The frontend talks to `http://127.0.0.1:8000` unless
`VITE_API_URL` is set.

## Configuration

All settings are read from `.env` (see `.env.example` for comments). The main ones:

| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | none | signs JWTs; set a real random value |
| `ENVIRONMENT` | `development` | outside development/test, shared rate limiting is required |
| `CORS_ORIGINS` | `http://localhost:5173,...` | allowed browser origins |
| `DATABASE_URL` | SQLite under `app/data/` | database connection |
| `GROQ_API_KEY` | none | Groq access |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | model for generation, quizzes and tutor |
| `GROQ_TIMEOUT_SECONDS`, `GROQ_QUIZ_TIMEOUT_SECONDS` | 60, 45 | request timeouts |
| `GROQ_MAX_COMPLETION_TOKENS` | 4096 | output budget |
| `GROQ_REASONING_EFFORT` | `medium` | reasoning level for reasoning models |
| `TAVILY_API_KEY` | none | live resource discovery |
| `YOUTUBE_API_KEY` | empty | optional YouTube ranking |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | skill matching model |
| `EMBEDDING_MATCH_THRESHOLD` | 0.6 | minimum similarity for a skill match |
| `USE_LLM_FIRST_VALIDATED_ROADMAP` | `true` | LLM proposal plus deterministic validation |
| `USE_PATH_PLANNER` | `true` | graph planner as fallback for uncurated goals |
| `PLANNER_WEAK_THRESHOLD` / `PLANNER_STRONG_THRESHOLD` | 0.50 / 0.85 | learn/review and skip thresholds |
| `WEB_SEARCH_CACHE_TTL_SECONDS` | 86400 | resource search cache lifetime |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM` | empty | emails; with no `SMTP_HOST`, reset links are logged to the console |
| `REMINDER_EMAILS_ENABLED` | `true` | reminder emails (needs SMTP) |
| `FRONTEND_URL` | `http://localhost:5173` | used in email links |
| `ADMIN_EMAILS` | empty | comma-separated admin accounts |
| `RATE_LIMIT_REDIS_URL` | none | shared rate limits (required in production) |

Only `SECRET_KEY` and `GROQ_API_KEY` are needed to try the core features. Tavily, YouTube and SMTP are
optional, and the app degrades gracefully without them. **Never commit `.env`.**

## API overview

Interactive documentation is available at `/docs`. Routes by group:

| Group | Prefix | Main endpoints |
|-------|--------|----------------|
| Authentication | `/auth` | `POST /register`, `/login`, `/logout`, `/forgot-password`, `/reset-password` |
| Users | `/users` | `GET /me`, `PUT /profile`, `PUT /personal-info`, `PUT /change-password`, `POST /extract-skills`, `GET /skills`, `DELETE /skills/{id}`, `GET /goals`, `GET /dashboard`, `GET /dashboard/activity`, `POST /activity/session` |
| Roadmap | `/roadmap` | `POST /generate-roadmap` (202, queued), `GET /generation-jobs/{job_id}`, `GET /saved`, `GET /{goal_id}`, `DELETE /{goal_id}`, `PATCH /{goal_id}/phase/{i}`, `POST /{goal_id}/phase/{i}/quiz`, `POST /{goal_id}/phase/{i}/quiz/submit`, `POST /{goal_id}/phase/{i}/study-notes`, `GET /{goal_id}/recommendation`, `POST /{goal_id}/phase/{i}/insert-remedial`, `GET /{goal_id}/report`, `POST /{goal_id}/complete`, `POST /feedback` |
| Tutor | `/chat` | `POST ""`, `POST /stream` (SSE), `POST /explain-answer`, `GET /history` |
| Learning tools | `/learning` | analytics, question history, review queue, reminders, deadline, e-mail preferences, share link, export / import, versions and restore, resource report, `GET /calendar.ics` |
| Sharing | `/share` | `GET /{token}` read-only progress view |
| Admin | `/admin` | `GET/POST /goals`, `GET/POST /skills` |
| Health | `/health` | service status |

## Frontend pages

| Route | Page |
|-------|------|
| `/` | landing page |
| `/login`, `/forgot-password`, `/reset-password` | authentication |
| `/home` | dashboard |
| `/onboarding` | build your learning plan (goal selection) |
| `/assess-skills`, `/my-skills` | skill assessment and your skills |
| `/roadmap`, `/roadmap/:goalId` | roadmap with phases, quizzes and the tutor |
| `/insights/:goalId` | learning insights and analytics |
| `/study-planner` | reminders, deadlines and calendar |
| `/saved-roadmaps`, `/my-reviews` | saved roadmaps and the review queue |
| `/profile` | account settings |
| `/share/:token` | shared read-only progress |

Most pages require a signed-in user.

## Testing

```bash
python -m pytest -q
```

Use `python -m pytest` (not plain `pytest`) from the repository root so the `app` and `experiments`
packages are importable. The suite has 221 tests covering the BKT maths, mastery decay, the planner and
its ablations, the roadmap validator, the LLM client and error handling, quiz integrity, rate limiting,
authentication and validation, sharing and reminders, resource search, and the experiment harness
(metrics, statistics, and an end-to-end mock pipeline). Tests do not call a real LLM.

Frontend: `cd frontend && npm run lint`.

## Evaluation study

`experiments/` contains a harness and the results of a study that compares ways of generating a path on
18 held-out **synthetic** learner profiles (beginner, intermediate, advanced, uneven, and edge cases)
across 3 goals:

| ID | Condition |
|----|-----------|
| A | LLM only |
| E | LLM with the prerequisite edges and rules in the prompt (nothing enforced) |
| D | deterministic planner decides the skills; the LLM only elaborates (the app's planner) |
| B, C | planner ablations: without mastery, and mastery filtering without the graph |

Models: `gpt-oss-120b` (main), `gpt-oss-20b` and `qwen3.6-27b` (run without thinking mode), all through
Groq. Paths were scored on three prerequisite graphs: the planner's own graph (P), and two graphs written
by other LLMs (E and E2).

**Mean mastery alignment (0 to 1, higher is better), scored on graph E**

| Model | A (LLM only) | E (LLM + rules in prompt) | D (planner) |
|-------|:-----------:|:--------------------------:|:-----------:|
| gpt-oss-120b | 0.39 | 0.82 | 0.83 |
| gpt-oss-20b | 0.41 | 0.78 | 0.83 |
| qwen3.6-27b | 0.45 | 0.48 | 0.83 |

**Mean prerequisite violation rate (%, lower is better), scored on graph E**

| Model | A | E | D |
|-------|:---:|:---:|:---:|
| gpt-oss-120b | 18.0 | 12.8 | 13.7 |
| gpt-oss-20b | 20.4 | 15.1 | 13.7 |
| qwen3.6-27b | 13.9 | 10.1 | 13.7 |

What the results support, and what they do not:

- The planner's advantage on **mastery alignment** over LLM-only paths holds across all three models and
  all three scoring graphs. LLM-only paths were about 2.5 times longer than needed (15.8 items against 6.2
  for gpt-oss-120b), and 28% of their items were skills the learner had already mastered.
- The planner's advantage on **prerequisite violations** is circular when scored on its own graph (zero by
  construction) and mostly disappears on independent graphs. On graph E2, LLM-only paths from
  gpt-oss-120b had fewer violations than the planner (7.1% against 15.8%). The planner's violations fall
  on relations where the three graphs disagree.
- A model that is given the rules in the prompt may follow them well (gpt-oss-120b) or ignore them
  (qwen3.6-27b in non-thinking mode). The planner does not depend on the model.
- The prerequisite graphs were written by LLMs and share only 43-60% of direct edges. The learners are
  synthetic. **No learning gains were measured and no real learners or human raters took part.**

The planner scores identically across models because its path does not depend on the LLM. Mastery alignment
uses the planner's own 0.85 threshold, so it shows how closely paths match a mastery state, not how well
learners learn.

Full details, commands to reproduce every table without any API calls, and the provenance of each graph and
run are in [`experiments/README.md`](experiments/README.md). The code state for the reported results is
frozen at the commit tagged `paper-v1`.

## Operational notes

**Schema lifecycle.** The API does not create tables at startup. Run `alembic upgrade head` as an explicit
release step. Test fixtures create their own isolated schema.

**Rate limiting.** Limits are grouped by action (authentication, chat, roadmap generation, quiz generation
and submission) instead of raw URL. Development and tests use a process-local fallback. In production set
`RATE_LIMIT_REDIS_URL` (for example `redis://localhost:6379/0`) so counters are shared across workers. The
service fails closed if the configured shared backend is unavailable.

**Background generation.** Both roadmap generation endpoints return `202 Accepted` with a job; the client
polls until the job is `completed` or `failed`. The queue uses FastAPI background tasks and a persisted job
row. It is asynchronous from the browser's point of view but not a durable external queue: a job is lost if
the API process stops mid-generation.

**Tutor streaming.** `POST /chat/stream` returns Server-Sent Events; `POST /chat` remains for clients that do
not stream.

**API tests.** `python -m pytest -q tests/test_api_hardening.py tests/test_rate_limit_routing.py` exercises
protected auth behaviour, login cookies, quiz generation, adaptive recommendations, SSE output, queued
roadmap generation and route-bucket matching.

**Data safety.** No user exports are committed. `.env`, local databases, logs and backups are git-ignored.
Do not commit real user data or API keys.

## Known limitations

- BKT parameters are hand-set (initial 0.20, learn 0.15, guess 0.20, slip 0.10) and have not been fitted to
  data or validated.
- Quiz difficulty moves one level at a time from the latest score and tracked mastery; it does not scale
  continuously with per-skill mastery.
- Quiz questions are LLM-generated and their correctness is not verified. If generation fails, a
  deterministic fallback quiz is used.
- The prerequisite graph is an assumption. The validator keeps a roadmap consistent with the graph; it
  cannot show that the graph is pedagogically right. The graphs used in the evaluation were written by
  LLMs, not reviewed by a domain expert.
- The evaluation uses synthetic learners. It tests alignment with a given mastery state, not learning
  outcomes, and the closed loop (quiz, mastery update, re-plan) is not evaluated.
- Roadmap generation jobs are not durable across API restarts.
- The embedding model runs on CPU by default.
- Tests do not cover the roadmap and adaptive services against a live LLM.
