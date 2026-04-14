# Foretrust — CLAUDE.md

## What It Does
AI-powered real estate deal analysis platform. Ingests property listings via a Python scraper service, runs them through AI analysis pipelines, and surfaces actionable deal intelligence through a Node.js/Express REST API. Both services run on Railway with a shared Supabase (Postgres) database.

## Tech Stack

| Layer | Tech |
|---|---|
| Backend API | Node.js + Express + TypeScript |
| Scraper | Python (FastAPI), Playwright, Supabase |
| Database | Supabase (Postgres) |
| AI | OpenAI (deal analysis) |
| Secrets | Doppler (`foretrust` + `foretrust-scraper` projects) |
| Deploy | Railway (Dockerfile builds), Vercel (frontend — not yet built) |

## Key File Paths

```
foretrust/
├── backend/
│   ├── server.ts          # Express app entry point
│   ├── routes/            # deals.ts, leads.ts, search.ts
│   ├── services/          # claude.ts, openai.ts, scraper.ts, database.ts, contact.ts
│   ├── db/schema.sql      # Supabase schema — run this first
│   └── package.json
├── scraper-service/
│   ├── app/main.py        # FastAPI entry point (uvicorn app.main:app)
│   ├── exports/           # Volume-mounted export directory
│   └── pyproject.toml
├── supabase/
│   └── migrations/        # DB migration files
├── docs/
│   ├── DEPLOYMENT.md      # Full deploy guide
│   ├── PRD.md
│   └── TDD.md
├── docker-compose.yml
└── railway.json
```

## How to Run Locally

```bash
# Terminal 1: Scraper service (port 8000)
cd scraper-service
pip install -r requirements.txt
playwright install chromium
doppler run --project foretrust-scraper --config dev -- uvicorn app.main:app --reload --port 8000

# Terminal 2: Node backend (port 3001)
cd backend
npm install
doppler run --project foretrust --config dev -- npm run dev
```

Or via Docker Compose:
```bash
export DOPPLER_TOKEN=dp.st.your_service_token
docker-compose up --build
```

Run backend tests: `cd backend && npm test`

## API Routes

All API routes are under `/api/foretrust`.

```
GET  /api/foretrust/         → endpoint index
GET  /api/foretrust/health   → Railway healthcheck
GET  /api/foretrust/leads/runs  → last 20 scraper run statuses
```

## Deploy (Railway)

- Two Railway services in same project: `backend` (root=`backend`) and `scraper-service` (root=`scraper-service`)
- Each service gets only `DOPPLER_TOKEN` as an env var — all other secrets pulled from Doppler
- `SCRAPER_SERVICE_URL` in Doppler = `http://scraper-service.railway.internal:8000` (private networking)
- Scraper service has a volume mount at `/app/exports`
- Healthchecks: backend → `/api/foretrust/health`, scraper → `/health`

## Environment Variables (via Doppler)

| Variable | Description |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key (bypasses RLS) |
| `OPENAI_API_KEY` | For deal analysis |
| `SCRAPER_SERVICE_URL` | Internal URL of Python scraper |
| `SCRAPER_SHARED_TOKEN` | Shared auth secret between services |
| `SCRAPER_TIMEOUT_MS` | Default: 30000 |
| `ALLOWED_ORIGINS` | CORS origins (open in dev if unset) |

## Gotchas

- Scraper service should NOT be publicly accessible — only backend calls it internally via Railway private networking.
- Apply `backend/db/schema.sql` to Supabase before first deploy.
- Doppler has two separate projects: `foretrust` (backend) and `foretrust-scraper` (scraper service). Don't mix them up.
- Railway auto-deploys from GitHub are unreliable for this multi-service setup; manual `railway up` may be needed.
- Frontend (React + Vercel) is planned but not yet built.
- `CAPTCHA_DAILY_BUDGET_USD` in Doppler controls spend on CAPTCHA solving — the solver auto-halts at the limit.
