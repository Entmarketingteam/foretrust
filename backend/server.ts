import path from 'path';
import { fileURLToPath } from 'url';
import express from 'express';
import app from './app.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
// public/ lives at the backend root; __dirname is either /app (tsx) or /app/dist (compiled)
const publicDir = __dirname.endsWith('/dist')
  ? path.join(__dirname, '..', 'public')
  : path.join(__dirname, 'public');

// Serve static dashboard
app.use(express.static(publicDir));

const PORT = parseInt(process.env.PORT || '3001', 10);

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Foretrust backend listening on port ${PORT}`);
});
