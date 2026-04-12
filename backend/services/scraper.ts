// Thin HTTP client for the Python scraper service.
// Service URL and auth token come from Doppler-injected env vars.

const SCRAPER_SERVICE_URL = process.env.SCRAPER_SERVICE_URL || 'http://localhost:8000';
const SCRAPER_SHARED_TOKEN = process.env.SCRAPER_SHARED_TOKEN || '';
const SCRAPER_TIMEOUT_MS = parseInt(process.env.SCRAPER_TIMEOUT_MS || '30000', 10);

/** Thrown for 4xx responses — signals withRetry to stop immediately (caller error, not transient). */
class NonRetryableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NonRetryableError';
  }
}

async function withRetry<T>(
  fn: () => Promise<T>,
  retries = 3,
  baseDelayMs = 500
): Promise<T> {
  let lastError: unknown;
  for (let attempt = 0; attempt < retries; attempt++) {
    try {
      return await fn();
    } catch (err) {
      if (err instanceof NonRetryableError) {
        throw err;
      }
      // Don't retry on abort (timeout) — retrying a timed-out request compounds the hang
      if (err instanceof Error && err.name === 'AbortError') throw err;
      lastError = err;
      if (attempt < retries - 1) {
        await new Promise(resolve => setTimeout(resolve, baseDelayMs * 2 ** attempt));
      }
    }
  }
  throw lastError;
}

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

  return withRetry(async () => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), SCRAPER_TIMEOUT_MS);
    let response: Response;
    try {
      response = await fetch(url, {
        method: 'POST',
        headers,
        body: JSON.stringify({ params }),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timeout);
    }

    if (!response.ok) {
      const errorText = await response.text();
      if (response.status < 500) {
        // 4xx = caller error, don't retry
        throw new NonRetryableError(`Scraper service error (${response.status}): ${errorText}`);
      }
      throw new Error(`Scraper service error (${response.status}): ${errorText}`);
    }

    return response.json() as Promise<ScraperRunResult>;
  });
}

export async function listConnectors(): Promise<unknown[]> {
  const url = `${SCRAPER_SERVICE_URL}/connectors`;
  const headers: Record<string, string> = {};
  if (SCRAPER_SHARED_TOKEN) {
    headers['Authorization'] = `Bearer ${SCRAPER_SHARED_TOKEN}`;
  }

  return withRetry(async () => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), SCRAPER_TIMEOUT_MS);
    let response: Response;
    try {
      response = await fetch(url, { headers, signal: controller.signal });
    } finally {
      clearTimeout(timeout);
    }

    if (!response.ok) {
      if (response.status < 500) {
        // 4xx = caller error, don't retry
        throw new NonRetryableError(`Failed to list connectors: ${response.status}`);
      }
      throw new Error(`Failed to list connectors: ${response.status}`);
    }

    const data = await response.json() as { connectors: unknown[] };
    return data.connectors;
  });
}
