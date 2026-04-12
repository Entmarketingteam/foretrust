-- Fix 1: Correct the default organization_id on ft_leads.
-- The initial schema defaulted to the nil UUID (all zeros) which has no matching
-- row in ft_organizations, causing a FK violation on every scraper insert.
ALTER TABLE ft_leads
  ALTER COLUMN organization_id SET DEFAULT '00000000-0000-0000-0000-000000000001'::uuid;

-- Fix 2: Service role full access policies for leads tables.
-- The 20260412000000_service_role_bypass migration covered deal tables but
-- missed ft_leads and ft_lead_source_runs.
CREATE POLICY "Service role full access" ON ft_leads
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access" ON ft_lead_source_runs
  FOR ALL TO service_role USING (true) WITH CHECK (true);
