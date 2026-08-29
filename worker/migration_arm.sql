-- v2.3 migration: account-level arm/disarm + disarm pass (hash only).
-- Run once per environment:
--   npx wrangler d1 execute DB --file=migration_arm.sql --remote

ALTER TABLE users ADD COLUMN armed INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN armed_by TEXT;
ALTER TABLE users ADD COLUMN disarm_hash TEXT;
