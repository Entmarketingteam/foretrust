// Foretrust Backend - Main Entry Point
import { Router } from 'express';
import dealsRouter from './routes/deals.js';

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

// Mount deals routes
router.use('/deals', dealsRouter);

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
      'GET /api/foretrust/deals/portfolio/insights': 'Get portfolio-level insights'
    }
  });
});

export default router;
