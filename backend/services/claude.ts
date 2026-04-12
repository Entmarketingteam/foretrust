// Foretrust Claude AI Service
// Routes through the ENT Agent Server proxy (Max subscription, no API key burn).
// Endpoint: POST https://ent-agent-server-production.up.railway.app/complete
// Auth: Bearer AGENT_SERVER_API_KEY

const AGENT_SERVER_URL = process.env.AGENT_SERVER_URL || 'https://ent-agent-server-production.up.railway.app';

export interface LeadInterpretation {
  owner_type: 'LLC' | 'individual' | 'trust' | 'corporate' | 'government' | 'unknown';
  owner_operator_likelihood: 'high' | 'medium' | 'low';
  likely_industry: string;
  business_category: string;
  years_in_business_estimate: number | null;
  years_in_business_basis: string;
  lead_potential: 'hot' | 'warm' | 'cold';
  opportunity_summary: string;
  key_signals: string[];
  contact_strategy: string;
  interpreted_at: string;
}

export async function interpretLead(lead: {
  owner_name?: string | null;
  property_address?: string | null;
  mailing_address?: string | null;
  city?: string | null;
  state?: string | null;
  postal_code?: string | null;
  jurisdiction?: string | null;
  lead_type?: string | null;
  building_sqft?: number | null;
  unit_count?: number | null;
  year_built?: number | null;
  estimated_value?: number | null;
  case_id?: string | null;
  case_filed_date?: string | null;
  parcel_number?: string | null;
  source_key?: string | null;
  hot_score?: number | null;
  raw_payload?: object | null;
}): Promise<LeadInterpretation> {
  const apiKey = process.env.AGENT_SERVER_API_KEY;
  if (!apiKey) throw new Error('AGENT_SERVER_API_KEY not set');

  const prompt = buildLeadInterpretationPrompt(lead);

  const response = await fetch(`${AGENT_SERVER_URL}/complete`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${apiKey}`,
    },
    body: JSON.stringify({ prompt }),
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`Agent server error: ${response.status} — ${err}`);
  }

  const data = await response.json() as { text: string; returncode: number; stderr: string };
  if (data.returncode !== 0) {
    throw new Error(`Claude CLI error (rc=${data.returncode}): ${data.stderr}`);
  }

  return parseInterpretation(data.text);
}

function buildLeadInterpretationPrompt(lead: Parameters<typeof interpretLead>[0]): string {
  const currentYear = new Date().getFullYear();
  const fields: string[] = [];

  if (lead.owner_name) fields.push(`Owner Name: ${lead.owner_name}`);
  if (lead.property_address) fields.push(`Property Address: ${lead.property_address}`);
  if (lead.city || lead.state) fields.push(`City/State: ${[lead.city, lead.state, lead.postal_code].filter(Boolean).join(', ')}`);
  if (lead.jurisdiction) fields.push(`County/Jurisdiction: ${lead.jurisdiction}`);
  if (lead.lead_type) fields.push(`Lead Type: ${lead.lead_type.replace(/_/g, ' ')}`);
  if (lead.source_key) fields.push(`Data Source: ${lead.source_key}`);
  if (lead.building_sqft) fields.push(`Building Size: ${lead.building_sqft.toLocaleString()} sqft`);
  if (lead.unit_count) fields.push(`Units: ${lead.unit_count}`);
  if (lead.year_built) fields.push(`Year Built: ${lead.year_built} (${currentYear - lead.year_built} years old)`);
  if (lead.estimated_value) fields.push(`Estimated Value: $${lead.estimated_value.toLocaleString()}`);
  if (lead.case_id) fields.push(`Case ID: ${lead.case_id}`);
  if (lead.case_filed_date) fields.push(`Case Filed: ${lead.case_filed_date}`);
  if (lead.hot_score != null) fields.push(`Hot Score: ${lead.hot_score}/100`);
  if (lead.mailing_address && lead.mailing_address !== lead.property_address) {
    fields.push(`Mailing Address (owner): ${lead.mailing_address}`);
  }

  // Include useful raw_payload fields if present
  if (lead.raw_payload && typeof lead.raw_payload === 'object') {
    const raw = lead.raw_payload as Record<string, unknown>;
    const interesting = [
      'business_name', 'tenant_name', 'naics_code', 'sic_code',
      'use_code', 'property_use', 'land_use', 'zoning', 'description',
      'filing_type', 'case_type', 'property_class',
    ].filter(k => raw[k]);
    for (const k of interesting) {
      fields.push(`${k.replace(/_/g, ' ')}: ${raw[k]}`);
    }
  }

  return `You are a commercial real estate intelligence analyst specializing in distressed property leads in Kentucky.

Analyze the following lead and return a JSON object with your assessment. Focus on:
1. Whether the owner is an LLC, individual, trust, or corporate entity (detect from naming patterns: "LLC", "Inc", "Corp", "Holdings", "Properties", "Enterprises", trust language, etc.)
2. Owner-operator likelihood — an LLC with a business-name suggests owner-operator; a "Holdings" LLC or individual with mismatched mailing address suggests passive investor
3. Industry/business type operating at the property (infer from company name, property type, building size, zoning)
4. Years in business estimate — use year_built, case filing dates, or company name patterns as signals
5. Lead opportunity potential: hot = motivated seller with clear distress + owner-operator; warm = some signals; cold = unclear or passive investor

Lead Data:
${fields.join('\n')}

Return ONLY a JSON object (no markdown fences, no explanation text before or after):
{
  "owner_type": "LLC",
  "owner_operator_likelihood": "high",
  "likely_industry": "Auto Repair",
  "business_category": "Independent Auto Service Shop",
  "years_in_business_estimate": 22,
  "years_in_business_basis": "Building built in 2003, likely in operation since then",
  "lead_potential": "hot",
  "opportunity_summary": "An LLC-owned auto repair shop facing foreclosure proceedings. Owner-operator pattern suggests the business owner also owns the real estate — a classic distressed NNN opportunity with motivated seller dynamics.",
  "key_signals": ["LLC name matches trade name pattern", "Probate case filed 2024", "Building built 2003 = aging structure", "Owner mailing = property address (occupant-owner)"],
  "contact_strategy": "Direct mail to the LLC registered agent address. Lead with sale-leaseback framing — owner keeps business running while unlocking equity.",
  "interpreted_at": "${new Date().toISOString()}"
}`;
}

function parseInterpretation(raw: string): LeadInterpretation {
  return parseJson<LeadInterpretation>(raw);
}

// ── SLB Thesis ───────────────────────────────────────────────────────────────

export interface SlbThesis {
  intro: string;
  motivation_factors: string[];
  years_at_location_estimate: number | null;
  years_at_location_basis: string;
  industry_trend_context: string;
  building_case: string;
  news_signals: Array<{ headline: string; url: string; relevance: string }>;
  motivation_score: 'high' | 'medium' | 'low';
  key_conversation_opener: string;
  researched_at: string;
}

import type { LeadSearchResults } from './search.js';

export async function generateSlbThesis(
  lead: {
    owner_name?: string | null;
    property_address?: string | null;
    city?: string | null;
    state?: string | null;
    jurisdiction?: string | null;
    lead_type?: string | null;
    building_sqft?: number | null;
    unit_count?: number | null;
    year_built?: number | null;
    estimated_value?: number | null;
    case_id?: string | null;
    case_filed_date?: string | null;
  },
  searchResults: LeadSearchResults,
  existingInterpretation?: {
    owner_type?: string;
    owner_operator_likelihood?: string;
    likely_industry?: string;
    business_category?: string;
    years_in_business_estimate?: number | null;
    opportunity_summary?: string;
  } | null
): Promise<SlbThesis> {
  const apiKey = process.env.AGENT_SERVER_API_KEY;
  if (!apiKey) throw new Error('AGENT_SERVER_API_KEY not set');

  const prompt = buildSlbPrompt(lead, searchResults, existingInterpretation);

  const response = await fetch(`${AGENT_SERVER_URL}/complete`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${apiKey}`,
    },
    body: JSON.stringify({ prompt }),
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`Agent server error: ${response.status} — ${err}`);
  }

  const data = await response.json() as { text: string; returncode: number; stderr: string };
  if (data.returncode !== 0) {
    throw new Error(`Claude CLI error (rc=${data.returncode}): ${data.stderr}`);
  }

  return parseJson<SlbThesis>(data.text);
}

function buildSlbPrompt(
  lead: Parameters<typeof generateSlbThesis>[0],
  search: LeadSearchResults,
  interp: Parameters<typeof generateSlbThesis>[2]
): string {
  const currentYear = new Date().getFullYear();
  const fields: string[] = [];

  if (lead.owner_name) fields.push(`Owner: ${lead.owner_name}`);
  if (lead.property_address) fields.push(`Address: ${lead.property_address}`);
  if (lead.city || lead.state) fields.push(`Location: ${[lead.city, lead.jurisdiction, lead.state].filter(Boolean).join(', ')}`);
  if (lead.lead_type) fields.push(`Lead Type: ${lead.lead_type.replace(/_/g, ' ')}`);
  if (lead.building_sqft) fields.push(`Building: ${lead.building_sqft.toLocaleString()} sqft`);
  if (lead.year_built) fields.push(`Year Built: ${lead.year_built} (${currentYear - lead.year_built} yrs old)`);
  if (lead.estimated_value) fields.push(`Est. Value: $${lead.estimated_value.toLocaleString()}`);
  if (lead.case_id) fields.push(`Case ID: ${lead.case_id}`);
  if (lead.case_filed_date) fields.push(`Filed: ${lead.case_filed_date}`);
  if (lead.unit_count) fields.push(`Units: ${lead.unit_count}`);

  const interpBlock = interp ? [
    `Owner Type: ${interp.owner_type || 'unknown'}`,
    `Owner-Operator Likelihood: ${interp.owner_operator_likelihood || 'unknown'}`,
    `Industry: ${interp.likely_industry || 'unknown'}`,
    `Business Category: ${interp.business_category || 'unknown'}`,
    interp.years_in_business_estimate ? `Est. Years in Business: ${interp.years_in_business_estimate}` : '',
    interp.opportunity_summary ? `Prior Analysis: ${interp.opportunity_summary}` : '',
  ].filter(Boolean).join('\n') : 'No prior analysis available.';

  const searchBlock = search.results.length > 0
    ? search.results.map(r => `- [${r.title}](${r.url})\n  ${r.snippet}`).join('\n\n')
    : 'No web results found.';

  const answerBlock = search.answer
    ? `Web Research Summary:\n${search.answer}\n\n`
    : '';

  return `You are a sale-leaseback (SLB) investment origination specialist focused on owner-occupied commercial real estate in Kentucky.

Your job: Given research on a distressed property owner, write a compelling hypothetical SLB thesis explaining WHY this specific owner might be willing to entertain a sale-leaseback right now.

A sale-leaseback = the owner sells their building to an investor and immediately signs a long-term lease to stay and continue operating. Key motivations: unlock equity, improve balance sheet, eliminate debt, fund growth, avoid bankruptcy, estate planning, etc.

LEAD DATA:
${fields.join('\n')}

AI ANALYSIS:
${interpBlock}

${answerBlock}WEB RESEARCH RESULTS:
${searchBlock}

Based on ALL of the above, return ONLY a JSON object (no markdown, no preamble):
{
  "intro": "3-4 sentence compelling narrative intro. Explain who this owner is, what situation they're in, and the core SLB opportunity. Be specific to this lead — reference actual signals found in the research.",
  "motivation_factors": ["array of 4-6 specific, evidence-based reasons this owner might entertain a SLB. Reference news, business age, industry trends, building age, financial distress signals, etc."],
  "years_at_location_estimate": null or integer,
  "years_at_location_basis": "how you estimated years at this specific location — cite web results if found",
  "industry_trend_context": "1-2 sentences on why owners in THIS specific industry tend to be receptive to SLBs. Reference industry-specific cash flow pressures, capital intensity, or recent sector trends.",
  "building_case": "1-2 sentences on why the building itself (age, size, type, condition signals) supports a SLB conversation.",
  "news_signals": [{"headline": "brief headline", "url": "source url or empty string", "relevance": "why this matters for SLB"}],
  "motivation_score": "high" | "medium" | "low",
  "key_conversation_opener": "The single best first sentence to use when calling or writing this owner. Specific, relevant, not generic.",
  "researched_at": "${new Date().toISOString()}"
}`;
}

function parseJson<T>(raw: string): T {
  let cleaned = raw.trim();
  if (cleaned.startsWith('```json')) cleaned = cleaned.slice(7);
  else if (cleaned.startsWith('```')) cleaned = cleaned.slice(3);
  if (cleaned.endsWith('```')) cleaned = cleaned.slice(0, -3);
  const start = cleaned.indexOf('{');
  const end = cleaned.lastIndexOf('}');
  if (start !== -1 && end !== -1) cleaned = cleaned.slice(start, end + 1);
  return JSON.parse(cleaned.trim()) as T;
}
