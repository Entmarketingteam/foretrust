import { describe, it, expect } from 'vitest';
import request from 'supertest';
import app from '../app.js';

describe('GET /api/foretrust/leads', () => {
  it('returns 200 with success and empty data array in mock mode', async () => {
    const res = await request(app).get('/api/foretrust/leads');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(Array.isArray(res.body.data)).toBe(true);
  });
});

describe('GET /api/foretrust/leads/runs', () => {
  it('returns 200 with success', async () => {
    const res = await request(app).get('/api/foretrust/leads/runs');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });
});

describe('GET /api/foretrust/leads/:id', () => {
  it('returns 404 for a nonexistent lead id', async () => {
    const res = await request(app).get('/api/foretrust/leads/nonexistent-id');
    expect(res.status).toBe(404);
    expect(res.body.success).toBe(false);
  });
});

describe('POST /api/foretrust/leads/scrape', () => {
  it('returns 400 when source_key is missing', async () => {
    const res = await request(app)
      .post('/api/foretrust/leads/scrape')
      .send({});
    expect(res.status).toBe(400);
    expect(res.body.success).toBe(false);
  });
});

describe('GET /api/foretrust/leads — query param validation', () => {
  it('returns 200 when hot_score_min=abc', async () => {
    const res = await request(app).get('/api/foretrust/leads?hot_score_min=abc');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });

  it('returns 200 when limit=999999 (capped)', async () => {
    const res = await request(app).get('/api/foretrust/leads?limit=999999');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });
});
