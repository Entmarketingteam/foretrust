# Foretrust

Foretrust is an AI-powered real estate deal analysis platform. It ingests property listings via a Python scraper service, runs them through AI analysis pipelines, and surfaces actionable deal intelligence through a Node.js backend API and dashboard. Both services run on Railway with a shared Supabase database.

## Architecture

| Service | Stack | Deployment |
|---------|-------|------------|
| `backend/` | Node.js + Express + TypeScript | Railway |
| `scraper-service/` | Python (FastAPI or similar) | Railway |
| Database | Supabase (Postgres) | Supabase |

The backend handles all API requests and AI analysis. The scraper-service handles property data ingestion and is called internally via `SCRAPER_SERVICE_URL`. Both services authenticate with each other using `SCRAPER_SHARED_TOKEN`.

## Local Development

**Backend**

```bash
cd backend
npm install
cp .env.example .env   # fill in vars below
npm run dev            # runs with tsx watch
```

**Scraper Service**

```bash
cd scraper-service
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --port 8001
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | Supabase service role key (bypasses RLS) |
| `OPENAI_API_KEY` | Yes | OpenAI API key for deal analysis |
| `PORT` | No | Backend port (default: `3001`) |
| `SCRAPER_SERVICE_URL` | Yes | Internal URL of the Python scraper service |
| `SCRAPER_SHARED_TOKEN` | Yes | Shared secret between backend and scraper |
| `SCRAPER_TIMEOUT_MS` | No | Scraper request timeout in ms (default: `30000`) |
| `ALLOWED_ORIGINS` | No | Comma-separated CORS origins (open in dev if unset) |
| `RATE_LIMIT_MAX` | No | Max requests per window per IP (default: `100`) |
| `RATE_LIMIT_WINDOW_MS` | No | Rate limit window in ms (default: `60000`) |

## Lead scraper (KY distressed pipeline)

Runs from repo root with **Doppler** (`foretrust-scraper` / `dev`). Never commit real `.env` secrets.

**One-time Supabase:** apply pending SQL migrations so PDF metadata persists (fixes `ft_clerk_documents` upsert 404):

```bash
cd ~/Desktop/foretrust
# If Supabase CLI is linked to this project:
doppler run --project foretrust-scraper --config dev -- supabase db push
# Or paste `supabase/migrations/20260525100000_ft_clerk_documents.sql` in the Supabase SQL editor and run once.
```

**Common jobs:**

| Goal | Command |
|------|---------|
| Portal LP / deep search (per county) | `ECCLIX_COUNTIES=scott bash scripts/run-portal-intel.sh` |
| Scenario library (24h-style) | `bash scripts/run-scenario-library-24h.sh` |
| Party intel (ESTATE OF, Orchard, etc.) | `bash scripts/run-party-intel-24h.sh` |
| PVA batch (Scott + Woodford) | `bash scripts/run-pva-batch-all.sh` |
| Parallel exports (no eCCLIX) | `bash scripts/run-parallel-enrichment.sh` |

Operator playbooks: `docs/ECCLIX-24H-RUN-QUEUE.md`, `docs/VETERAN-WHOLESALER-PLAYBOOK.md`, `docs/SIGNAL-INTEL-STACK.md`.

## API Overview

All routes are mounted under `/api/foretrust`. Send a `GET /api/foretrust/` request to see the full list of available endpoints with descriptions.

```
GET  /api/foretrust/          → endpoint index
GET  /health                  → Railway healthcheck
```
