-- Add contact intelligence column to ft_leads.
-- Stores Apollo/Findymail/SOS-enriched contact data as JSONB.
ALTER TABLE ft_leads
  ADD COLUMN IF NOT EXISTS contact_intel JSONB;

CREATE INDEX IF NOT EXISTS ft_leads_contact_intel_idx
  ON ft_leads ((contact_intel IS NOT NULL));
