# AI Based Adaptive Learning Path Generator

An AI-powered web app that generates a personalized, phase-wise learning roadmap for a
learner's goal, tracks skill mastery from quiz performance, adapts the roadmap when a
learner is struggling (or ready to move faster), and provides a context-aware AI tutor
chatbot grounded in the learner's own progress.

## Features

- Goal-based, LLM-generated learning roadmaps (phases, resources, projects)
- Skill-gap analysis against a learner's stated goal and current skills
- Phase-end adaptive quizzes that update per-skill mastery (up or down)
- An adaptive recommendation engine that inserts a remedial review phase when a learner
  is struggling, or flags when they're ready to move faster
- An AI tutor chatbot with live access to the learner's goal, current phase, mastery,
  and quiz history — not a generic Q&A bot
- Dashboard with progress, mastery breakdown, and "pick up where you left off"
- JWT authentication with email-based password reset

## Tech Stack

**Frontend:** React (Vite)
**Backend:** FastAPI (Python)
**Database:** SQLite (via SQLAlchemy)
**LLM:** [Groq](https://console.groq.com) API using `openai/gpt-oss-120b` for roadmap generation, quizzes, skill extraction, and tutor chat
**Mastery model:** Bayesian Knowledge Tracing (fixed parameters, see Known Limitations)
**Skill matching:** sentence-transformer embeddings with cosine similarity (`all-MiniLM-L6-v2`
by default) — matches learner-stated or LLM-extracted skills against the skill catalogue
semantically, so phrasing differences and abbreviations (e.g. "JS" vs "JavaScript") still match
**Resource discovery:** Tavily API

## Prerequisites

- Python 3.11+
- Node.js 18+
- A [Groq](https://console.groq.com) API key. Set `GROQ_API_KEY` in your `.env` file;
  `GROQ_MODEL` defaults to `openai/gpt-oss-120b`.
- (Optional) A [Tavily](https://tavily.com) API key — used for live resource discovery

## Setup

### Backend

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# then fill in .env — set SECRET_KEY to a real random value and add GROQ_API_KEY
# (see the comment in .env.example for how to generate one)

uvicorn app.main:app --reload
```

> **First-time setup only:** the "Build Your Learning Plan" goal dropdown reads from a
> `goals` table that starts empty on a fresh database. Seed it once with:
> ```
> python scripts/migrate_csv_to_db.py
> ```
> This populates the goal/skill catalog from `dataset/*.csv`. Safe to re-run — it skips
> rows that already exist. You only need to do this once per database, not on every
> `git pull`.

> First run will download the sentence-transformer model (~90 MB) from Hugging Face —
> needs internet access once, then it's cached locally. `pip install` itself also
> pulls in PyTorch, which is a large download (700 MB+); this is normal.

Backend runs at `http://localhost:8000`. Interactive API docs at `http://localhost:8000/docs`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:5173`.

## Environment Variables

See `.env.example` for the full list with explanations. Nothing is required to get a
basic instance running except `SECRET_KEY` — Groq, Tavily, and YouTube keys are all
optional fallbacks/enhancements, not hard requirements, and the app degrades gracefully
without them (password reset just logs the link instead of emailing it if SMTP isn't
configured, for example).

## Project Structure

```
app/
  routes/       FastAPI route handlers (thin — delegate to services)
  services/     Business logic (roadmap generation, quizzes, adaptive engine, chat, etc.)
  db/           SQLAlchemy models and database setup
  models/       Pydantic request/response schemas
  utils/        Config, security, logging
frontend/
  src/pages/       Top-level routed pages
  src/components/  Shared UI components
  src/api/         Backend API client functions
scripts/        One-off maintenance/migration scripts
```

## Known Limitations / In Progress

- Quiz difficulty adapts one level up/down from the learner's profile default based on
  the latest quiz score for the phase (`adaptive_service.get_quiz_difficulty`); it does
  not yet scale continuously with per-skill mastery
- Mastery is tracked per skill with Bayesian Knowledge Tracing
  (`skill_extraction.bkt_update`) using fixed, hand-set parameters (initial P(L)=0.20,
  p_learn=0.15, p_guess=0.20, p_slip=0.10). These have **not** been fitted to data or
  validated
- Quiz questions are LLM-generated and their correctness is not verified; if generation
  fails, a deterministic fallback quiz is used whose scores still feed BKT
- Automated tests cover validation, BKT direction, the path planner, the research
  metrics and the experiment harness; there are no tests for the roadmap/adaptive
  services against a live LLM
- The embedding model runs on CPU by default (no GPU-specific setup); fine for a
  minor project's scale, but batch operations over a very large skill catalogue would
  benefit from GPU inference

## LLM-first validated roadmap generation

Roadmap generation uses an LLM-first proposal followed by deterministic validation
when `USE_LLM_FIRST_VALIDATED_ROADMAP=true` (the default). The LLM proposes phases,
skills and project ideas; the validator checks skill IDs, duplicates, mastery and
prerequisite order before the roadmap is returned.

- **Curated goals** use the full reviewed skill IDs in
  `dataset/goal_curricula.json` as the allowed goal scope (not potentially stale
  or sparse local `GoalSkill` rows). For validation, the prerequisite graph is
  restricted to those curriculum skills so unrelated cross-domain edges in the
  legacy global graph cannot expand a curated roadmap.
- **Uncurated goals** use the target skills mapped to the goal plus their prerequisite
  closure in the skill graph. This preserves the ability to insert foundations that
  are required for custom goals.
- For both routes, goal-scoped, time-decayed BKT mastery is used when available, and
  already mastered skills are omitted. Skills below `PLANNER_WEAK_THRESHOLD` are
  labelled `learn`; intermediate mastery levels are labelled `review`.
- If LLM-first generation fails, curated goals fall back to their reviewed curriculum.
  Uncurated goals fall back to the existing graph planner (`USE_PATH_PLANNER=true`),
  followed by the possession-based topological plan if needed.

The validator guarantees consistency with the supplied graph, not that the graph
itself is pedagogically correct. Keep the curated curricula as the source of truth
for each goal's intended skill scope. The offline research experiments evaluate the
planner module on synthetic profiles; they do not validate live learner outcomes.

## Research experiments

`experiments/` contains the harness for the study comparing LLM-only generation with
prerequisite-aware, rule-based planning. See `experiments/README.md`.

## Operational hardening: migrations, rate limits, background generation, and streaming

### Database schema lifecycle

The API no longer creates database tables on application startup. Schema changes are managed through Alembic; run `alembic upgrade head` as an explicit deployment/release step against a fresh database before starting the API. Test fixtures may create their isolated test schema directly.

**Existing databases created by the old `create_all` startup may not have an `alembic_version` table. Back up the database and compare the schema with the migration chain before adopting a baseline. Do not run `alembic upgrade head` blindly on such a database**: the initial migration can try to recreate existing tables. Stamp an existing database only after verifying that it already contains every change represented by the revision being stamped.

### Shared rate limiting

Rate limits are grouped by action (authentication, chat, roadmap generation, and quiz generation/submission) rather than raw URL. In development/test, the fallback is process-local. In production, configure `RATE_LIMIT_REDIS_URL` so atomic counters are shared across API workers, for example `redis://localhost:6379/0`, and install the `redis` dependency from `requirements.txt`. The service fails closed if the configured shared backend is unavailable.

### Roadmap generation and tutor streaming

Both roadmap generation endpoints return a queued job (`202 Accepted`); the client starts the job and polls `/roadmap/generation-jobs/{job_id}` until `completed` or `failed`. The current queue runner uses FastAPI background tasks and a persisted job row; it is asynchronous from the browser's perspective but not a durable external queue if the API process is terminated mid-generation. The tutor supports `POST /chat/stream` with Server-Sent Events; `POST /chat` remains available for non-streaming clients.

### API-level tests

Install `requirements.txt`, then run `python -m pytest -q tests/test_api_hardening.py tests/test_rate_limit_routing.py`. These exercise protected auth behavior, login cookie creation, quiz generation, adaptive recommendations, SSE output, queued roadmap generation, and route-bucket matching.
