export type SourceConfidence = 'confirmed' | 'probable' | 'weak' | 'missing';

export type LeadRaw = {
  id: string;
  ownerName?: string | null;
  parcelNumber?: string | null;
  propertyAddress?: string | null;
  mailingAddress?: string | null;
  sourceUrl?: string | null;
  sourceCapturedAt?: string | null;
};

export type LeadOracle = {
  parcelNumber?: string | null;
  ownerName?: string | null;
  propertyAddress?: string | null;
  mailingAddressDeliverable?: boolean;
  ownerConfidence: SourceConfidence;
  addressConfidence: SourceConfidence;
  skiptraceConfidence: SourceConfidence;
  duplicateLeadIds?: string[];
  staleAfter?: string | null;
};

export type LeadVerdict = {
  leadId: string;
  status: 'PASS' | 'REVIEW' | 'BLOCK';
  canPublish: boolean;
  failedAssertions: string[];
  evidenceSummary: string[];
};

const PASSING_CONFIDENCE: SourceConfidence[] = ['confirmed', 'probable'];

function normalize(value?: string | null): string {
  return (value ?? '').trim().toLowerCase().replace(/\s+/g, ' ');
}

function isStale(staleAfter?: string | null, now = new Date()): boolean {
  if (!staleAfter) return false;
  const parsed = new Date(staleAfter);
  return Number.isNaN(parsed.getTime()) || parsed.getTime() < now.getTime();
}

export function gradeVerifiedLeadGate(raw: LeadRaw, oracle: LeadOracle, now = new Date()): LeadVerdict {
  const failedAssertions: string[] = [];
  const evidenceSummary: string[] = [];

  if (!raw.sourceUrl) failedAssertions.push('missing_source_provenance');
  else evidenceSummary.push(`source=${raw.sourceUrl}`);

  if (!raw.parcelNumber || normalize(raw.parcelNumber) !== normalize(oracle.parcelNumber)) {
    failedAssertions.push('parcel_mismatch');
  } else {
    evidenceSummary.push(`parcel_match=${raw.parcelNumber}`);
  }

  if (!raw.ownerName || normalize(raw.ownerName) !== normalize(oracle.ownerName)) {
    failedAssertions.push('owner_entity_mismatch');
  }

  if (!raw.propertyAddress || normalize(raw.propertyAddress) !== normalize(oracle.propertyAddress)) {
    failedAssertions.push('property_address_mismatch');
  }

  if (oracle.mailingAddressDeliverable !== true) failedAssertions.push('mailing_address_not_deliverable');
  if (!PASSING_CONFIDENCE.includes(oracle.ownerConfidence)) failedAssertions.push('owner_confidence_low');
  if (!PASSING_CONFIDENCE.includes(oracle.addressConfidence)) failedAssertions.push('address_confidence_low');
  if (!PASSING_CONFIDENCE.includes(oracle.skiptraceConfidence)) failedAssertions.push('skiptrace_confidence_low');
  if ((oracle.duplicateLeadIds ?? []).length > 0) failedAssertions.push('duplicate_suppression');
  if (isStale(oracle.staleAfter, now)) failedAssertions.push('stale_record_ttl');

  const status = failedAssertions.length === 0 ? 'PASS' : 'BLOCK';
  return {
    leadId: raw.id,
    status,
    canPublish: status === 'PASS',
    failedAssertions,
    evidenceSummary,
  };
}

export function toPublishedLead(raw: LeadRaw, verdict: LeadVerdict) {
  if (!verdict.canPublish) return null;
  return {
    leadId: raw.id,
    ownerName: raw.ownerName,
    parcelNumber: raw.parcelNumber,
    propertyAddress: raw.propertyAddress,
    verifiedAt: new Date().toISOString(),
  };
}
