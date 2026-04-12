-- Change score columns from INTEGER to NUMERIC(5,2) so float values
-- returned by LLMs (e.g. 75.25) don't cause cast errors.
-- Scores are 0-100 so NUMERIC(5,2) gives enough precision.
ALTER TABLE ft_deal_scores
  ALTER COLUMN lci_score TYPE NUMERIC(5,2),
  ALTER COLUMN tenant_credit_score TYPE NUMERIC(5,2),
  ALTER COLUMN downside_score TYPE NUMERIC(5,2),
  ALTER COLUMN market_depth_score TYPE NUMERIC(5,2),
  ALTER COLUMN overall_score TYPE NUMERIC(5,2);
