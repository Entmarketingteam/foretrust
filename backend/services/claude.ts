// Foretrust lead AI — Gemini Ultra CLI (primary) or ENT Agent Server / Claude (fallback)

import type { LeadSearchResults } from './search.js';
import type { MapsEntity } from './maps.js';
import { isGeminiCliAvailable, runGeminiPrompt, parseJsonWithRepair } from './gemini-cli.js';

const AGENT_SERVER_URL = process.env.AGENT_SERVER_URL || 'https://ent-agent-server-production.up.railway.app';

export interface ScoreRationale {
  production_fit: string;
  owner_operator_signal: string;
  sale_leaseback_fit: string;
  nnn_fit: string;
  qpp_fit: string;
}

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
  production_fit?: number;
  owner_operator_signal?: number;
  sale_leaseback_fit?: number;
  nnn_fit?: number;
  qpp_fit?: number;
  confidence?: number;
  score_rationale?: ScoreRationale;
  maps_entity?: MapsEntity;
  ai_provider?: 'gemini-cli' | 'claude';
}

export type LeadInput = {
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
};

export type InterpretContext = {
  searchResults?: LeadSearchResults;
  mapsEntity?: MapsEntity | null;
};

export async function interpretLead(lead: LeadInput, context?: InterpretContext): Promise<LeadInterpretation> {
  if (isGeminiCliAvailable()) {
    const interp = await interpretLeadGemini(lead, context);
    interp.ai_provider = 'gemini-cli';
    return interp;
  }
  const interp = await interpretLeadClaude(lead);
  interp.ai_provider = 'claude';
  return interp;
}

async function interpretLeadGemini(lead: LeadInput, context?: InterpretContext): Promise<LeadInterpretation> {
  const prompt = buildLeadInterpretationPrompt(lead, context);
  const raw = runGeminiPrompt(prompt, { timeoutMs: 300000 });
  const parsed = parseJsonWithRepair<LeadInterpretation>(raw);
  if (context?.mapsEntity) parsed.maps_entity = context.mapsEntity;
  if (!parsed.interpreted_at) parsed.interpreted_at = new Date().toISOString();
  return parsed;
}

async function interpretLeadClaude(lead: LeadInput): Promise<LeadInterpretation> {
  const apiKey = process.env.AGENT_SERVER_API_KEY;
  if (!apiKey) throw new Error('AGENT_SERVER_API_KEY not set (and Gemini CLI OAuth not configured)');

  const prompt = buildLeadInterpretationPrompt(lead);
  const text = await agentServerComplete(prompt);
  return parseJson<LeadInterpretation>(text);
}

function buildLeadFields(lead: LeadInput): string[] {
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

  return fields;
}

function buildLeadInterpretationPrompt(lead: LeadInput, context?: InterpretContext): string {
  const fields = buildLeadFields(lead);
  const researchBlock = context?.searchResults?.answer
    ? `WEB RESEARCH SUMMARY:\n${context.searchResults.answer}\n\nSOURCES:\n${
        context.searchResults.results.map(r => `- ${r.title}: ${r.url}\n  ${r.snippet}`).join('\n') || 'none'
      }\n\n`
    : '';

  const mapsBlock = context?.mapsEntity
    ? `GOOGLE MAPS ENTITY:\n${JSON.stringify(context.mapsEntity, null, 2)}\n\n`
    : '';

  const useMaScores = isGeminiCliAvailable() || Boolean(context?.searchResults);

  const scoreFields = useMaScores
    ? `
  "production_fit": 0,
  "owner_operator_signal": 0,
  "sale_leaseback_fit": 0,
  "nnn_fit": 0,
  "qpp_fit": 0,
  "confidence": 0,
  "score_rationale": {
    "production_fit": "string",
    "owner_operator_signal": "string",
    "sale_leaseback_fit": "string",
    "nnn_fit": "string",
    "qpp_fit": "string"
  },`
    : '';

  const scoreInstructions = useMaScores
    ? `
Also score 0-5 (0=none, 5=strong, default 3 if thin evidence):
- production_fit: manufacturing/processing/industrial ops at site (not pure retail/office)
- owner_operator_signal: owner likely operates business on-site
- sale_leaseback_fit: distress/maturity/capital needs favor SLB
- nnn_fit: single-tenant, clear use, long-term occupancy
- qpp_fit: fit for qualified purchaser / direct buyer program
- confidence: evidence completeness

Use Google Search in your tools when web research summary is missing or thin.`
    : '';

  return `You are a commercial real estate origination analyst for Central Kentucky owner-operators (manufacturing, food processing, industrial services). Target sale-leaseback (SLB), NNN, and qualified purchaser program (QPP) opportunities.

Analyze the lead. Focus on owner entity type, owner-operator likelihood, industry, years in business, and lead potential (hot/warm/cold).${scoreInstructions}

Lead Data:
${fields.join('\n')}

${researchBlock}${mapsBlock}Return ONLY a JSON object (no markdown fences):
{
  "owner_type": "LLC",
  "owner_operator_likelihood": "high",
  "likely_industry": "string",
  "business_category": "string",
  "years_in_business_estimate": null,
  "years_in_business_basis": "string",
  "lead_potential": "hot",
  "opportunity_summary": "string",
  "key_signals": ["string"],
  "contact_strategy": "string",${scoreFields}
  "interpreted_at": "${new Date().toISOString()}"
}`;
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

export async function generateSlbThesis(
  lead: LeadInput,
  searchResults: LeadSearchResults,
  existingInterpretation?: Partial<LeadInterpretation> | null
): Promise<SlbThesis> {
  if (isGeminiCliAvailable()) {
    const prompt = buildSlbPrompt(lead, searchResults, existingInterpretation);
    const raw = runGeminiPrompt(prompt, { timeoutMs: 420000 });
    return parseJsonWithRepair<SlbThesis>(raw);
  }

  const apiKey = process.env.AGENT_SERVER_API_KEY;
  if (!apiKey) throw new Error('AGENT_SERVER_API_KEY not set');

  const prompt = buildSlbPrompt(lead, searchResults, existingInterpretation);
  const text = await agentServerComplete(prompt);
  return parseJson<SlbThesis>(text);
}

function buildSlbPrompt(
  lead: LeadInput,
  search: LeadSearchResults,
  interp: Partial<LeadInterpretation> | null | undefined
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
    `Owner-Operator: ${interp.owner_operator_likelihood || 'unknown'}`,
    `Industry: ${interp.likely_industry || 'unknown'}`,
    interp.production_fit != null ? `production_fit: ${interp.production_fit}/5` : '',
    interp.sale_leaseback_fit != null ? `sale_leaseback_fit: ${interp.sale_leaseback_fit}/5` : '',
    interp.opportunity_summary ? `Prior Analysis: ${interp.opportunity_summary}` : '',
  ].filter(Boolean).join('\n') : 'No prior analysis available.';

  const searchBlock = search.results.length > 0
    ? search.results.map(r => `- [${r.title}](${r.url})\n  ${r.snippet}`).join('\n\n')
    : 'No web results found.';

  const answerBlock = search.answer ? `Web Research Summary:\n${search.answer}\n\n` : '';

  const searchHint = isGeminiCliAvailable()
    ? 'Use Google Search to verify or expand findings if results are thin.\n\n'
    : '';

  return `You are a sale-leaseback (SLB) investment origination specialist for owner-occupied commercial real estate in Kentucky.

Write a compelling SLB thesis: WHY this owner might entertain a sale-leaseback now (unlock equity, debt relief, estate planning, distress, etc.).

${searchHint}LEAD DATA:
${fields.join('\n')}

AI ANALYSIS:
${interpBlock}

${answerBlock}WEB RESEARCH RESULTS:
${searchBlock}

Return ONLY a JSON object (no markdown):
{
  "intro": "3-4 sentence narrative",
  "motivation_factors": ["4-6 evidence-based reasons"],
  "years_at_location_estimate": null,
  "years_at_location_basis": "string",
  "industry_trend_context": "string",
  "building_case": "string",
  "news_signals": [{"headline": "string", "url": "string", "relevance": "string"}],
  "motivation_score": "high",
  "key_conversation_opener": "string",
  "researched_at": "${new Date().toISOString()}"
}`;
}

async function agentServerComplete(prompt: string): Promise<string> {
  const apiKey = process.env.AGENT_SERVER_API_KEY!;
  const response = await fetch(`${AGENT_SERVER_URL}/complete`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`,
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
  return data.text;
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
