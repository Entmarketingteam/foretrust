// Foretrust Leads API Routes
// Bridges the Node backend to the Python scraper service
import { Router, Request, Response } from 'express';
import * as db from '../services/database.js';
import { triggerScraperRun } from '../services/scraper.js';
import { interpretLead, generateSlbThesis } from '../services/claude.js';
import { researchLead } from '../services/search.js';
import { enrichLeadContact } from '../services/contact.js';
import { parseNonNegativeInt } from '../utils/params.js';

const router = Router();

// List leads with filters
router.get('/', async (req: Request, res: Response) => {
  try {
    const { vertical, source_key, jurisdiction, lead_type, hot_score_min, limit, offset } = req.query;
    const leads = await db.listLeads({
      vertical: vertical as string,
      source_key: source_key as string,
      jurisdiction: jurisdiction as string,
      lead_type: lead_type as string,
      hot_score_min: parseNonNegativeInt(hot_score_min as string | undefined, undefined, 100),
      limit: parseNonNegativeInt(limit as string | undefined, 50, 1000),
      offset: parseNonNegativeInt(offset as string | undefined, 0),
    });
    res.json({ success: true, data: leads });
  } catch (error) {
    console.error('Error listing leads:', error);
    res.status(500).json({ success: false, error: 'Failed to list leads' });
  }
});

// Get single lead detail
router.get('/runs', async (req: Request, res: Response) => {
  try {
    const { limit } = req.query;
    const runs = await db.listLeadRuns(parseNonNegativeInt(limit as string | undefined, 20, 1000) as number);
    res.json({ success: true, data: runs });
  } catch (error) {
    console.error('Error listing runs:', error);
    res.status(500).json({ success: false, error: 'Failed to list runs' });
  }
});

// Export leads as CSV
router.get('/export.csv', async (req: Request, res: Response) => {
  try {
    const { vertical, source_key, jurisdiction, lead_type, hot_score_min } = req.query;
    const leads = await db.listLeads({
      vertical: vertical as string,
      source_key: source_key as string,
      jurisdiction: jurisdiction as string,
      lead_type: lead_type as string,
      hot_score_min: parseNonNegativeInt(hot_score_min as string | undefined, undefined, 100),
      limit: 10000,
      offset: 0,
    });

    // Build CSV
    const escapeCsv = (val: unknown) => {
      const str = String(val ?? '');
      if (str.includes('"') || str.includes(',') || str.includes('\n')) {
        return `"${str.replace(/"/g, '""')}"`;
      }
      return str;
    };
    const headers = [
      'hot_score', 'lead_type', 'vertical', 'owner_name', 'property_address',
      'mailing_address', 'city', 'state', 'postal_code', 'parcel_number',
      'building_sqft', 'year_built', 'estimated_value', 'case_id',
      'case_filed_date', 'jurisdiction', 'source_key', 'scraped_at',
    ];
    const csvRows = [headers.join(',')];
    for (const lead of leads) {
      const row = headers.map(h => {
        const val = (lead as unknown as Record<string, unknown>)[h];
        if (val === null || val === undefined) return '';
        return escapeCsv(val);
      });
      csvRows.push(row.join(','));
    }

    res.setHeader('Content-Type', 'text/csv');
    res.setHeader('Content-Disposition', 'attachment; filename=leads_export.csv');
    res.send(csvRows.join('\n'));
  } catch (error) {
    console.error('Error exporting leads:', error);
    res.status(500).json({ success: false, error: 'Failed to export leads' });
  }
});

// Get single lead
router.get('/:leadId', async (req: Request, res: Response) => {
  try {
    const { leadId } = req.params;
    const lead = await db.getLead(leadId);
    if (!lead) {
      return res.status(404).json({ success: false, error: 'Lead not found' });
    }
    res.json({ success: true, data: lead });
  } catch (error) {
    console.error('Error getting lead:', error);
    res.status(500).json({ success: false, error: 'Failed to get lead' });
  }
});

// Trigger a scraper run
router.post('/scrape', async (req: Request, res: Response) => {
  try {
    const { source_key, params } = req.body;
    if (!source_key) {
      return res.status(400).json({ success: false, error: 'source_key is required' });
    }

    const result = await triggerScraperRun(source_key, params || {});
    res.json({ success: true, data: result });
  } catch (error) {
    console.error('Error triggering scraper:', error);
    res.status(500).json({ success: false, error: 'Failed to trigger scraper run' });
  }
});

// Promote a lead to a deal
router.post('/:leadId/promote', async (req: Request, res: Response) => {
  try {
    const { leadId } = req.params;
    const { runPipeline } = req.body;

    const lead = await db.getLead(leadId);
    if (!lead) {
      return res.status(404).json({ success: false, error: 'Lead not found' });
    }

    // Create a deal from the lead
    const deal = await db.createDeal({
      name: `${lead.owner_name || 'Unknown'} - ${lead.property_address || lead.jurisdiction || ''}`.trim(),
      source_type: 'url',
    });

    // Link the lead to the deal
    await db.promoteLead(leadId, deal.id);

    // Populate property attributes from the lead data
    if (lead.property_address || lead.building_sqft) {
      await db.upsertPropertyAttributes(deal.id, {
        address_line1: lead.property_address || undefined,
        city: lead.city || undefined,
        state: lead.state || undefined,
        postal_code: lead.postal_code || undefined,
        building_sqft: lead.building_sqft || undefined,
        year_built: lead.year_built || undefined,
        parcel_number: lead.parcel_number || undefined,
      });
    }

    // Update deal status to ingested since we have property data
    await db.updateDealStatus(deal.id, 'ingested');

    res.json({
      success: true,
      data: {
        deal,
        promoted_from_lead: leadId,
        message: runPipeline
          ? 'Deal created. Use POST /deals/:id/pipeline to run full analysis.'
          : 'Deal created from lead.',
      },
    });
  } catch (error) {
    console.error('Error promoting lead:', error);
    res.status(500).json({ success: false, error: 'Failed to promote lead' });
  }
});

// Research + generate SLB thesis for a lead
router.post('/:leadId/slb-research', async (req: Request, res: Response) => {
  try {
    const { leadId } = req.params;
    const lead = await db.getLead(leadId);
    if (!lead) {
      return res.status(404).json({ success: false, error: 'Lead not found' });
    }

    // Run web research and SLB thesis generation in sequence
    // (research results feed directly into thesis prompt)
    const searchResults = await researchLead({
      owner_name: lead.owner_name,
      property_address: lead.property_address,
      city: lead.city,
      state: lead.state,
      jurisdiction: lead.jurisdiction,
      lead_type: lead.lead_type,
      building_sqft: lead.building_sqft,
      year_built: lead.year_built,
      ai_interpretation: lead.ai_interpretation ? {
        likely_industry: lead.ai_interpretation.likely_industry,
        business_category: lead.ai_interpretation.business_category,
      } : null,
    });

    const thesis = await generateSlbThesis(lead, searchResults, lead.ai_interpretation || null);
    await db.updateLeadSlbThesis(leadId, thesis);

    const updated = { ...lead, slb_thesis: thesis };
    res.json({
      success: true,
      data: updated,
      meta: { search_source: searchResults.source, queries_run: searchResults.queries_run },
    });
  } catch (error) {
    console.error('Error generating SLB thesis:', error);
    res.status(500).json({ success: false, error: 'Failed to generate SLB thesis' });
  }
});

// Interpret a lead with Claude AI (owner type, industry, opportunity summary)
router.post('/:leadId/interpret', async (req: Request, res: Response) => {
  try {
    const { leadId } = req.params;
    const lead = await db.getLead(leadId);
    if (!lead) {
      return res.status(404).json({ success: false, error: 'Lead not found' });
    }

    const interpretation = await interpretLead(lead);
    await db.updateLeadInterpretation(leadId, interpretation);

    // Merge interpretation back into the lead object for the response
    const updated = { ...lead, ai_interpretation: interpretation };
    res.json({ success: true, data: updated });
  } catch (error) {
    console.error('Error interpreting lead:', error);
    res.status(500).json({ success: false, error: 'Failed to interpret lead' });
  }
});

// Enrich contact intelligence for a lead (Apollo + Findymail + SOS web lookup)
router.post('/:leadId/contact-intel', async (req: Request, res: Response) => {
  try {
    const { leadId } = req.params;
    const lead = await db.getLead(leadId);
    if (!lead) {
      return res.status(404).json({ success: false, error: 'Lead not found' });
    }

    const intel = await enrichLeadContact({
      owner_name: lead.owner_name,
      property_address: lead.property_address,
      city: lead.city,
      state: lead.state,
      jurisdiction: lead.jurisdiction,
    });

    await db.updateLeadContactIntel(leadId, intel);

    const updated = { ...lead, contact_intel: intel };
    res.json({
      success: true,
      data: updated,
      meta: { sources_used: intel.sources_used, contacts_found: intel.contacts.length },
    });
  } catch (error) {
    console.error('Error enriching contact intel:', error);
    res.status(500).json({ success: false, error: 'Failed to enrich contact intel' });
  }
});

// Bulk interpret leads (up to 20 at a time, skips already-interpreted)
router.post('/interpret-batch', async (req: Request, res: Response) => {
  try {
    const { limit = 20, force = false } = req.body;
    const leads = await db.listLeads({ limit: Math.min(limit, 20), offset: 0 });
    const targets = force ? leads : leads.filter(l => !l.ai_interpretation);

    let interpreted = 0;
    let failed = 0;

    // Process concurrently in batches of 5
    const batchSize = 5;
    for (let i = 0; i < targets.length; i += batchSize) {
      const batch = targets.slice(i, i + batchSize);
      await Promise.allSettled(
        batch.map(async (lead) => {
          try {
            const interp = await interpretLead(lead);
            await db.updateLeadInterpretation(lead.id, interp);
            interpreted++;
          } catch {
            failed++;
          }
        })
      );
    }

    res.json({ success: true, data: { interpreted, failed, total: targets.length } });
  } catch (error) {
    console.error('Error in batch interpret:', error);
    res.status(500).json({ success: false, error: 'Batch interpret failed' });
  }
});

export default router;
