// Foretrust Database Service - Using Supabase Client with Mock Fallback
import { createClient, SupabaseClient } from '@supabase/supabase-js';
import fetch, { RequestInit } from 'node-fetch';
import { HttpsProxyAgent } from 'https-proxy-agent';

// Supabase client
let supabase: SupabaseClient | null = null;
let useMockData = false;

// Mock data store (in-memory for demo)
const mockStore: {
  deals: Deal[];
  propertyAttributes: DealPropertyAttributes[];
  leaseTerms: DealLeaseTerms[];
  scores: DealScores[];
  financials: DealFinancials[];
  enrichment: DealEnrichment[];
  memos: DealMemo[];
} = {
  deals: [
    {
      id: 'mock-deal-001',
      organization_id: '00000000-0000-0000-0000-000000000001',
      name: 'Walgreens - Austin TX',
      status: 'memo_generated',
      source_type: 'pdf',
      created_at: '2025-11-20T10:00:00Z',
      updated_at: '2025-11-20T12:00:00Z'
    },
    {
      id: 'mock-deal-002',
      organization_id: '00000000-0000-0000-0000-000000000001',
      name: 'Dollar General - Nashville TN',
      status: 'underwritten',
      source_type: 'url',
      source_url: 'https://example.com/listing/123',
      created_at: '2025-11-18T08:00:00Z',
      updated_at: '2025-11-19T15:00:00Z'
    },
    {
      id: 'mock-deal-003',
      organization_id: '00000000-0000-0000-0000-000000000001',
      name: 'CVS Pharmacy - Phoenix AZ',
      status: 'enriched',
      source_type: 'manual',
      created_at: '2025-11-15T14:00:00Z',
      updated_at: '2025-11-16T09:00:00Z'
    }
  ],
  propertyAttributes: [
    {
      id: 'mock-prop-001',
      deal_id: 'mock-deal-001',
      address_line1: '1234 Main Street',
      city: 'Austin',
      state: 'TX',
      postal_code: '78701',
      property_type: 'Retail - NNN',
      building_sqft: 14500,
      land_acres: 1.2,
      year_built: 2018
    },
    {
      id: 'mock-prop-002',
      deal_id: 'mock-deal-002',
      address_line1: '5678 Commerce Blvd',
      city: 'Nashville',
      state: 'TN',
      postal_code: '37203',
      property_type: 'Retail - NNN',
      building_sqft: 9100,
      land_acres: 0.9,
      year_built: 2020
    },
    {
      id: 'mock-prop-003',
      deal_id: 'mock-deal-003',
      address_line1: '910 Desert Road',
      city: 'Phoenix',
      state: 'AZ',
      postal_code: '85001',
      property_type: 'Retail - NNN',
      building_sqft: 12800,
      land_acres: 1.5,
      year_built: 2015
    }
  ],
  leaseTerms: [
    {
      id: 'mock-lease-001',
      deal_id: 'mock-deal-001',
      tenant_name: 'Walgreens Co.',
      lease_type: 'Absolute NNN',
      lease_start_date: '2018-06-01',
      lease_end_date: '2038-05-31',
      base_rent_annual: 450000,
      rent_psf: 31.03
    },
    {
      id: 'mock-lease-002',
      deal_id: 'mock-deal-002',
      tenant_name: 'Dollar General Corporation',
      lease_type: 'NNN',
      lease_start_date: '2020-03-01',
      lease_end_date: '2035-02-28',
      base_rent_annual: 125000,
      rent_psf: 13.74
    },
    {
      id: 'mock-lease-003',
      deal_id: 'mock-deal-003',
      tenant_name: 'CVS Health Corporation',
      lease_type: 'NNN',
      lease_start_date: '2015-09-01',
      lease_end_date: '2030-08-31',
      base_rent_annual: 380000,
      rent_psf: 29.69
    }
  ],
  scores: [
    {
      id: 'mock-score-001',
      deal_id: 'mock-deal-001',
      overall_score: 87,
      lci_score: 92,
      tenant_credit_score: 95,
      downside_score: 78,
      market_depth_score: 83,
      risk_flags: ['Long lease term positive', 'Strong tenant credit'],
      scored_at: '2025-11-20T11:00:00Z'
    },
    {
      id: 'mock-score-002',
      deal_id: 'mock-deal-002',
      overall_score: 72,
      lci_score: 68,
      tenant_credit_score: 82,
      downside_score: 65,
      market_depth_score: 73,
      risk_flags: ['Moderate lease term', 'Secondary market'],
      scored_at: '2025-11-19T14:00:00Z'
    }
  ],
  financials: [
    {
      id: 'mock-fin-001',
      deal_id: 'mock-deal-001',
      purchase_price: 7200000,
      noi_year1: 450000,
      cap_rate: 0.0625,
      ltv_assumed: 0.65,
      interest_rate: 0.055,
      io_years: 2,
      amort_years: 25,
      exit_cap_rate: 0.07,
      hold_period_years: 7,
      levered_irr: 0.142,
      unlevered_irr: 0.078,
      dscr_min: 1.45,
      cash_on_cash_year1: 0.082
    },
    {
      id: 'mock-fin-002',
      deal_id: 'mock-deal-002',
      purchase_price: 1850000,
      noi_year1: 125000,
      cap_rate: 0.0676,
      ltv_assumed: 0.70,
      interest_rate: 0.058,
      io_years: 0,
      amort_years: 25,
      exit_cap_rate: 0.075,
      hold_period_years: 5,
      levered_irr: 0.118,
      unlevered_irr: 0.072,
      dscr_min: 1.28,
      cash_on_cash_year1: 0.065
    }
  ],
  enrichment: [],
  memos: [
    {
      id: 'mock-memo-001',
      deal_id: 'mock-deal-001',
      version: 1,
      content_markdown: `# Investment Committee Memo\n\n## Executive Summary\nWalgreens NNN property in Austin, TX presents a compelling investment opportunity with strong tenant credit and favorable lease terms.\n\n## Recommendation: APPROVE\n\n### Key Highlights\n- Investment Grade Tenant (S&P: BBB)\n- 20-year absolute NNN lease\n- 6.25% cap rate in growth market\n- Projected 14.2% levered IRR\n\n### Risk Factors\n- Retail pharmacy sector headwinds\n- E-commerce competition\n\n### Conclusion\nStrong credit tenant with long-term lease in growing Texas market. Recommend proceeding with acquisition.`,
      recommendation: 'approve',
      generated_at: '2025-11-20T12:00:00Z'
    }
  ]
};

function generateUUID(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

async function testSupabaseConnection(): Promise<boolean> {
  try {
    const supabaseUrl = process.env.VITE_SUPABASE_URL;
    const supabaseKey = process.env.VITE_SUPABASE_ANON_KEY;

    if (!supabaseUrl || !supabaseKey) return false;

    const httpsProxy = process.env.https_proxy || process.env.HTTPS_PROXY;
    const proxyAgent = httpsProxy ? new HttpsProxyAgent(httpsProxy) : undefined;

    const response = await fetch(`${supabaseUrl}/rest/v1/`, {
      headers: { 'apikey': supabaseKey },
      agent: proxyAgent
    } as RequestInit);

    // If we get 403 "Access denied", Supabase is blocked
    if (response.status === 403) {
      const text = await response.text();
      if (text === 'Access denied') return false;
    }

    return response.ok || response.status === 401;
  } catch {
    return false;
  }
}

async function getClient(): Promise<SupabaseClient | null> {
  if (useMockData) return null;

  if (!supabase) {
    const supabaseUrl = process.env.VITE_SUPABASE_URL;
    const supabaseKey = process.env.VITE_SUPABASE_ANON_KEY;

    if (!supabaseUrl || !supabaseKey) {
      console.log('🔶 No Supabase credentials, using mock data');
      useMockData = true;
      return null;
    }

    // Test connection first
    const canConnect = await testSupabaseConnection();
    if (!canConnect) {
      console.log('🔶 Supabase blocked by proxy, using mock data for demo');
      useMockData = true;
      return null;
    }

    // Create proxy agent if HTTPS_PROXY is set
    const httpsProxy = process.env.https_proxy || process.env.HTTPS_PROXY;
    const proxyAgent = httpsProxy ? new HttpsProxyAgent(httpsProxy) : undefined;

    // Custom fetch that uses the proxy
    const customFetch = (url: string | URL, init?: RequestInit) => {
      return fetch(url, {
        ...init,
        agent: proxyAgent
      } as RequestInit);
    };

    supabase = createClient(supabaseUrl, supabaseKey, {
      global: {
        fetch: customFetch as unknown as typeof globalThis.fetch
      }
    });
  }
  return supabase;
}

// Types
export interface Deal {
  id: string;
  organization_id: string;
  name: string;
  status: 'draft' | 'ingested' | 'enriched' | 'underwritten' | 'memo_generated' | 'archived';
  source_type: 'pdf' | 'url' | 'manual';
  source_url?: string;
  created_by?: string;
  created_at: string;
  updated_at: string;
}

export interface DealPropertyAttributes {
  id: string;
  deal_id: string;
  address_line1?: string;
  city?: string;
  state?: string;
  postal_code?: string;
  latitude?: number;
  longitude?: number;
  property_type?: string;
  building_sqft?: number;
  land_acres?: number;
  year_built?: number;
  clear_height_ft?: number;
  dock_doors?: number;
  drive_in_doors?: number;
  zoning?: string;
  parcel_number?: string;
  last_sale_date?: string;
  last_sale_price?: number;
}

export interface DealLeaseTerms {
  id: string;
  deal_id: string;
  tenant_name?: string;
  lease_type?: string;
  lease_start_date?: string;
  lease_end_date?: string;
  base_rent_annual?: number;
  rent_psf?: number;
  rent_escalations?: object[];
  options?: object[];
}

export interface DealScores {
  id: string;
  deal_id: string;
  lci_score?: number;
  tenant_credit_score?: number;
  downside_score?: number;
  market_depth_score?: number;
  overall_score?: number;
  risk_flags?: string[];
  scored_at?: string;
}

export interface DealFinancials {
  id: string;
  deal_id: string;
  purchase_price?: number;
  noi_year1?: number;
  cap_rate?: number;
  ltv_assumed?: number;
  interest_rate?: number;
  io_years?: number;
  amort_years?: number;
  exit_cap_rate?: number;
  hold_period_years?: number;
  levered_irr?: number;
  unlevered_irr?: number;
  dscr_min?: number;
  cash_on_cash_year1?: number;
  cash_on_cash_avg?: number;
}

export interface DealEnrichment {
  id: string;
  deal_id: string;
  geocode?: object;
  market?: object;
  tenant?: object;
  enriched_at: string;
}

export interface DealMemo {
  id: string;
  deal_id: string;
  version: number;
  content_markdown: string;
  recommendation?: 'approve' | 'approve_with_conditions' | 'decline';
  generated_at: string;
}

// Default org/user for MVP
const DEFAULT_ORG_ID = '00000000-0000-0000-0000-000000000001';
const DEFAULT_USER_ID = '00000000-0000-0000-0000-000000000001';

// Deal CRUD operations
export async function createDeal(data: {
  name: string;
  source_type: 'pdf' | 'url' | 'manual';
  source_url?: string;
  organization_id?: string;
  created_by?: string;
}): Promise<Deal> {
  const client = await getClient();

  if (!client) {
    // Mock mode
    const newDeal: Deal = {
      id: generateUUID(),
      organization_id: data.organization_id || DEFAULT_ORG_ID,
      name: data.name,
      status: 'draft',
      source_type: data.source_type,
      source_url: data.source_url,
      created_by: data.created_by || DEFAULT_USER_ID,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    };
    mockStore.deals.unshift(newDeal);
    return newDeal;
  }

  const { data: deal, error } = await client
    .from('ft_deals')
    .insert({
      name: data.name,
      source_type: data.source_type,
      source_url: data.source_url || null,
      organization_id: data.organization_id || DEFAULT_ORG_ID,
      created_by: data.created_by || DEFAULT_USER_ID
    })
    .select()
    .single();

  if (error) throw error;
  return deal;
}

export async function getDeal(id: string): Promise<Deal | null> {
  const client = await getClient();

  if (!client) {
    return mockStore.deals.find(d => d.id === id) || null;
  }

  const { data, error } = await client
    .from('ft_deals')
    .select('*')
    .eq('id', id)
    .single();

  if (error && error.code !== 'PGRST116') throw error;
  return data;
}

export async function updateDealStatus(id: string, status: Deal['status']): Promise<Deal | null> {
  const client = await getClient();

  if (!client) {
    const deal = mockStore.deals.find(d => d.id === id);
    if (deal) {
      deal.status = status;
      deal.updated_at = new Date().toISOString();
    }
    return deal || null;
  }

  const { data, error } = await client
    .from('ft_deals')
    .update({ status, updated_at: new Date().toISOString() })
    .eq('id', id)
    .select()
    .single();

  if (error) throw error;
  return data;
}

export async function listDeals(filters?: {
  organization_id?: string;
  status?: string;
  tenant?: string;
  market?: string;
  limit?: number;
  offset?: number;
}): Promise<Deal[]> {
  const client = await getClient();

  if (!client) {
    // Mock mode - return enriched deals
    let deals = mockStore.deals.filter(d =>
      d.organization_id === (filters?.organization_id || DEFAULT_ORG_ID)
    );

    if (filters?.status) {
      deals = deals.filter(d => d.status === filters.status);
    }

    // Enrich with related data
    return deals.map(deal => {
      const prop = mockStore.propertyAttributes.find(p => p.deal_id === deal.id);
      const lease = mockStore.leaseTerms.find(l => l.deal_id === deal.id);
      const scores = mockStore.scores.find(s => s.deal_id === deal.id);
      const fin = mockStore.financials.find(f => f.deal_id === deal.id);

      return {
        ...deal,
        city: prop?.city,
        state: prop?.state,
        property_type: prop?.property_type,
        tenant_name: lease?.tenant_name,
        overall_score: scores?.overall_score,
        lci_score: scores?.lci_score,
        tenant_credit_score: scores?.tenant_credit_score,
        cap_rate: fin?.cap_rate,
        noi_year1: fin?.noi_year1,
        levered_irr: fin?.levered_irr,
      };
    });
  }

  let query = client
    .from('ft_deals')
    .select(`
      *,
      ft_deal_property_attributes(city, state, property_type),
      ft_deal_lease_terms(tenant_name),
      ft_deal_scores(overall_score, lci_score, tenant_credit_score),
      ft_deal_financials(cap_rate, noi_year1, levered_irr)
    `)
    .eq('organization_id', filters?.organization_id || DEFAULT_ORG_ID)
    .order('created_at', { ascending: false });

  if (filters?.status) {
    query = query.eq('status', filters.status);
  }
  if (filters?.limit) {
    query = query.limit(filters.limit);
  }

  const { data, error } = await query;
  if (error) throw error;

  // Flatten joined data
  return (data || []).map((d: Record<string, unknown>) => ({
    ...d,
    city: (d.ft_deal_property_attributes as Record<string, unknown>)?.city,
    state: (d.ft_deal_property_attributes as Record<string, unknown>)?.state,
    property_type: (d.ft_deal_property_attributes as Record<string, unknown>)?.property_type,
    tenant_name: (d.ft_deal_lease_terms as Record<string, unknown>)?.tenant_name,
    overall_score: (d.ft_deal_scores as Record<string, unknown>)?.overall_score,
    lci_score: (d.ft_deal_scores as Record<string, unknown>)?.lci_score,
    tenant_credit_score: (d.ft_deal_scores as Record<string, unknown>)?.tenant_credit_score,
    cap_rate: (d.ft_deal_financials as Record<string, unknown>)?.cap_rate,
    noi_year1: (d.ft_deal_financials as Record<string, unknown>)?.noi_year1,
    levered_irr: (d.ft_deal_financials as Record<string, unknown>)?.levered_irr,
  }));
}

// Property Attributes
export async function upsertPropertyAttributes(dealId: string, data: Partial<DealPropertyAttributes>): Promise<DealPropertyAttributes> {
  const client = await getClient();

  if (!client) {
    const idx = mockStore.propertyAttributes.findIndex(p => p.deal_id === dealId);
    const newProp: DealPropertyAttributes = {
      id: idx >= 0 ? mockStore.propertyAttributes[idx].id : generateUUID(),
      deal_id: dealId,
      ...data
    };
    if (idx >= 0) {
      mockStore.propertyAttributes[idx] = newProp;
    } else {
      mockStore.propertyAttributes.push(newProp);
    }
    return newProp;
  }

  const { data: result, error } = await client
    .from('ft_deal_property_attributes')
    .upsert({
      deal_id: dealId,
      ...data,
      updated_at: new Date().toISOString()
    }, { onConflict: 'deal_id' })
    .select()
    .single();

  if (error) throw error;
  return result;
}

export async function getPropertyAttributes(dealId: string): Promise<DealPropertyAttributes | null> {
  const client = await getClient();

  if (!client) {
    return mockStore.propertyAttributes.find(p => p.deal_id === dealId) || null;
  }

  const { data, error } = await client
    .from('ft_deal_property_attributes')
    .select('*')
    .eq('deal_id', dealId)
    .single();

  if (error && error.code !== 'PGRST116') throw error;
  return data;
}

// Lease Terms
export async function upsertLeaseTerms(dealId: string, data: Partial<DealLeaseTerms>): Promise<DealLeaseTerms> {
  const client = await getClient();

  if (!client) {
    const idx = mockStore.leaseTerms.findIndex(l => l.deal_id === dealId);
    const newLease: DealLeaseTerms = {
      id: idx >= 0 ? mockStore.leaseTerms[idx].id : generateUUID(),
      deal_id: dealId,
      ...data
    };
    if (idx >= 0) {
      mockStore.leaseTerms[idx] = newLease;
    } else {
      mockStore.leaseTerms.push(newLease);
    }
    return newLease;
  }

  const { data: result, error } = await client
    .from('ft_deal_lease_terms')
    .upsert({
      deal_id: dealId,
      ...data,
      updated_at: new Date().toISOString()
    }, { onConflict: 'deal_id' })
    .select()
    .single();

  if (error) throw error;
  return result;
}

export async function getLeaseTerms(dealId: string): Promise<DealLeaseTerms | null> {
  const client = await getClient();

  if (!client) {
    return mockStore.leaseTerms.find(l => l.deal_id === dealId) || null;
  }

  const { data, error } = await client
    .from('ft_deal_lease_terms')
    .select('*')
    .eq('deal_id', dealId)
    .single();

  if (error && error.code !== 'PGRST116') throw error;
  return data;
}

// Scores
export async function upsertScores(dealId: string, data: Partial<DealScores>): Promise<DealScores> {
  const client = await getClient();

  if (!client) {
    const idx = mockStore.scores.findIndex(s => s.deal_id === dealId);
    const newScore: DealScores = {
      id: idx >= 0 ? mockStore.scores[idx].id : generateUUID(),
      deal_id: dealId,
      scored_at: new Date().toISOString(),
      ...data
    };
    if (idx >= 0) {
      mockStore.scores[idx] = newScore;
    } else {
      mockStore.scores.push(newScore);
    }
    return newScore;
  }

  const { data: result, error } = await client
    .from('ft_deal_scores')
    .upsert({
      deal_id: dealId,
      ...data,
      scored_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    }, { onConflict: 'deal_id' })
    .select()
    .single();

  if (error) throw error;
  return result;
}

export async function getScores(dealId: string): Promise<DealScores | null> {
  const client = await getClient();

  if (!client) {
    return mockStore.scores.find(s => s.deal_id === dealId) || null;
  }

  const { data, error } = await client
    .from('ft_deal_scores')
    .select('*')
    .eq('deal_id', dealId)
    .single();

  if (error && error.code !== 'PGRST116') throw error;
  return data;
}

// Financials
export async function upsertFinancials(dealId: string, data: Partial<DealFinancials>): Promise<DealFinancials> {
  const client = await getClient();

  if (!client) {
    const idx = mockStore.financials.findIndex(f => f.deal_id === dealId);
    const newFin: DealFinancials = {
      id: idx >= 0 ? mockStore.financials[idx].id : generateUUID(),
      deal_id: dealId,
      ...data
    };
    if (idx >= 0) {
      mockStore.financials[idx] = newFin;
    } else {
      mockStore.financials.push(newFin);
    }
    return newFin;
  }

  const { data: result, error } = await client
    .from('ft_deal_financials')
    .upsert({
      deal_id: dealId,
      ...data,
      updated_at: new Date().toISOString()
    }, { onConflict: 'deal_id' })
    .select()
    .single();

  if (error) throw error;
  return result;
}

export async function getFinancials(dealId: string): Promise<DealFinancials | null> {
  const client = await getClient();

  if (!client) {
    return mockStore.financials.find(f => f.deal_id === dealId) || null;
  }

  const { data, error } = await client
    .from('ft_deal_financials')
    .select('*')
    .eq('deal_id', dealId)
    .single();

  if (error && error.code !== 'PGRST116') throw error;
  return data;
}

// Enrichment
export async function upsertEnrichment(dealId: string, data: Partial<DealEnrichment>): Promise<DealEnrichment> {
  const client = await getClient();

  if (!client) {
    const idx = mockStore.enrichment.findIndex(e => e.deal_id === dealId);
    const newEnrich: DealEnrichment = {
      id: idx >= 0 ? mockStore.enrichment[idx].id : generateUUID(),
      deal_id: dealId,
      enriched_at: new Date().toISOString(),
      ...data
    };
    if (idx >= 0) {
      mockStore.enrichment[idx] = newEnrich;
    } else {
      mockStore.enrichment.push(newEnrich);
    }
    return newEnrich;
  }

  const { data: result, error } = await client
    .from('ft_deal_enrichment')
    .upsert({
      deal_id: dealId,
      ...data,
      enriched_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    }, { onConflict: 'deal_id' })
    .select()
    .single();

  if (error) throw error;
  return result;
}

export async function getEnrichment(dealId: string): Promise<DealEnrichment | null> {
  const client = await getClient();

  if (!client) {
    return mockStore.enrichment.find(e => e.deal_id === dealId) || null;
  }

  const { data, error } = await client
    .from('ft_deal_enrichment')
    .select('*')
    .eq('deal_id', dealId)
    .single();

  if (error && error.code !== 'PGRST116') throw error;
  return data;
}

// Memos
export async function createMemo(dealId: string, data: {
  content_markdown: string;
  recommendation?: 'approve' | 'approve_with_conditions' | 'decline';
}): Promise<DealMemo> {
  const client = await getClient();

  if (!client) {
    const existingMemos = mockStore.memos.filter(m => m.deal_id === dealId);
    const nextVersion = existingMemos.length > 0
      ? Math.max(...existingMemos.map(m => m.version)) + 1
      : 1;
    const newMemo: DealMemo = {
      id: generateUUID(),
      deal_id: dealId,
      version: nextVersion,
      content_markdown: data.content_markdown,
      recommendation: data.recommendation,
      generated_at: new Date().toISOString()
    };
    mockStore.memos.unshift(newMemo);
    return newMemo;
  }

  // Get next version number
  const { data: existing } = await client
    .from('ft_deal_memos')
    .select('version')
    .eq('deal_id', dealId)
    .order('version', { ascending: false })
    .limit(1);

  const nextVersion = (existing?.[0]?.version || 0) + 1;

  const { data: result, error } = await client
    .from('ft_deal_memos')
    .insert({
      deal_id: dealId,
      version: nextVersion,
      content_markdown: data.content_markdown,
      recommendation: data.recommendation,
      generated_at: new Date().toISOString()
    })
    .select()
    .single();

  if (error) throw error;
  return result;
}

export async function getMemos(dealId: string): Promise<DealMemo[]> {
  const client = await getClient();

  if (!client) {
    return mockStore.memos
      .filter(m => m.deal_id === dealId)
      .sort((a, b) => b.version - a.version);
  }

  const { data, error } = await client
    .from('ft_deal_memos')
    .select('*')
    .eq('deal_id', dealId)
    .order('version', { ascending: false });

  if (error) throw error;
  return data || [];
}

export async function getLatestMemo(dealId: string): Promise<DealMemo | null> {
  const client = await getClient();

  if (!client) {
    const memos = mockStore.memos
      .filter(m => m.deal_id === dealId)
      .sort((a, b) => b.version - a.version);
    return memos[0] || null;
  }

  const { data, error } = await client
    .from('ft_deal_memos')
    .select('*')
    .eq('deal_id', dealId)
    .order('version', { ascending: false })
    .limit(1)
    .single();

  if (error && error.code !== 'PGRST116') throw error;
  return data;
}

// Get complete deal data
export async function getCompleteDeal(dealId: string): Promise<{
  deal: Deal | null;
  propertyAttributes: DealPropertyAttributes | null;
  leaseTerms: DealLeaseTerms | null;
  scores: DealScores | null;
  financials: DealFinancials | null;
  enrichment: DealEnrichment | null;
  memos: DealMemo[];
}> {
  const [deal, propertyAttributes, leaseTerms, scores, financials, enrichment, memos] = await Promise.all([
    getDeal(dealId),
    getPropertyAttributes(dealId),
    getLeaseTerms(dealId),
    getScores(dealId),
    getFinancials(dealId),
    getEnrichment(dealId),
    getMemos(dealId)
  ]);

  return { deal, propertyAttributes, leaseTerms, scores, financials, enrichment, memos };
}

// Delete deal
export async function deleteDeal(dealId: string): Promise<boolean> {
  const client = await getClient();

  if (!client) {
    const idx = mockStore.deals.findIndex(d => d.id === dealId);
    if (idx >= 0) {
      mockStore.deals.splice(idx, 1);
      // Also clean up related data
      mockStore.propertyAttributes = mockStore.propertyAttributes.filter(p => p.deal_id !== dealId);
      mockStore.leaseTerms = mockStore.leaseTerms.filter(l => l.deal_id !== dealId);
      mockStore.scores = mockStore.scores.filter(s => s.deal_id !== dealId);
      mockStore.financials = mockStore.financials.filter(f => f.deal_id !== dealId);
      mockStore.enrichment = mockStore.enrichment.filter(e => e.deal_id !== dealId);
      mockStore.memos = mockStore.memos.filter(m => m.deal_id !== dealId);
    }
    return true;
  }

  const { error } = await client
    .from('ft_deals')
    .delete()
    .eq('id', dealId);

  if (error) throw error;
  return true;
}
