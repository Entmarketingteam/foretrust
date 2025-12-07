// Foretrust OpenAI Service
import {
  buildParsePrompt,
  buildEnrichmentPrompt,
  buildUnderwritingPrompt,
  buildMemoPrompt,
  buildPortfolioPrompt,
  buildExplainabilityPrompt
} from '../prompts/index.js';

const OPENAI_API_URL = 'https://api.openai.com/v1/chat/completions';
const DEFAULT_MODEL = 'gpt-4-turbo-preview';

interface OpenAIResponse {
  choices: Array<{
    message: {
      content: string;
    };
  }>;
}

async function callOpenAI(prompt: string, systemPrompt?: string): Promise<string> {
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) {
    throw new Error('OPENAI_API_KEY environment variable is not set');
  }

  const messages = [
    {
      role: 'system',
      content: systemPrompt || 'You are a helpful assistant that returns valid JSON responses.'
    },
    {
      role: 'user',
      content: prompt
    }
  ];

  const response = await fetch(OPENAI_API_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${apiKey}`
    },
    body: JSON.stringify({
      model: process.env.OPENAI_MODEL || DEFAULT_MODEL,
      messages,
      temperature: 0.2,
      max_tokens: 4096
    })
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`OpenAI API error: ${response.status} - ${error}`);
  }

  const data = await response.json() as OpenAIResponse;
  return data.choices[0]?.message?.content || '';
}

function parseJsonResponse<T>(response: string): T {
  // Clean up response - remove markdown code blocks if present
  let cleaned = response.trim();
  if (cleaned.startsWith('```json')) {
    cleaned = cleaned.slice(7);
  } else if (cleaned.startsWith('```')) {
    cleaned = cleaned.slice(3);
  }
  if (cleaned.endsWith('```')) {
    cleaned = cleaned.slice(0, -3);
  }
  cleaned = cleaned.trim();

  return JSON.parse(cleaned) as T;
}

// Parse OM/Document content
export interface ParsedDealData {
  addressLine1: string | null;
  city: string | null;
  state: string | null;
  postalCode: string | null;
  tenantName: string | null;
  propertyType: string | null;
  buildingSqft: number | null;
  landAcres: number | null;
  yearBuilt: number | null;
  clearHeightFt: number | null;
  dockDoors: number | null;
  driveInDoors: number | null;
  leaseType: string | null;
  leaseStartDate: string | null;
  leaseEndDate: string | null;
  baseRentAnnual: number | null;
  rentPsf: number | null;
  purchasePrice: number | null;
  rentEscalations: Array<{ year: number; bumpPct: number }>;
  options: Array<{ type: string; years: number }>;
}

export async function parseDocument(documentContent: string): Promise<ParsedDealData> {
  const prompt = buildParsePrompt(documentContent);
  const response = await callOpenAI(prompt, 'You are a real estate document parser. Return only valid JSON.');
  return parseJsonResponse<ParsedDealData>(response);
}

// Enrich deal data
export interface EnrichmentData {
  geocode: {
    latitude: number | null;
    longitude: number | null;
  };
  market: {
    submarketName: string | null;
    marketRank: number | null;
  };
  tenant: {
    industry: string | null;
    companySize: string | null;
    publicOrPrivate: string | null;
    creditImplied: string | null;
  };
}

export async function enrichDeal(parsedData: ParsedDealData): Promise<EnrichmentData> {
  const prompt = buildEnrichmentPrompt(parsedData);
  const response = await callOpenAI(prompt, 'You are a real estate data enrichment engine. Return only valid JSON.');
  return parseJsonResponse<EnrichmentData>(response);
}

// Underwrite deal
export interface UnderwritingResult {
  scores: {
    lciScore: number;
    tenantCreditScore: number;
    downsideScore: number;
    marketDepthScore: number;
    overallScore: number;
    riskFlags: string[];
  };
  financials: {
    purchasePrice: number | null;
    noiYear1: number | null;
    capRate: number | null;
    ltvAssumed: number;
    interestRate: number;
    ioYears: number;
    amortYears: number;
    exitCapRate: number;
    holdPeriodYears: number;
    leveredIrr: number;
    unleveredIrr: number;
    dscrMin: number;
    cashOnCashYear1: number;
    cashOnCashAvg: number;
  };
}

export async function underwriteDeal(dealData: object): Promise<UnderwritingResult> {
  const prompt = buildUnderwritingPrompt(dealData);
  const response = await callOpenAI(prompt, 'You are a real estate underwriting engine. Return only valid JSON.');
  return parseJsonResponse<UnderwritingResult>(response);
}

// Generate IC Memo
export async function generateMemo(dealData: object): Promise<string> {
  const prompt = buildMemoPrompt(dealData);
  const response = await callOpenAI(prompt, 'You are an investment committee memo writer. Return a well-formatted markdown document.');
  return response;
}

// Portfolio insights
export interface PortfolioInsights {
  topDeals: Array<{ dealId: string; name: string; reason: string }>;
  topByIrr: Array<{ dealId: string; name: string; irr: number }>;
  topByLocation: Array<{ dealId: string; name: string; lciScore: number }>;
  systemicRisks: string[];
  portfolioSummary: string;
}

export async function analyzePortfolio(deals: object[]): Promise<PortfolioInsights> {
  const prompt = buildPortfolioPrompt(deals);
  const response = await callOpenAI(prompt, 'You are a portfolio analyst. Return only valid JSON.');
  return parseJsonResponse<PortfolioInsights>(response);
}

// Score explainability
export interface ScoreExplainability {
  explainability: {
    lci: string;
    tenantCredit: string;
    downside: string;
    marketDepth: string;
    overall: string;
  };
}

export async function explainScores(dealData: object): Promise<ScoreExplainability> {
  const prompt = buildExplainabilityPrompt(dealData);
  const response = await callOpenAI(prompt, 'You are a score explainability engine. Return only valid JSON.');
  return parseJsonResponse<ScoreExplainability>(response);
}
