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
**LLM:** Qwen3 via [Ollama](https://ollama.com) (local), with Groq as a cloud fallback
**Skill matching:** RapidFuzz (fuzzy string matching) — a switch to sentence-transformer
embeddings is planned but not yet implemented
**Resource discovery:** Tavily API

## Prerequisites

- Python 3.11+
- Node.js 18+
- [Ollama](https://ollama.com) installed, with the models pulled locally:
  ```
  ollama pull qwen3:8b
  ollama pull qwen3:4b
  ```
- (Optional) A [Groq](https://console.groq.com) API key — used as a fallback if the
  local Ollama call fails or times out
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
# then fill in .env — at minimum set SECRET_KEY to a real random value
# (see the comment in .env.example for how to generate one)

uvicorn app.main:app --reload
```

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

- Quiz difficulty does not yet adapt to mastery level (only roadmap content does)
- Skill matching uses fuzzy string similarity (RapidFuzz); a switch to semantic
  embeddings (sentence-transformers) is planned but not yet wired in
- No automated test suite yet
- Mastery is tracked with a weighted-average heuristic; a switch to a proper Bayesian
  Knowledge Tracing model is planned
