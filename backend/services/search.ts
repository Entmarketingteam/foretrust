// Foretrust Lead Research Service
// Runs parallel web searches to gather business intel for SLB thesis generation.
// Priority: Tavily (free dev tier) → Perplexity sonar (free) → SerpAPI (fallback)

export interface SearchResult {
  title: string;
  url: string;
  snippet: string;
  published_date?: string;
}

export interface LeadSearchResults {
  answer?: string;          // Tavily/Perplexity AI answer
  results: SearchResult[];
  source: 'tavily' | 'perplexity' | 'serpapi' | 'none';
  queries_run: string[];
}

// ── Tavily ──────────────────────────────────────────────────────────────────

async function searchTavily(query: string, maxResults = 5): Promise<SearchResult[]> {
  const apiKey = process.env.TAVILY_API_KEY;
  if (!apiKey) throw new Error('TAVILY_API_KEY not set');

  const res = await fetch('https://api.tavily.com/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      api_key: apiKey,
      query,
      max_results: maxResults,
      include_answer: true,
      search_depth: 'basic',
    }),
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Tavily error ${res.status}: ${err}`);
  }

  const data = await res.json() as {
    answer?: string;
    results?: Array<{ title: string; url: string; content: string; published_date?: string }>;
  };

  return (data.results || []).map(r => ({
    title: r.title,
    url: r.url,
    snippet: r.content?.slice(0, 300) || '',
    published_date: r.published_date,
  }));
}

// ── Perplexity ───────────────────────────────────────────────────────────────

async function searchPerplexity(query: string): Promise<{ answer: string; results: SearchResult[] }> {
  const apiKey = process.env.PERPLEXITY_API_KEY;
  if (!apiKey) throw new Error('PERPLEXITY_API_KEY not set');

  const res = await fetch('https://api.perplexity.ai/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: 'sonar',
      messages: [{ role: 'user', content: query }],
      max_tokens: 512,
    }),
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Perplexity error ${res.status}: ${err}`);
  }

  const data = await res.json() as {
    choices?: Array<{ message: { content: string } }>;
    citations?: string[];
  };

  const answer = data.choices?.[0]?.message?.content || '';
  const results: SearchResult[] = (data.citations || []).slice(0, 5).map((url, i) => ({
    title: `Source ${i + 1}`,
    url,
    snippet: '',
  }));

  return { answer, results };
}

// ── SerpAPI fallback ──────────────────────────────────────────────────────────

async function searchSerp(query: string): Promise<SearchResult[]> {
  const apiKey = process.env.SERP_API_KEY;
  if (!apiKey) throw new Error('SERP_API_KEY not set');

  const params = new URLSearchParams({
    q: query,
    api_key: apiKey,
    engine: 'google',
    num: '5',
    output: 'json',
  });

  const res = await fetch(`https://serpapi.com/search?${params}`);
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`SerpAPI error ${res.status}: ${err}`);
  }

  const data = await res.json() as {
    organic_results?: Array<{ title: string; link: string; snippet: string }>;
  };

  return (data.organic_results || []).slice(0, 5).map(r => ({
    title: r.title,
    url: r.link,
    snippet: r.snippet?.slice(0, 300) || '',
  }));
}

// ── Main research function ───────────────────────────────────────────────────

export async function researchLead(lead: {
  owner_name?: string | null;
  property_address?: string | null;
  city?: string | null;
  state?: string | null;
  jurisdiction?: string | null;
  lead_type?: string | null;
  building_sqft?: number | null;
  year_built?: number | null;
  ai_interpretation?: { likely_industry?: string; business_category?: string } | null;
}): Promise<LeadSearchResults> {
  // Build targeted search queries
  const location = [lead.city, lead.jurisdiction, lead.state || 'KY'].filter(Boolean).join(' ');
  const ownerRaw = lead.owner_name || '';
  // Strip legal suffixes for cleaner search, keep them for legal searches
  const ownerClean = ownerRaw.replace(/\s+(LLC|INC|CORP|LTD|CO\.?|L\.L\.C\.?|C\/O.*)/gi, '').trim();
  const industry = lead.ai_interpretation?.likely_industry || '';

  const queries: string[] = [];

  // Primary: owner/business name + location
  if (ownerClean) queries.push(`"${ownerClean}" ${location} business`);

  // Secondary: news / financial distress
  if (ownerRaw) queries.push(`"${ownerRaw}" bankruptcy OR foreclosure OR lawsuit OR sale OR news`);

  // Tertiary: property address
  if (lead.property_address) queries.push(`"${lead.property_address}" ${location} property`);

  // Industry SLB context if we have it
  if (industry) queries.push(`${industry} owner operator sale leaseback ${lead.state || 'Kentucky'} trend`);

  const queriesRun: string[] = [];
  const allResults: SearchResult[] = [];
  let topAnswer = '';

  // Run first 3 queries via Tavily in parallel (free tier)
  const tavilyQueries = queries.slice(0, 3);
  try {
    const tavilyResults = await Promise.allSettled(
      tavilyQueries.map(q => searchTavily(q, 4))
    );

    for (let i = 0; i < tavilyResults.length; i++) {
      queriesRun.push(tavilyQueries[i]);
      if (tavilyResults[i].status === 'fulfilled') {
        allResults.push(...(tavilyResults[i] as PromiseFulfilledResult<SearchResult[]>).value);
      }
    }

    // Dedupe by URL
    const seen = new Set<string>();
    const deduped = allResults.filter(r => {
      if (seen.has(r.url)) return false;
      seen.add(r.url);
      return true;
    });

    if (deduped.length >= 2) {
      return { answer: topAnswer, results: deduped.slice(0, 10), source: 'tavily', queries_run: queriesRun };
    }
  } catch (e) {
    console.warn('Tavily search failed, falling back to Perplexity:', e);
  }

  // Perplexity fallback — combine queries into one prompt
  try {
    const combinedQuery = `Research this Kentucky real estate lead: ${ownerRaw}${lead.property_address ? ` at ${lead.property_address}` : ''} in ${location}. Find: business history, years in operation, any news or financial distress signals, and any context relevant to a potential sale-leaseback transaction.`;
    queriesRun.push(combinedQuery);
    const { answer, results } = await searchPerplexity(combinedQuery);
    topAnswer = answer;
    allResults.push(...results);

    if (answer || results.length > 0) {
      return { answer: topAnswer, results: allResults.slice(0, 10), source: 'perplexity', queries_run: queriesRun };
    }
  } catch (e) {
    console.warn('Perplexity search failed, falling back to SerpAPI:', e);
  }

  // SerpAPI last resort
  try {
    const q = queries[0] || `${ownerRaw} ${location}`;
    queriesRun.push(q);
    const results = await searchSerp(q);
    allResults.push(...results);
    return { answer: '', results: allResults.slice(0, 10), source: 'serpapi', queries_run: queriesRun };
  } catch (e) {
    console.warn('All search APIs failed:', e);
  }

  return { answer: '', results: [], source: 'none', queries_run: queriesRun };
}
