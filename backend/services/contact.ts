// Foretrust Contact Intelligence Service
// Enriches leads with contact info via Apollo.io, Findymail verification, and web/SOS research.
// Flow: Apollo org+people search → Findymail email verification → Tavily SOS/web lookup

import type { LeadSearchResults } from './search.js';

export interface ContactPerson {
  name: string;
  title?: string;
  email?: string;
  email_status?: 'valid' | 'invalid' | 'risky' | 'unknown';
  email_mx_found?: boolean;
  phone?: string;
  linkedin_url?: string;
  source: 'apollo' | 'web';
}

export interface ContactIntel {
  entity_status?: 'active' | 'inactive' | 'dissolved' | 'unknown';
  entity_formed?: string;
  registered_agent_name?: string;
  registered_agent_address?: string;
  company_website?: string;
  linkedin_company_url?: string;
  contacts: ContactPerson[];
  enriched_at: string;
  sources_used: string[];
}

// ── Apollo.io ────────────────────────────────────────────────────────────────

interface ApolloOrg {
  id: string;
  name: string;
  website_url?: string;
  linkedin_url?: string;
  primary_domain?: string;
}

interface ApolloPerson {
  id: string;
  name: string;
  title?: string;
  email?: string;
  sanitized_phone?: string;
  linkedin_url?: string;
  organization?: { name?: string };
}

async function apolloOrgSearch(companyName: string, state: string): Promise<ApolloOrg | null> {
  const apiKey = process.env.APOLLO_API_KEY;
  if (!apiKey) return null;

  const res = await fetch('https://api.apollo.io/api/v1/mixed_companies/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Api-Key': apiKey },
    body: JSON.stringify({
      q_organization_name: companyName,
      organization_locations: [`${state}, US`],
      per_page: 3,
    }),
  });

  if (!res.ok) return null;

  const data = await res.json() as { organizations?: ApolloOrg[] };
  return data.organizations?.[0] ?? null;
}

async function apolloPeopleSearch(
  companyName: string,
  state: string,
  organizationIds?: string[],
): Promise<ApolloPerson[]> {
  const apiKey = process.env.APOLLO_API_KEY;
  if (!apiKey) return [];

  const body: Record<string, unknown> = {
    q_organization_name: companyName,
    organization_locations: [`${state}, US`],
    per_page: 5,
    reveal_personal_emails: true,
    // Prioritize decision-maker titles
    person_titles: ['owner', 'president', 'ceo', 'principal', 'managing member', 'partner', 'director'],
  };
  if (organizationIds?.length) {
    body.organization_ids = organizationIds;
  }

  const res = await fetch('https://api.apollo.io/api/v1/mixed_people/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Api-Key': apiKey },
    body: JSON.stringify(body),
  });

  if (!res.ok) return [];

  const data = await res.json() as { people?: ApolloPerson[] };
  return data.people ?? [];
}

// ── Findymail ────────────────────────────────────────────────────────────────

interface FindymailVerifyResult {
  email: string;
  status: 'valid' | 'invalid' | 'risky' | 'unknown';
  mx_found: boolean;
  disposable?: boolean;
}

interface FindymailSearchResult {
  email: string | null;
  status: 'valid' | 'invalid' | 'risky' | 'unknown';
}

async function findymailVerify(email: string): Promise<FindymailVerifyResult | null> {
  const apiKey = process.env.FINDYMAIL_API_KEY;
  if (!apiKey || !email) return null;

  const res = await fetch('https://app.findymail.com/api/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${apiKey}` },
    body: JSON.stringify({ email }),
  });

  if (!res.ok) return null;

  const data = await res.json() as {
    contact?: { email: string; status: string; mx_found?: boolean; disposable?: boolean };
    data?: { email: string; result: string; mx_found?: boolean };
  };

  // Findymail has two response shapes across API versions
  if (data.contact) {
    return {
      email: data.contact.email,
      status: normalizeEmailStatus(data.contact.status),
      mx_found: data.contact.mx_found ?? false,
      disposable: data.contact.disposable,
    };
  }
  if (data.data) {
    return {
      email: data.data.email,
      status: normalizeEmailStatus(data.data.result),
      mx_found: data.data.mx_found ?? false,
    };
  }
  return null;
}

async function findymailSearch(name: string, domain: string): Promise<FindymailSearchResult | null> {
  const apiKey = process.env.FINDYMAIL_API_KEY;
  if (!apiKey || !name || !domain) return null;

  const res = await fetch('https://app.findymail.com/api/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${apiKey}` },
    body: JSON.stringify({ name, domain }),
  });

  if (!res.ok) return null;

  const data = await res.json() as {
    contact?: { email: string | null; status: string };
    data?: { email: string | null; result: string };
  };

  if (data.contact) {
    return { email: data.contact.email, status: normalizeEmailStatus(data.contact.status) };
  }
  if (data.data) {
    return { email: data.data.email, status: normalizeEmailStatus(data.data.result) };
  }
  return null;
}

function normalizeEmailStatus(s: string): 'valid' | 'invalid' | 'risky' | 'unknown' {
  const v = (s || '').toLowerCase();
  if (v === 'valid' || v === 'deliverable') return 'valid';
  if (v === 'invalid' || v === 'undeliverable') return 'invalid';
  if (v === 'risky' || v === 'catch_all' || v === 'accept_all' || v === 'disposable') return 'risky';
  return 'unknown';
}

// ── KY SOS + Web lookup via Tavily ───────────────────────────────────────────

async function searchSosAndWeb(
  ownerName: string,
  location: string,
): Promise<{ registered_agent?: string; registered_agent_address?: string; entity_status?: string; entity_formed?: string; linkedin_company?: string }> {
  const apiKey = process.env.TAVILY_API_KEY;
  if (!apiKey) return {};

  // Two targeted queries in parallel
  const queries = [
    `"${ownerName}" Kentucky "registered agent" site:sos.ky.gov OR "secretary of state"`,
    `"${ownerName}" ${location} owner contact LinkedIn`,
  ];

  const results = await Promise.allSettled(
    queries.map(q =>
      fetch('https://api.tavily.com/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: apiKey, query: q, max_results: 3, search_depth: 'basic' }),
      }).then(r => r.json() as Promise<{ results?: Array<{ title: string; url: string; content: string }> }>),
    ),
  );

  const snippets: string[] = [];
  let linkedinCompany: string | undefined;

  for (const r of results) {
    if (r.status !== 'fulfilled') continue;
    for (const item of r.value.results ?? []) {
      snippets.push(item.content?.slice(0, 500) ?? '');
      if (item.url.includes('linkedin.com/company') && !linkedinCompany) {
        linkedinCompany = item.url;
      }
    }
  }

  const combined = snippets.join(' ').toLowerCase();

  // Heuristic extraction from SOS snippet text
  // Match "registered agent: Name Here" but reject generic explanatory text
  const agentRaw = combined.match(/registered agent[:\s]+([a-z ,.'-]{4,60})/i);
  const agentMatch = agentRaw && !agentRaw[1].includes(' is ') && !agentRaw[1].includes(' an ') ? agentRaw : null;
  const addressMatch = combined.match(/\d{2,5}\s[a-z0-9 ,.\-#]+(?:suite|ste|apt|floor|fl)?[a-z0-9 ,.]*,\s*[a-z ]+,\s*[a-z]{2}\s*\d{5}/i);
  const statusMatch = combined.match(/\b(active|inactive|dissolved|good standing|forfeited|revoked)\b/i);
  const formedMatch = combined.match(/(?:organized|formed|incorporated|registered)[^\d]{0,20}(\d{4})/i);

  return {
    registered_agent: agentMatch?.[1]?.trim(),
    registered_agent_address: addressMatch?.[0]?.trim(),
    entity_status: statusMatch?.[1]?.toLowerCase(),
    entity_formed: formedMatch?.[1],
    linkedin_company: linkedinCompany,
  };
}

// ── Main enrichment function ─────────────────────────────────────────────────

export async function enrichLeadContact(lead: {
  owner_name?: string | null;
  property_address?: string | null;
  city?: string | null;
  state?: string | null;
  jurisdiction?: string | null;
}): Promise<ContactIntel> {
  const state = lead.state || 'KY';
  const location = [lead.city, lead.jurisdiction, state].filter(Boolean).join(', ');
  const ownerRaw = lead.owner_name || '';
  const ownerClean = ownerRaw.replace(/\s+(LLC|INC|CORP|LTD|CO\.?|L\.L\.C\.?|C\/O.*)/gi, '').trim();

  const sourcesUsed: string[] = [];
  const contacts: ContactPerson[] = [];
  let companyWebsite: string | undefined;
  let linkedinCompanyUrl: string | undefined;
  let entityStatus: string | undefined;
  let entityFormed: string | undefined;
  let registeredAgentName: string | undefined;
  let registeredAgentAddress: string | undefined;

  // Run Apollo org search + SOS/web lookup in parallel
  const [apolloOrg, sosData] = await Promise.all([
    apolloOrgSearch(ownerClean, state).catch(() => null),
    searchSosAndWeb(ownerRaw, location).catch(() => ({
      registered_agent: undefined as string | undefined,
      registered_agent_address: undefined as string | undefined,
      entity_status: undefined as string | undefined,
      entity_formed: undefined as string | undefined,
      linkedin_company: undefined as string | undefined,
    })),
  ]);

  // Apply SOS/web data
  if (sosData.registered_agent) {
    registeredAgentName = sosData.registered_agent;
    sourcesUsed.push('ky_sos_web');
  }
  if (sosData.registered_agent_address) registeredAgentAddress = sosData.registered_agent_address;
  if (sosData.entity_status) entityStatus = sosData.entity_status;
  if (sosData.entity_formed) entityFormed = sosData.entity_formed;
  if (sosData.linkedin_company) linkedinCompanyUrl = sosData.linkedin_company;

  // Apply Apollo org data
  let primaryDomain: string | undefined;
  if (apolloOrg) {
    sourcesUsed.push('apollo');
    if (apolloOrg.website_url) companyWebsite = apolloOrg.website_url;
    if (apolloOrg.linkedin_url && !linkedinCompanyUrl) linkedinCompanyUrl = apolloOrg.linkedin_url;
    primaryDomain = apolloOrg.primary_domain;
  }

  // Apollo people search
  const apolloPeople = await apolloPeopleSearch(
    ownerClean,
    state,
    apolloOrg ? [apolloOrg.id] : undefined,
  ).catch(() => []);

  // For each person: collect + verify email via Findymail
  const emailVerifyTasks = apolloPeople.map(async (p): Promise<ContactPerson> => {
    const person: ContactPerson = {
      name: p.name,
      title: p.title,
      email: p.email,
      phone: p.sanitized_phone,
      linkedin_url: p.linkedin_url,
      source: 'apollo',
    };

    if (p.email) {
      // Verify existing email
      const verified = await findymailVerify(p.email).catch(() => null);
      if (verified) {
        person.email_status = verified.status;
        person.email_mx_found = verified.mx_found;
        if (!sourcesUsed.includes('findymail')) sourcesUsed.push('findymail');
      }
    } else if (primaryDomain) {
      // Try to find email via name + domain
      const found = await findymailSearch(p.name, primaryDomain).catch(() => null);
      if (found?.email) {
        person.email = found.email;
        person.email_status = found.status;
        if (!sourcesUsed.includes('findymail')) sourcesUsed.push('findymail');
      }
    }

    return person;
  });

  const enrichedPeople = await Promise.allSettled(emailVerifyTasks);
  for (const r of enrichedPeople) {
    if (r.status === 'fulfilled') contacts.push(r.value);
  }

  return {
    entity_status: normalizeEntityStatus(entityStatus),
    entity_formed: entityFormed,
    registered_agent_name: registeredAgentName,
    registered_agent_address: registeredAgentAddress,
    company_website: companyWebsite,
    linkedin_company_url: linkedinCompanyUrl,
    contacts,
    enriched_at: new Date().toISOString(),
    sources_used: sourcesUsed,
  };
}

function normalizeEntityStatus(s?: string): 'active' | 'inactive' | 'dissolved' | 'unknown' | undefined {
  if (!s) return undefined;
  const v = s.toLowerCase();
  if (v.includes('active') || v.includes('good standing')) return 'active';
  if (v.includes('dissolv') || v.includes('revok') || v.includes('forfeit')) return 'dissolved';
  if (v.includes('inactive')) return 'inactive';
  return 'unknown';
}
