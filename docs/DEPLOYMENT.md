# Deployment Guide — Railway + Vercel + Doppler

## Architecture

| Component | Host | Port |
|---|---|---|
| Node backend | Railway | 3001 (public) |
| Python scraper service | Railway | 8000 (internal only) |
| Frontend (React) | Vercel | 443 (CDN) |
| Database | Supabase Cloud | — |
| Secrets | Doppler | — |

## Prerequisites

- Doppler account with projects `foretrust` and `foretrust-scraper`
- Railway account linked to the GitHub repo
- Vercel account (for frontend, when ready)
- Supabase project with schema applied (`backend/db/schema.sql`)

## Step 1: Doppler Setup

```bash
# Install Doppler CLI
brew install dopplerhq/cli/doppler  # macOS
# or: curl -Ls https://cli.doppler.com/install.sh | sh

# Login
doppler login

# Set up projects (one-time)
doppler projects create foretrust
doppler projects create foretrust-scraper

# Add all secrets (see list in plan doc section 4b)
doppler secrets set SUPABASE_URL="https://xxx.supabase.co" --project foretrust --config dev
# ... repeat for all secrets
```

## Step 2: Local Development

```bash
# Terminal 1: Scraper service
cd scraper-service
pip install -r requirements.txt
playwright install chromium
doppler run --project foretrust-scraper --config dev -- uvicorn app.main:app --reload --port 8000

# Terminal 2: Node backend
cd backend
npm install
doppler run --project foretrust --config dev -- npm run dev
```

Or use Docker Compose:

```bash
export DOPPLER_TOKEN=dp.st.your_service_token
docker-compose up --build
```

## Step 3: Railway Deployment

1. Connect the GitHub repo to Railway
2. Create two services in the same Railway project:
   - **backend**: root directory = `backend`, Dockerfile build
   - **scraper-service**: root directory = `scraper-service`, Dockerfile build
3. In each service's settings:
   - Set **only** `DOPPLER_TOKEN` as an environment variable (generate a service token from Doppler)
   - Enable private networking (scraper-service should NOT be publicly accessible)
4. Set the backend's `SCRAPER_SERVICE_URL` in Doppler to `http://scraper-service.railway.internal:8000`
5. Add a volume mount to scraper-service at `/app/exports`
6. Deploy

## Step 4: Vercel (Frontend)

1. Connect the GitHub repo to Vercel
2. Set root directory to `src/foretrust` (or wherever the React app lives)
3. Add `DOPPLER_TOKEN` as an environment variable
4. Set `VITE_API_BASE_URL` to the Railway backend's public URL
5. Deploy

## Healthchecks

- Node backend: `GET /api/foretrust/health`
- Scraper service: `GET /health`
- Railway pings these automatically; failing checks roll back the deploy

## Monitoring

- **Scraper runs**: `GET /api/foretrust/leads/runs` shows the last 20 runs with status, record counts, and errors
- **Lead quality**: Sort Google Sheet by Hot Score; anything > 70 should be called within 24 hours
- **CAPTCHA spend**: Check `CAPTCHA_DAILY_BUDGET_USD` in Doppler; the solver auto-halts at the limit
