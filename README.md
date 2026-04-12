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

## API Overview

All routes are mounted under `/api/foretrust`. Send a `GET /api/foretrust/` request to see the full list of available endpoints with descriptions.

```
GET  /api/foretrust/          → endpoint index
GET  /health                  → Railway healthcheck
```
