import { describe, expect, it } from 'vitest';
import { gradeVerifiedLeadGate, toPublishedLead, type LeadOracle, type LeadRaw } from '../services/lead-verification.js';

const goodRaw: LeadRaw = {
  id: 'lead-good-001',
  ownerName: 'Bluegrass Holdings LLC',
  parcelNumber: '123-45-678',
  propertyAddress: '100 Main St, Lexington, KY',
  mailingAddress: 'PO Box 100, Lexington, KY',
  sourceUrl: 'https://county.example/parcel/123-45-678',
  sourceCapturedAt: '2026-06-26T12:00:00.000Z',
};

const goodOracle: LeadOracle = {
  ownerName: 'Bluegrass Holdings LLC',
  parcelNumber: '123-45-678',
  propertyAddress: '100 Main St, Lexington, KY',
  mailingAddressDeliverable: true,
  ownerConfidence: 'confirmed',
  addressConfidence: 'confirmed',
  skiptraceConfidence: 'probable',
  duplicateLeadIds: [],
  staleAfter: '2026-07-26T12:00:00.000Z',
};

describe('Foretrust verified lead gate', () => {
  it('passes a lead only when parcel, owner, address, provenance, and confidence checks pass', () => {
    const verdict = gradeVerifiedLeadGate(goodRaw, goodOracle, new Date('2026-06-26T12:00:00.000Z'));

    expect(verdict.status).toBe('PASS');
    expect(verdict.canPublish).toBe(true);
    expect(verdict.failedAssertions).toEqual([]);
    expect(toPublishedLead(goodRaw, verdict)).toMatchObject({
      leadId: 'lead-good-001',
      ownerName: 'Bluegrass Holdings LLC',
      parcelNumber: '123-45-678',
    });
  });

  it('blocks a deliberately bad lead from the published queue', () => {
    const badRaw: LeadRaw = {
      ...goodRaw,
      id: 'lead-bad-001',
      ownerName: 'Wrong Owner LLC',
      parcelNumber: '000-00-000',
      propertyAddress: '999 Fake Ave, Nowhere, KY',
      sourceUrl: null,
    };
    const badOracle: LeadOracle = {
      ...goodOracle,
      duplicateLeadIds: ['existing-lead-123'],
      mailingAddressDeliverable: false,
      ownerConfidence: 'weak',
      skiptraceConfidence: 'missing',
      staleAfter: '2026-01-01T00:00:00.000Z',
    };

    const verdict = gradeVerifiedLeadGate(badRaw, badOracle, new Date('2026-06-26T12:00:00.000Z'));

    expect(verdict.status).toBe('BLOCK');
    expect(verdict.canPublish).toBe(false);
    expect(verdict.failedAssertions).toEqual(expect.arrayContaining([
      'missing_source_provenance',
      'parcel_mismatch',
      'owner_entity_mismatch',
      'property_address_mismatch',
      'mailing_address_not_deliverable',
      'owner_confidence_low',
      'skiptrace_confidence_low',
      'duplicate_suppression',
      'stale_record_ttl',
    ]));
    expect(toPublishedLead(badRaw, verdict)).toBeNull();
  });
});
