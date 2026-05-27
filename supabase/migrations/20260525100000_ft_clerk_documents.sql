-- Clerk instrument documents (eCCLIX downloads) linked to leads

CREATE TABLE IF NOT EXISTS ft_clerk_documents (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001'::uuid
    REFERENCES ft_organizations(id) ON DELETE CASCADE,
  lead_id UUID REFERENCES ft_leads(id) ON DELETE SET NULL,
  source_key VARCHAR(100) NOT NULL DEFAULT 'ecclix_batch',
  county VARCHAR(50) NOT NULL,
  instrument_type VARCHAR(80),
  book VARCHAR(20),
  page VARCHAR(20),
  recorded_date DATE,
  grantor TEXT,
  grantee TEXT,
  legal_description TEXT,
  consideration DECIMAL(15, 2),
  property_address TEXT,
  file_name VARCHAR(255),
  storage_path TEXT NOT NULL,
  storage_url TEXT,
  file_sha256 VARCHAR(64),
  raw_payload JSONB DEFAULT '{}',
  scraped_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (county, book, page, instrument_type, source_key)
);

CREATE INDEX IF NOT EXISTS idx_clerk_docs_lead ON ft_clerk_documents(lead_id);
CREATE INDEX IF NOT EXISTS idx_clerk_docs_county_date ON ft_clerk_documents(county, recorded_date DESC);
CREATE INDEX IF NOT EXISTS idx_clerk_docs_type ON ft_clerk_documents(instrument_type);

ALTER TABLE ft_clerk_documents ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Service role full access clerk docs" ON ft_clerk_documents;
CREATE POLICY "Service role full access clerk docs" ON ft_clerk_documents
  FOR ALL TO service_role USING (true) WITH CHECK (true);

COMMENT ON TABLE ft_clerk_documents IS 'Downloaded county clerk instruments from eCCLIX (deeds, wills, mortgages, etc.)';
