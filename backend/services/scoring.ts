import type { LeadInterpretation } from './claude.js';

/** Central KY production / NNN / SLB / QPP review thresholds */
export function qualifiesForReview(interp: LeadInterpretation): boolean {
  const prod = interp.production_fit ?? 0;
  const oo = interp.owner_operator_signal ?? 0;
  const qpp = interp.qpp_fit ?? 0;
  const nnn = interp.nnn_fit ?? 0;
  return prod >= 4 && oo >= 3 && (qpp >= 3 || nnn >= 3);
}

export function maScoreLabel(score: number | undefined): string {
  if (score == null || score < 0) return '—';
  if (score >= 4) return 'Strong';
  if (score >= 3) return 'Moderate';
  if (score >= 1) return 'Weak';
  return 'None';
}
