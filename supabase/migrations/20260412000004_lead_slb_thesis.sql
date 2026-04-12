-- Add sale-leaseback thesis column to ft_leads.
-- Stores Claude's web-researched SLB opportunity narrative as JSONB.
ALTER TABLE ft_leads
  ADD COLUMN IF NOT EXISTS slb_thesis JSONB;
