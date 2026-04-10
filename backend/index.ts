// Foretrust Backend - Main Entry Point
import { Router } from 'express';
import dealsRouter from './routes/deals.js';
import leadsRouter from './routes/leads.js';

const router = Router();

// Health check
router.get('/health', (_req, res) => {
  res.json({
    status: 'healthy',
    service: 'foretrust',
    version: '1.0.0',
    timestamp: new Date().toISOString()
  });
});

// Mount routes
router.use('/deals', dealsRouter);
router.use('/leads', leadsRouter);

// API documentation
router.get('/', (_req, res) => {
  res.json({
    name: 'Foretrust API',
    version: '1.0.0',
    description: 'AI-powered real estate decision platform',
    endpoints: {
      'GET /api/foretrust/health': 'Health check',
      'GET /api/foretrust/deals': 'List all deals (with filters)',
      'POST /api/foretrust/deals': 'Create new deal',
      'GET /api/foretrust/deals/:dealId': 'Get deal with all data',
      'DELETE /api/foretrust/deals/:dealId': 'Delete deal',
      'POST /api/foretrust/deals/:dealId/ingest': 'Parse OM/document content',
      'POST /api/foretrust/deals/:dealId/enrich': 'Enrich deal with external data',
      'POST /api/foretrust/deals/:dealId/underwrite': 'Calculate scores and financials',
      'POST /api/foretrust/deals/:dealId/memo': 'Generate IC memo',
      'GET /api/foretrust/deals/:dealId/explain': 'Get score explainability',
      'POST /api/foretrust/deals/:dealId/pipeline': 'Run full pipeline (ingest→enrich→underwrite→memo)',
      'GET /api/foretrust/deals/portfolio/insights': 'Get portfolio-level insights',
      // Lead acquisition (scraper service)
      'GET /api/foretrust/leads': 'List scraped leads (filters: vertical, source_key, jurisdiction, lead_type, hot_score_min)',
      'GET /api/foretrust/leads/:leadId': 'Get single lead detail',
      'POST /api/foretrust/leads/scrape': 'Trigger a scraper run (body: {source_key, params})',
      'POST /api/foretrust/leads/:leadId/promote': 'Promote lead to a deal',
      'GET /api/foretrust/leads/runs': 'Recent scraper run audit log',
      'GET /api/foretrust/leads/export.csv': 'Export leads as CSV',
    }
  });
});

export default router;
