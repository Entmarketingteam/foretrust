# Foretrust Scraper Service

Automated real-estate lead acquisition service. Scrapes court records, PVA databases, GIS maps, and newspaper legal notices to find distressed property leads across Kentucky counties.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Run (all config comes from Doppler — no .env files)
doppler run --project foretrust-scraper --config dev -- uvicorn app.main:app --reload
```

## API

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Healthcheck |
| GET | `/connectors` | List registered connectors |
| POST | `/run/{source_key}` | Trigger a connector run |
| GET | `/runs` | Recent run audit log |

## Architecture

See `docs/SCRAPER.md` for the operator runbook and `docs/DEPLOYMENT.md` for Railway + Vercel + Doppler setup.

## Tests

```bash
doppler run --project foretrust-scraper --config dev -- pytest
```
