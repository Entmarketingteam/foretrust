-- Add AI interpretation column to ft_leads.
-- Stores Claude's structured analysis of each lead (owner type, industry,
-- lead potential, opportunity summary, etc.) as JSONB.
ALTER TABLE ft_leads
  ADD COLUMN IF NOT EXISTS ai_interpretation JSONB;

-- Index for querying interpreted vs. uninterpreted leads
CREATE INDEX IF NOT EXISTS ft_leads_ai_interpretation_idx
  ON ft_leads ((ai_interpretation IS NOT NULL));
