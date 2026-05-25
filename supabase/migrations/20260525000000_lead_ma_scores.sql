-- M&A scoring fields live in ft_leads.ai_interpretation JSONB (no column change required).
-- Optional stored column for list filtering by production_fit.

COMMENT ON COLUMN ft_leads.ai_interpretation IS
  'Lead AI: owner/industry + production_fit, owner_operator_signal, sale_leaseback_fit, nnn_fit, qpp_fit (0-5), maps_entity, ai_provider';

ALTER TABLE ft_leads
  ADD COLUMN IF NOT EXISTS production_fit smallint
  GENERATED ALWAYS AS ((ai_interpretation->>'production_fit')::smallint) STORED;

CREATE INDEX IF NOT EXISTS ft_leads_production_fit_idx
  ON ft_leads (production_fit DESC NULLS LAST)
  WHERE production_fit IS NOT NULL;
