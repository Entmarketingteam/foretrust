-- Allow the service_role (backend API) full access to all ft_ tables.
-- The Express backend is the only consumer; end-users never connect directly.
-- RLS remains enabled so the anon key is still blocked.

CREATE POLICY "Service role full access" ON ft_organizations
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access" ON ft_users
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access" ON ft_deals
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access" ON ft_deal_documents
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access" ON ft_deal_property_attributes
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access" ON ft_deal_lease_terms
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access" ON ft_deal_scores
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access" ON ft_deal_financials
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access" ON ft_deal_enrichment
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "Service role full access" ON ft_deal_memos
  FOR ALL TO service_role USING (true) WITH CHECK (true);
