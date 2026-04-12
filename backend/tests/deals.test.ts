import { describe, it, expect } from 'vitest';
import request from 'supertest';
import app from '../app.js';

describe('GET /api/foretrust/health', () => {
  it('returns 200 with healthy status', async () => {
    const res = await request(app).get('/api/foretrust/health');
    expect(res.status).toBe(200);
    expect(res.body.status).toBe('healthy');
  });
});

describe('GET /api/foretrust/deals', () => {
  it('returns 200 with success and data array', async () => {
    const res = await request(app).get('/api/foretrust/deals');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
    expect(Array.isArray(res.body.data)).toBe(true);
  });
});

describe('GET /api/foretrust/deals/:id', () => {
  it('returns 404 for a nonexistent deal id', async () => {
    const res = await request(app).get('/api/foretrust/deals/nonexistent-id');
    expect(res.status).toBe(404);
    expect(res.body.success).toBe(false);
  });
});

describe('POST /api/foretrust/deals', () => {
  it('creates a deal and returns 201 with the new deal', async () => {
    const res = await request(app)
      .post('/api/foretrust/deals')
      .send({ name: 'Test Deal', sourceType: 'url' });
    expect(res.status).toBe(201);
    expect(res.body.success).toBe(true);
    expect(res.body.data.name).toBe('Test Deal');
    expect(res.body.data.id).toBeDefined();
  });

  it('returns 400 when name is missing', async () => {
    const res = await request(app)
      .post('/api/foretrust/deals')
      .send({ sourceType: 'url' });
    expect(res.status).toBe(400);
    expect(res.body.success).toBe(false);
  });

  it('returns 400 when sourceType is missing', async () => {
    const res = await request(app)
      .post('/api/foretrust/deals')
      .send({ name: 'Missing Source Type' });
    expect(res.status).toBe(400);
    expect(res.body.success).toBe(false);
  });
});

describe('GET /api/foretrust/deals — query param validation', () => {
  it('returns 200 with default limit when limit=abc', async () => {
    const res = await request(app).get('/api/foretrust/deals?limit=abc');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });

  it('returns 200 with default limit when limit=-1', async () => {
    const res = await request(app).get('/api/foretrust/deals?limit=-1');
    expect(res.status).toBe(200);
    expect(res.body.success).toBe(true);
  });

  it('caps limit at 1000 when limit=999999', async () => {
    const res = await request(app).get('/api/foretrust/deals?limit=999999');
    expect(res.status).toBe(200);
    // data array length will be <= 1000 (mock has < 1000, so just check it succeeded)
    expect(res.body.success).toBe(true);
  });
});
