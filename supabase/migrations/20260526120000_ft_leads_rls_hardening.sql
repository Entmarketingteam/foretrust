-- Harden public API: enable RLS on lead tables (may have been created without it)
-- and ensure clerk-doc policy is service_role-only (idempotent).

ALTER TABLE ft_leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE ft_lead_source_runs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Service role full access" ON ft_leads;
CREATE POLICY "Service role full access" ON ft_leads
  FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Service role full access" ON ft_lead_source_runs;
CREATE POLICY "Service role full access" ON ft_lead_source_runs
  FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Service role full access clerk docs" ON ft_clerk_documents;
CREATE POLICY "Service role full access clerk docs" ON ft_clerk_documents
  FOR ALL TO service_role USING (true) WITH CHECK (true);
