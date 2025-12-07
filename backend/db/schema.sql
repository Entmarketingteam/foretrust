-- Foretrust MVP Database Schema
-- Run this in Supabase SQL Editor

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Organizations (funds/firms)
CREATE TABLE IF NOT EXISTS ft_organizations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name VARCHAR(255) NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Users
CREATE TABLE IF NOT EXISTS ft_users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID NOT NULL REFERENCES ft_organizations(id) ON DELETE CASCADE,
  email VARCHAR(255) NOT NULL UNIQUE,
  name VARCHAR(255) NOT NULL,
  role VARCHAR(50) NOT NULL DEFAULT 'analyst' CHECK (role IN ('admin', 'analyst', 'viewer')),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Deals (main entity)
CREATE TABLE IF NOT EXISTS ft_deals (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID NOT NULL REFERENCES ft_organizations(id) ON DELETE CASCADE,
  name VARCHAR(255) NOT NULL,
  status VARCHAR(50) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'ingested', 'enriched', 'underwritten', 'memo_generated', 'archived')),
  source_type VARCHAR(50) NOT NULL CHECK (source_type IN ('pdf', 'url', 'manual')),
  source_url TEXT,
  created_by UUID REFERENCES ft_users(id),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Deal Documents (uploaded PDFs, etc.)
CREATE TABLE IF NOT EXISTS ft_deal_documents (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  deal_id UUID NOT NULL REFERENCES ft_deals(id) ON DELETE CASCADE,
  document_type VARCHAR(50) NOT NULL DEFAULT 'om' CHECK (document_type IN ('om', 'lease', 'rent_roll', 'other')),
  file_name VARCHAR(255) NOT NULL,
  file_url TEXT NOT NULL,
  file_size INTEGER,
  parsed_content TEXT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Deal Property Attributes
CREATE TABLE IF NOT EXISTS ft_deal_property_attributes (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  deal_id UUID NOT NULL UNIQUE REFERENCES ft_deals(id) ON DELETE CASCADE,
  address_line1 VARCHAR(255),
  city VARCHAR(100),
  state VARCHAR(50),
  postal_code VARCHAR(20),
  latitude DECIMAL(10, 8),
  longitude DECIMAL(11, 8),
  property_type VARCHAR(100),
  building_sqft INTEGER,
  land_acres DECIMAL(10, 4),
  year_built INTEGER,
  clear_height_ft INTEGER,
  dock_doors INTEGER,
  drive_in_doors INTEGER,
  zoning VARCHAR(100),
  parcel_number VARCHAR(100),
  last_sale_date DATE,
  last_sale_price DECIMAL(15, 2),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Deal Lease Terms
CREATE TABLE IF NOT EXISTS ft_deal_lease_terms (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  deal_id UUID NOT NULL UNIQUE REFERENCES ft_deals(id) ON DELETE CASCADE,
  tenant_name VARCHAR(255),
  lease_type VARCHAR(100),
  lease_start_date DATE,
  lease_end_date DATE,
  base_rent_annual DECIMAL(15, 2),
  rent_psf DECIMAL(10, 2),
  rent_escalations JSONB DEFAULT '[]',
  options JSONB DEFAULT '[]',
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Deal Scores
CREATE TABLE IF NOT EXISTS ft_deal_scores (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  deal_id UUID NOT NULL UNIQUE REFERENCES ft_deals(id) ON DELETE CASCADE,
  lci_score INTEGER CHECK (lci_score >= 0 AND lci_score <= 100),
  tenant_credit_score INTEGER CHECK (tenant_credit_score >= 0 AND tenant_credit_score <= 100),
  downside_score INTEGER CHECK (downside_score >= 0 AND downside_score <= 100),
  market_depth_score INTEGER CHECK (market_depth_score >= 0 AND market_depth_score <= 100),
  overall_score INTEGER CHECK (overall_score >= 0 AND overall_score <= 100),
  risk_flags JSONB DEFAULT '[]',
  scored_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Deal Financials
CREATE TABLE IF NOT EXISTS ft_deal_financials (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  deal_id UUID NOT NULL UNIQUE REFERENCES ft_deals(id) ON DELETE CASCADE,
  purchase_price DECIMAL(15, 2),
  noi_year1 DECIMAL(15, 2),
  cap_rate DECIMAL(5, 4),
  ltv_assumed DECIMAL(5, 4),
  interest_rate DECIMAL(5, 4),
  io_years INTEGER,
  amort_years INTEGER,
  exit_cap_rate DECIMAL(5, 4),
  hold_period_years INTEGER,
  levered_irr DECIMAL(5, 4),
  unlevered_irr DECIMAL(5, 4),
  dscr_min DECIMAL(5, 2),
  cash_on_cash_year1 DECIMAL(5, 4),
  cash_on_cash_avg DECIMAL(5, 4),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Deal Enrichment Data
CREATE TABLE IF NOT EXISTS ft_deal_enrichment (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  deal_id UUID NOT NULL UNIQUE REFERENCES ft_deals(id) ON DELETE CASCADE,
  geocode JSONB,
  market JSONB,
  tenant JSONB,
  enriched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Deal Memos
CREATE TABLE IF NOT EXISTS ft_deal_memos (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  deal_id UUID NOT NULL REFERENCES ft_deals(id) ON DELETE CASCADE,
  version INTEGER NOT NULL DEFAULT 1,
  content_markdown TEXT NOT NULL,
  recommendation VARCHAR(50) CHECK (recommendation IN ('approve', 'approve_with_conditions', 'decline')),
  generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_deals_org ON ft_deals(organization_id);
CREATE INDEX IF NOT EXISTS idx_deals_status ON ft_deals(status);
CREATE INDEX IF NOT EXISTS idx_deals_created ON ft_deals(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_deal ON ft_deal_documents(deal_id);
CREATE INDEX IF NOT EXISTS idx_memos_deal ON ft_deal_memos(deal_id);
CREATE INDEX IF NOT EXISTS idx_users_org ON ft_users(organization_id);
CREATE INDEX IF NOT EXISTS idx_property_city_state ON ft_deal_property_attributes(city, state);
CREATE INDEX IF NOT EXISTS idx_lease_tenant ON ft_deal_lease_terms(tenant_name);
CREATE INDEX IF NOT EXISTS idx_scores_overall ON ft_deal_scores(overall_score DESC);

-- Row Level Security (RLS) Policies
ALTER TABLE ft_organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE ft_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE ft_deals ENABLE ROW LEVEL SECURITY;
ALTER TABLE ft_deal_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE ft_deal_property_attributes ENABLE ROW LEVEL SECURITY;
ALTER TABLE ft_deal_lease_terms ENABLE ROW LEVEL SECURITY;
ALTER TABLE ft_deal_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE ft_deal_financials ENABLE ROW LEVEL SECURITY;
ALTER TABLE ft_deal_enrichment ENABLE ROW LEVEL SECURITY;
ALTER TABLE ft_deal_memos ENABLE ROW LEVEL SECURITY;

-- Helper function to get user's organization
CREATE OR REPLACE FUNCTION get_user_org_id()
RETURNS UUID AS $$
BEGIN
  RETURN (
    SELECT organization_id
    FROM ft_users
    WHERE id = auth.uid()
  );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- RLS Policies for organization isolation
CREATE POLICY "Users can view own org" ON ft_organizations
  FOR SELECT USING (id = get_user_org_id());

CREATE POLICY "Users can view org members" ON ft_users
  FOR SELECT USING (organization_id = get_user_org_id());

CREATE POLICY "Users can view org deals" ON ft_deals
  FOR ALL USING (organization_id = get_user_org_id());

CREATE POLICY "Users can view org documents" ON ft_deal_documents
  FOR ALL USING (deal_id IN (SELECT id FROM ft_deals WHERE organization_id = get_user_org_id()));

CREATE POLICY "Users can view org property attrs" ON ft_deal_property_attributes
  FOR ALL USING (deal_id IN (SELECT id FROM ft_deals WHERE organization_id = get_user_org_id()));

CREATE POLICY "Users can view org lease terms" ON ft_deal_lease_terms
  FOR ALL USING (deal_id IN (SELECT id FROM ft_deals WHERE organization_id = get_user_org_id()));

CREATE POLICY "Users can view org scores" ON ft_deal_scores
  FOR ALL USING (deal_id IN (SELECT id FROM ft_deals WHERE organization_id = get_user_org_id()));

CREATE POLICY "Users can view org financials" ON ft_deal_financials
  FOR ALL USING (deal_id IN (SELECT id FROM ft_deals WHERE organization_id = get_user_org_id()));

CREATE POLICY "Users can view org enrichment" ON ft_deal_enrichment
  FOR ALL USING (deal_id IN (SELECT id FROM ft_deals WHERE organization_id = get_user_org_id()));

CREATE POLICY "Users can view org memos" ON ft_deal_memos
  FOR ALL USING (deal_id IN (SELECT id FROM ft_deals WHERE organization_id = get_user_org_id()));

-- Insert default organization and admin user for MVP testing
INSERT INTO ft_organizations (id, name) VALUES
  ('00000000-0000-0000-0000-000000000001', 'Demo Fund')
ON CONFLICT DO NOTHING;

INSERT INTO ft_users (id, organization_id, email, name, role) VALUES
  ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', 'demo@foretrust.com', 'Demo User', 'admin')
ON CONFLICT DO NOTHING;

-- MVP ONLY: Allow anon access for demo organization
-- Remove these policies in production!
CREATE POLICY "Anon can view demo org" ON ft_organizations
  FOR SELECT USING (id = '00000000-0000-0000-0000-000000000001');

CREATE POLICY "Anon can view demo users" ON ft_users
  FOR SELECT USING (organization_id = '00000000-0000-0000-0000-000000000001');

CREATE POLICY "Anon can manage demo deals" ON ft_deals
  FOR ALL USING (organization_id = '00000000-0000-0000-0000-000000000001');

CREATE POLICY "Anon can manage demo documents" ON ft_deal_documents
  FOR ALL USING (deal_id IN (SELECT id FROM ft_deals WHERE organization_id = '00000000-0000-0000-0000-000000000001'));

CREATE POLICY "Anon can manage demo property attrs" ON ft_deal_property_attributes
  FOR ALL USING (deal_id IN (SELECT id FROM ft_deals WHERE organization_id = '00000000-0000-0000-0000-000000000001'));

CREATE POLICY "Anon can manage demo lease terms" ON ft_deal_lease_terms
  FOR ALL USING (deal_id IN (SELECT id FROM ft_deals WHERE organization_id = '00000000-0000-0000-0000-000000000001'));

CREATE POLICY "Anon can manage demo scores" ON ft_deal_scores
  FOR ALL USING (deal_id IN (SELECT id FROM ft_deals WHERE organization_id = '00000000-0000-0000-0000-000000000001'));

CREATE POLICY "Anon can manage demo financials" ON ft_deal_financials
  FOR ALL USING (deal_id IN (SELECT id FROM ft_deals WHERE organization_id = '00000000-0000-0000-0000-000000000001'));

CREATE POLICY "Anon can manage demo enrichment" ON ft_deal_enrichment
  FOR ALL USING (deal_id IN (SELECT id FROM ft_deals WHERE organization_id = '00000000-0000-0000-0000-000000000001'));

CREATE POLICY "Anon can manage demo memos" ON ft_deal_memos
  FOR ALL USING (deal_id IN (SELECT id FROM ft_deals WHERE organization_id = '00000000-0000-0000-0000-000000000001'));
