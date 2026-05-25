// Gemini CLI + Google OAuth (Ultra/Pro subscription) — mirrors agent-server/vsl/providers/gemini_cli.py
import { spawnSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import os from 'os';

const GEMINI_BIN = process.env.GEMINI_BIN || 'gemini';
const DEFAULT_MODEL = process.env.GEMINI_MODEL || 'gemini-2.5-flash';
const DEFAULT_TIMEOUT_MS = parseInt(process.env.GEMINI_CLI_TIMEOUT_MS || '600000', 10);

const OAUTH_SETTINGS = {
  security: { auth: { selectedType: 'oauth-personal' } },
};

/** Railway uses /root/.gemini; local Mac/Linux uses ~/.gemini unless explicitly root. */
function useRailwayGeminiPaths(): boolean {
  const cliHome = process.env.GEMINI_CLI_HOME?.trim() || '';
  if (!cliHome.startsWith('/root')) return false;
  try {
    return typeof process.getuid === 'function' && process.getuid() === 0;
  } catch {
    return false;
  }
}

function geminiDir(): string {
  if (useRailwayGeminiPaths() && process.env.GEMINI_CLI_HOME?.trim()) {
    return process.env.GEMINI_CLI_HOME.trim();
  }
  return path.join(os.homedir(), '.gemini');
}

function userHome(): string {
  if (useRailwayGeminiPaths()) {
    if (process.env.GEMINI_CLI_USER_HOME?.trim()) {
      return process.env.GEMINI_CLI_USER_HOME.trim();
    }
    const cliHome = process.env.GEMINI_CLI_HOME?.trim();
    if (cliHome) return path.dirname(cliHome);
  }
  const home = os.homedir();
  if (path.basename(home) === '.gemini') return path.dirname(home);
  return home;
}

function ensureOAuthCreds(): boolean {
  const dir = geminiDir();
  fs.mkdirSync(dir, { recursive: true });
  const credsPath = path.join(dir, 'oauth_creds.json');

  const raw = process.env.GEMINI_OAUTH_CREDS?.trim();
  if (raw) fs.writeFileSync(credsPath, raw);

  const settingsPath = path.join(dir, 'settings.json');
  if (!fs.existsSync(settingsPath)) {
    fs.writeFileSync(settingsPath, JSON.stringify(OAUTH_SETTINGS, null, 2) + '\n');
  }

  try {
    return fs.statSync(credsPath).size > 10;
  } catch {
    return false;
  }
}

function whichGemini(): string | null {
  const paths = (process.env.PATH || '').split(path.delimiter);
  for (const p of paths) {
    const full = path.join(p, GEMINI_BIN);
    if (fs.existsSync(full)) return full;
  }
  return null;
}

export function isGeminiCliAvailable(): boolean {
  return whichGemini() !== null && ensureOAuthCreds();
}

function cliEnv(): NodeJS.ProcessEnv {
  const env = { ...process.env };
  for (const key of [
    'GEMINI_API_KEY',
    'GOOGLE_API_KEY',
    'GOOGLE_GENAI_USE_VERTEXAI',
    'GOOGLE_GENAI_USE_GCA',
  ]) {
    delete env[key];
  }
  env.HOME = userHome();
  delete env.GEMINI_CLI_HOME;
  env.GEMINI_CLI_TRUST_WORKSPACE = env.GEMINI_CLI_TRUST_WORKSPACE || 'true';
  return env;
}

export function runGeminiPrompt(prompt: string, options?: { model?: string; timeoutMs?: number }): string {
  if (!isGeminiCliAvailable()) {
    throw new Error(
      'Gemini CLI OAuth not configured. Run `gemini` locally to sign in, then sync GEMINI_OAUTH_CREDS to Railway (scripts/sync-gemini-oauth.sh).'
    );
  }

  const bin = whichGemini()!;
  const modelId = options?.model || DEFAULT_MODEL;
  const timeoutMs = options?.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  console.log(
    `[gemini-cli] model=${modelId} HOME=${userHome()} config=${geminiDir()}`
  );

  const result = spawnSync(
    bin,
    ['--skip-trust', '-y', '-p', '', '-m', modelId, '-o', 'text'],
    {
      input: prompt,
      encoding: 'utf-8',
      timeout: timeoutMs,
      env: cliEnv(),
    }
  );

  if (result.error) {
    throw new Error(`gemini CLI spawn failed: ${result.error.message}`);
  }
  if (result.status !== 0) {
    const err = (result.stderr || result.stdout || 'unknown error').trim();
    throw new Error(`gemini CLI failed: ${err}`);
  }

  const text = (result.stdout || '').trim();
  if (!text) throw new Error('gemini CLI returned empty output');
  return text;
}

export function repairJsonViaGemini(brokenJson: string): string {
  const prompt =
    'The following text should be a single JSON object but has syntax errors. ' +
    'Return ONLY the corrected JSON object, no markdown:\n\n' +
    brokenJson.slice(0, 14000);
  return runGeminiPrompt(prompt, { timeoutMs: 120000 });
}

export function extractJsonObject(raw: string): string {
  let cleaned = raw.trim();
  if (cleaned.startsWith('```json')) cleaned = cleaned.slice(7);
  else if (cleaned.startsWith('```')) cleaned = cleaned.slice(3);
  if (cleaned.endsWith('```')) cleaned = cleaned.slice(0, -3);
  const start = cleaned.indexOf('{');
  const end = cleaned.lastIndexOf('}');
  if (start !== -1 && end !== -1) cleaned = cleaned.slice(start, end + 1);
  return cleaned.trim();
}

export function parseJsonWithRepair<T>(raw: string): T {
  const extracted = extractJsonObject(raw);
  try {
    return JSON.parse(extracted) as T;
  } catch {
    if (!isGeminiCliAvailable()) throw new Error('Invalid JSON from Gemini CLI and repair unavailable');
    const fixed = repairJsonViaGemini(extracted);
    return JSON.parse(extractJsonObject(fixed)) as T;
  }
}
