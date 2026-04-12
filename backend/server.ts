import express from 'express';
import path from 'path';
import { fileURLToPath } from 'url';
import router from './index.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
// public/ lives at the backend root; __dirname is either /app (tsx) or /app/dist (compiled)
const publicDir = __dirname.endsWith('/dist')
  ? path.join(__dirname, '..', 'public')
  : path.join(__dirname, 'public');

const app = express();
const PORT = parseInt(process.env.PORT || '3001', 10);

app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true }));

// CORS for local dev
app.use((_req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  next();
});

app.use('/api/foretrust', router);

// Serve static dashboard
app.use(express.static(publicDir));

// Root health (Railway healthcheck hits /health by default)
app.get('/health', (_req, res) => {
  res.json({ status: 'healthy', service: 'foretrust-backend', version: '1.0.0' });
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Foretrust backend listening on port ${PORT}`);
});
