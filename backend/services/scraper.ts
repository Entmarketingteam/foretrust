// Thin HTTP client for the Python scraper service.
// Service URL and auth token come from Doppler-injected env vars.

const SCRAPER_SERVICE_URL = process.env.SCRAPER_SERVICE_URL || 'http://localhost:8000';
const SCRAPER_SHARED_TOKEN = process.env.SCRAPER_SHARED_TOKEN || '';

interface ScraperRunResult {
  status: string;
  source_key: string;
}

export async function triggerScraperRun(
  sourceKey: string,
  params: Record<string, unknown> = {}
): Promise<ScraperRunResult> {
  const url = `${SCRAPER_SERVICE_URL}/run/${sourceKey}`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (SCRAPER_SHARED_TOKEN) {
    headers['Authorization'] = `Bearer ${SCRAPER_SHARED_TOKEN}`;
  }

  const response = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify({ params }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Scraper service error (${response.status}): ${errorText}`);
  }

  return response.json() as Promise<ScraperRunResult>;
}

export async function listConnectors(): Promise<unknown[]> {
  const url = `${SCRAPER_SERVICE_URL}/connectors`;
  const headers: Record<string, string> = {};
  if (SCRAPER_SHARED_TOKEN) {
    headers['Authorization'] = `Bearer ${SCRAPER_SHARED_TOKEN}`;
  }

  const response = await fetch(url, { headers });
  if (!response.ok) {
    throw new Error(`Failed to list connectors: ${response.status}`);
  }

  const data = await response.json() as { connectors: unknown[] };
  return data.connectors;
}
