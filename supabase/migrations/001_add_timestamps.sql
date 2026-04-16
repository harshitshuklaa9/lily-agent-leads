-- Option C: Freshness-based expiry
-- Adds updated_at to leads and created_at to contacts so the pipeline
-- can detect stale rows and re-run only what has expired.
--
-- Run this once in Supabase SQL editor before the next pipeline run.

-- leads: track when the row was last enriched
ALTER TABLE leads
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- Auto-update updated_at on any UPDATE to leads
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS leads_set_updated_at ON leads;
CREATE TRIGGER leads_set_updated_at
  BEFORE UPDATE ON leads
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- contacts: track when each contact was found
ALTER TABLE contacts
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

-- Backfill: mark all existing rows as "just created" so they start fresh
UPDATE leads    SET updated_at = NOW() WHERE updated_at IS NULL;
UPDATE contacts SET created_at = NOW() WHERE created_at IS NULL;
