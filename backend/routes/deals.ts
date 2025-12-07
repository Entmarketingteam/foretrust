// Foretrust Deals API Routes
import { Router, Request, Response } from 'express';
import * as db from '../services/database.js';
import * as openai from '../services/openai.js';

const router = Router();

// List all deals with filters
router.get('/', async (req: Request, res: Response) => {
  try {
    const { status, tenant, market, limit, offset } = req.query;
    const deals = await db.listDeals({
      status: status as string,
      tenant: tenant as string,
      market: market as string,
      limit: limit ? parseInt(limit as string) : undefined,
      offset: offset ? parseInt(offset as string) : undefined
    });
    res.json({ success: true, data: deals });
  } catch (error) {
    console.error('Error listing deals:', error);
    res.status(500).json({ success: false, error: 'Failed to list deals' });
  }
});

// Get single deal with all data
router.get('/:dealId', async (req: Request, res: Response) => {
  try {
    const { dealId } = req.params;
    const dealData = await db.getCompleteDeal(dealId);

    if (!dealData.deal) {
      return res.status(404).json({ success: false, error: 'Deal not found' });
    }

    res.json({ success: true, data: dealData });
  } catch (error) {
    console.error('Error getting deal:', error);
    res.status(500).json({ success: false, error: 'Failed to get deal' });
  }
});

// Create new deal
router.post('/', async (req: Request, res: Response) => {
  try {
    const { name, sourceType, sourceUrl } = req.body;

    if (!name || !sourceType) {
      return res.status(400).json({
        success: false,
        error: 'name and sourceType are required'
      });
    }

    const deal = await db.createDeal({
      name,
      source_type: sourceType,
      source_url: sourceUrl
    });

    res.status(201).json({ success: true, data: deal });
  } catch (error) {
    console.error('Error creating deal:', error);
    res.status(500).json({ success: false, error: 'Failed to create deal' });
  }
});

// Delete deal
router.delete('/:dealId', async (req: Request, res: Response) => {
  try {
    const { dealId } = req.params;
    const deleted = await db.deleteDeal(dealId);

    if (!deleted) {
      return res.status(404).json({ success: false, error: 'Deal not found' });
    }

    res.json({ success: true, message: 'Deal deleted' });
  } catch (error) {
    console.error('Error deleting deal:', error);
    res.status(500).json({ success: false, error: 'Failed to delete deal' });
  }
});

// Ingest document content (parse OM/URL)
router.post('/:dealId/ingest', async (req: Request, res: Response) => {
  try {
    const { dealId } = req.params;
    const { documentContent, manualData } = req.body;

    const deal = await db.getDeal(dealId);
    if (!deal) {
      return res.status(404).json({ success: false, error: 'Deal not found' });
    }

    let parsedData: openai.ParsedDealData;

    if (manualData) {
      // Use manually provided data
      parsedData = manualData;
    } else if (documentContent) {
      // Parse document using OpenAI
      parsedData = await openai.parseDocument(documentContent);
    } else {
      return res.status(400).json({
        success: false,
        error: 'Either documentContent or manualData is required'
      });
    }

    // Save parsed data to database
    const [propertyAttrs, leaseTerms] = await Promise.all([
      db.upsertPropertyAttributes(dealId, {
        address_line1: parsedData.addressLine1 || undefined,
        city: parsedData.city || undefined,
        state: parsedData.state || undefined,
        postal_code: parsedData.postalCode || undefined,
        property_type: parsedData.propertyType || undefined,
        building_sqft: parsedData.buildingSqft || undefined,
        land_acres: parsedData.landAcres || undefined,
        year_built: parsedData.yearBuilt || undefined,
        clear_height_ft: parsedData.clearHeightFt || undefined,
        dock_doors: parsedData.dockDoors || undefined,
        drive_in_doors: parsedData.driveInDoors || undefined
      }),
      db.upsertLeaseTerms(dealId, {
        tenant_name: parsedData.tenantName || undefined,
        lease_type: parsedData.leaseType || undefined,
        lease_start_date: parsedData.leaseStartDate || undefined,
        lease_end_date: parsedData.leaseEndDate || undefined,
        base_rent_annual: parsedData.baseRentAnnual || undefined,
        rent_psf: parsedData.rentPsf || undefined,
        rent_escalations: parsedData.rentEscalations,
        options: parsedData.options
      })
    ]);

    // Update deal status
    await db.updateDealStatus(dealId, 'ingested');

    res.json({
      success: true,
      data: {
        parsedData,
        propertyAttributes: propertyAttrs,
        leaseTerms
      }
    });
  } catch (error) {
    console.error('Error ingesting deal:', error);
    res.status(500).json({ success: false, error: 'Failed to ingest deal' });
  }
});

// Enrich deal data
router.post('/:dealId/enrich', async (req: Request, res: Response) => {
  try {
    const { dealId } = req.params;

    const deal = await db.getDeal(dealId);
    if (!deal) {
      return res.status(404).json({ success: false, error: 'Deal not found' });
    }

    // Get existing property and lease data
    const [propertyAttrs, leaseTerms] = await Promise.all([
      db.getPropertyAttributes(dealId),
      db.getLeaseTerms(dealId)
    ]);

    if (!propertyAttrs && !leaseTerms) {
      return res.status(400).json({
        success: false,
        error: 'Deal must be ingested before enrichment'
      });
    }

    // Build input for enrichment
    const inputData = {
      address: propertyAttrs ? {
        addressLine1: propertyAttrs.address_line1,
        city: propertyAttrs.city,
        state: propertyAttrs.state,
        postalCode: propertyAttrs.postal_code
      } : null,
      tenantName: leaseTerms?.tenant_name,
      propertyType: propertyAttrs?.property_type,
      buildingSqft: propertyAttrs?.building_sqft,
      yearBuilt: propertyAttrs?.year_built
    };

    // Call OpenAI for enrichment
    const enrichmentData = await openai.enrichDeal(inputData as openai.ParsedDealData);

    // Save enrichment data
    const enrichment = await db.upsertEnrichment(dealId, {
      geocode: enrichmentData.geocode,
      market: enrichmentData.market,
      tenant: enrichmentData.tenant
    });

    // Update property attributes with geocode
    if (enrichmentData.geocode.latitude && enrichmentData.geocode.longitude) {
      await db.upsertPropertyAttributes(dealId, {
        latitude: enrichmentData.geocode.latitude,
        longitude: enrichmentData.geocode.longitude
      });
    }

    // Update deal status
    await db.updateDealStatus(dealId, 'enriched');

    res.json({ success: true, data: enrichment });
  } catch (error) {
    console.error('Error enriching deal:', error);
    res.status(500).json({ success: false, error: 'Failed to enrich deal' });
  }
});

// Underwrite deal
router.post('/:dealId/underwrite', async (req: Request, res: Response) => {
  try {
    const { dealId } = req.params;
    const { purchasePrice } = req.body; // Optional override

    const deal = await db.getDeal(dealId);
    if (!deal) {
      return res.status(404).json({ success: false, error: 'Deal not found' });
    }

    // Get all deal data
    const [propertyAttrs, leaseTerms, enrichment] = await Promise.all([
      db.getPropertyAttributes(dealId),
      db.getLeaseTerms(dealId),
      db.getEnrichment(dealId)
    ]);

    // Build comprehensive input for underwriting
    const inputData = {
      property: propertyAttrs,
      lease: leaseTerms,
      enrichment: enrichment,
      purchasePrice: purchasePrice || null
    };

    // Call OpenAI for underwriting
    const underwritingResult = await openai.underwriteDeal(inputData);

    // Save scores and financials
    const [scores, financials] = await Promise.all([
      db.upsertScores(dealId, {
        lci_score: underwritingResult.scores.lciScore,
        tenant_credit_score: underwritingResult.scores.tenantCreditScore,
        downside_score: underwritingResult.scores.downsideScore,
        market_depth_score: underwritingResult.scores.marketDepthScore,
        overall_score: underwritingResult.scores.overallScore,
        risk_flags: underwritingResult.scores.riskFlags
      }),
      db.upsertFinancials(dealId, {
        purchase_price: underwritingResult.financials.purchasePrice,
        noi_year1: underwritingResult.financials.noiYear1,
        cap_rate: underwritingResult.financials.capRate,
        ltv_assumed: underwritingResult.financials.ltvAssumed,
        interest_rate: underwritingResult.financials.interestRate,
        io_years: underwritingResult.financials.ioYears,
        amort_years: underwritingResult.financials.amortYears,
        exit_cap_rate: underwritingResult.financials.exitCapRate,
        hold_period_years: underwritingResult.financials.holdPeriodYears,
        levered_irr: underwritingResult.financials.leveredIrr,
        unlevered_irr: underwritingResult.financials.unleveredIrr,
        dscr_min: underwritingResult.financials.dscrMin,
        cash_on_cash_year1: underwritingResult.financials.cashOnCashYear1,
        cash_on_cash_avg: underwritingResult.financials.cashOnCashAvg
      })
    ]);

    // Update deal status
    await db.updateDealStatus(dealId, 'underwritten');

    res.json({
      success: true,
      data: {
        scores,
        financials
      }
    });
  } catch (error) {
    console.error('Error underwriting deal:', error);
    res.status(500).json({ success: false, error: 'Failed to underwrite deal' });
  }
});

// Generate IC Memo
router.post('/:dealId/memo', async (req: Request, res: Response) => {
  try {
    const { dealId } = req.params;

    const deal = await db.getDeal(dealId);
    if (!deal) {
      return res.status(404).json({ success: false, error: 'Deal not found' });
    }

    // Get complete deal data
    const dealData = await db.getCompleteDeal(dealId);

    // Generate memo using OpenAI
    const memoContent = await openai.generateMemo(dealData);

    // Extract recommendation from memo
    let recommendation: 'approve' | 'approve_with_conditions' | 'decline' | undefined;
    const memoLower = memoContent.toLowerCase();
    if (memoLower.includes('**approve with conditions**') || memoLower.includes('approve with conditions')) {
      recommendation = 'approve_with_conditions';
    } else if (memoLower.includes('**approve**') || memoLower.includes('# recommendation\n')) {
      if (memoLower.includes('decline')) {
        recommendation = 'decline';
      } else {
        recommendation = 'approve';
      }
    }

    // Save memo
    const memo = await db.createMemo(dealId, {
      content_markdown: memoContent,
      recommendation
    });

    // Update deal status
    await db.updateDealStatus(dealId, 'memo_generated');

    res.json({ success: true, data: memo });
  } catch (error) {
    console.error('Error generating memo:', error);
    res.status(500).json({ success: false, error: 'Failed to generate memo' });
  }
});

// Get score explainability
router.get('/:dealId/explain', async (req: Request, res: Response) => {
  try {
    const { dealId } = req.params;

    const dealData = await db.getCompleteDeal(dealId);
    if (!dealData.deal) {
      return res.status(404).json({ success: false, error: 'Deal not found' });
    }

    if (!dealData.scores) {
      return res.status(400).json({
        success: false,
        error: 'Deal must be underwritten first'
      });
    }

    const explainability = await openai.explainScores(dealData);

    res.json({ success: true, data: explainability });
  } catch (error) {
    console.error('Error explaining scores:', error);
    res.status(500).json({ success: false, error: 'Failed to explain scores' });
  }
});

// Run full pipeline (ingest → enrich → underwrite → memo)
router.post('/:dealId/pipeline', async (req: Request, res: Response) => {
  try {
    const { dealId } = req.params;
    const { documentContent, manualData, purchasePrice } = req.body;

    const deal = await db.getDeal(dealId);
    if (!deal) {
      return res.status(404).json({ success: false, error: 'Deal not found' });
    }

    const startTime = Date.now();
    const results: Record<string, unknown> = {};

    // Step 1: Ingest
    let parsedData: openai.ParsedDealData;
    if (manualData) {
      parsedData = manualData;
    } else if (documentContent) {
      parsedData = await openai.parseDocument(documentContent);
    } else {
      return res.status(400).json({
        success: false,
        error: 'Either documentContent or manualData is required'
      });
    }

    await Promise.all([
      db.upsertPropertyAttributes(dealId, {
        address_line1: parsedData.addressLine1 || undefined,
        city: parsedData.city || undefined,
        state: parsedData.state || undefined,
        postal_code: parsedData.postalCode || undefined,
        property_type: parsedData.propertyType || undefined,
        building_sqft: parsedData.buildingSqft || undefined,
        land_acres: parsedData.landAcres || undefined,
        year_built: parsedData.yearBuilt || undefined,
        clear_height_ft: parsedData.clearHeightFt || undefined,
        dock_doors: parsedData.dockDoors || undefined,
        drive_in_doors: parsedData.driveInDoors || undefined
      }),
      db.upsertLeaseTerms(dealId, {
        tenant_name: parsedData.tenantName || undefined,
        lease_type: parsedData.leaseType || undefined,
        lease_start_date: parsedData.leaseStartDate || undefined,
        lease_end_date: parsedData.leaseEndDate || undefined,
        base_rent_annual: parsedData.baseRentAnnual || undefined,
        rent_psf: parsedData.rentPsf || undefined,
        rent_escalations: parsedData.rentEscalations,
        options: parsedData.options
      })
    ]);
    results.parsed = parsedData;

    // Step 2: Enrich
    const enrichmentData = await openai.enrichDeal(parsedData);
    await db.upsertEnrichment(dealId, {
      geocode: enrichmentData.geocode,
      market: enrichmentData.market,
      tenant: enrichmentData.tenant
    });
    if (enrichmentData.geocode.latitude && enrichmentData.geocode.longitude) {
      await db.upsertPropertyAttributes(dealId, {
        latitude: enrichmentData.geocode.latitude,
        longitude: enrichmentData.geocode.longitude
      });
    }
    results.enrichment = enrichmentData;

    // Step 3: Underwrite
    const underwritingInput = {
      ...parsedData,
      enrichment: enrichmentData,
      purchasePrice: purchasePrice || parsedData.purchasePrice
    };
    const underwritingResult = await openai.underwriteDeal(underwritingInput);
    await Promise.all([
      db.upsertScores(dealId, {
        lci_score: underwritingResult.scores.lciScore,
        tenant_credit_score: underwritingResult.scores.tenantCreditScore,
        downside_score: underwritingResult.scores.downsideScore,
        market_depth_score: underwritingResult.scores.marketDepthScore,
        overall_score: underwritingResult.scores.overallScore,
        risk_flags: underwritingResult.scores.riskFlags
      }),
      db.upsertFinancials(dealId, {
        purchase_price: underwritingResult.financials.purchasePrice,
        noi_year1: underwritingResult.financials.noiYear1,
        cap_rate: underwritingResult.financials.capRate,
        ltv_assumed: underwritingResult.financials.ltvAssumed,
        interest_rate: underwritingResult.financials.interestRate,
        io_years: underwritingResult.financials.ioYears,
        amort_years: underwritingResult.financials.amortYears,
        exit_cap_rate: underwritingResult.financials.exitCapRate,
        hold_period_years: underwritingResult.financials.holdPeriodYears,
        levered_irr: underwritingResult.financials.leveredIrr,
        unlevered_irr: underwritingResult.financials.unleveredIrr,
        dscr_min: underwritingResult.financials.dscrMin,
        cash_on_cash_year1: underwritingResult.financials.cashOnCashYear1,
        cash_on_cash_avg: underwritingResult.financials.cashOnCashAvg
      })
    ]);
    results.underwriting = underwritingResult;

    // Step 4: Generate Memo
    const dealData = await db.getCompleteDeal(dealId);
    const memoContent = await openai.generateMemo(dealData);

    let recommendation: 'approve' | 'approve_with_conditions' | 'decline' | undefined;
    const memoLower = memoContent.toLowerCase();
    if (memoLower.includes('approve with conditions')) {
      recommendation = 'approve_with_conditions';
    } else if (memoLower.includes('decline')) {
      recommendation = 'decline';
    } else if (memoLower.includes('approve')) {
      recommendation = 'approve';
    }

    const memo = await db.createMemo(dealId, {
      content_markdown: memoContent,
      recommendation
    });
    results.memo = memo;

    // Update final status
    await db.updateDealStatus(dealId, 'memo_generated');

    const processingTime = Date.now() - startTime;

    res.json({
      success: true,
      data: {
        ...results,
        processingTimeMs: processingTime,
        processingTimeSec: Math.round(processingTime / 1000)
      }
    });
  } catch (error) {
    console.error('Error running pipeline:', error);
    res.status(500).json({ success: false, error: 'Failed to run pipeline' });
  }
});

// Portfolio insights
router.get('/portfolio/insights', async (req: Request, res: Response) => {
  try {
    const deals = await db.listDeals({ limit: 100 });

    if (deals.length === 0) {
      return res.json({
        success: true,
        data: {
          message: 'No deals found for analysis'
        }
      });
    }

    const insights = await openai.analyzePortfolio(deals);
    res.json({ success: true, data: insights });
  } catch (error) {
    console.error('Error analyzing portfolio:', error);
    res.status(500).json({ success: false, error: 'Failed to analyze portfolio' });
  }
});

export default router;
