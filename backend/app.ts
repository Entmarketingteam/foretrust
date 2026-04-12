import express from 'express';
import router from './index.js';

const app = express();

app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true }));

// CORS
const allowedOrigins: string[] = process.env.ALLOWED_ORIGINS
  ? process.env.ALLOWED_ORIGINS.split(',').map(o => o.trim())
  : [];

app.use((req, res, next) => {
  const origin = req.headers.origin;
  res.setHeader('Vary', 'Origin');
  if (allowedOrigins.length > 0) {
    if (origin && allowedOrigins.includes(origin)) {
      res.setHeader('Access-Control-Allow-Origin', origin);
    }
  } else if (process.env.NODE_ENV !== 'production') {
    res.setHeader('Access-Control-Allow-Origin', '*');
  }
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  if (req.method === 'OPTIONS') {
    res.status(204).end();
    return;
  }
  next();
});

// Simple in-memory rate limiter
const rateLimitMap = new Map<string, { count: number; resetAt: number }>();
const RATE_LIMIT_MAX = Math.max(1, parseInt(process.env.RATE_LIMIT_MAX || '100', 10));
const RATE_LIMIT_WINDOW_MS = Math.max(1, parseInt(process.env.RATE_LIMIT_WINDOW_MS || '60000', 10));

app.use((req, res, next) => {
  const ip = (req.headers['x-forwarded-for'] as string)?.split(',')[0]?.trim() || req.socket.remoteAddress || 'unknown';
  const now = Date.now();
  const entry = rateLimitMap.get(ip);
  if (!entry || now > entry.resetAt) {
    rateLimitMap.set(ip, { count: 1, resetAt: now + RATE_LIMIT_WINDOW_MS });
    return next();
  }
  entry.count++;
  if (entry.count > RATE_LIMIT_MAX) {
    res.setHeader('Retry-After', String(Math.ceil((entry.resetAt - now) / 1000)));
    return res.status(429).json({ success: false, error: 'Too many requests' });
  }
  next();
});

app.use('/api/foretrust', router);

// Root health (Railway healthcheck hits /health by default)
app.get('/health', (_req, res) => {
  res.json({ status: 'healthy', service: 'foretrust-backend', version: '1.0.0' });
});

// Purge expired rate-limit entries on a fixed interval (prevents unbounded memory growth)
setInterval(() => {
  const now = Date.now();
  for (const [ip, entry] of rateLimitMap.entries()) {
    if (now > entry.resetAt) rateLimitMap.delete(ip);
  }
}, RATE_LIMIT_WINDOW_MS);

export default app;
