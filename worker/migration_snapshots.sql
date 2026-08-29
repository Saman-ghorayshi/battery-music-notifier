-- v2.1 migration: intruder snapshots.
-- Run once per environment:
--   npx wrangler d1 execute DB --file=migration_snapshots.sql --remote
-- Also needs an R2 bucket bound as SNAPSHOTS (see wrangler.toml):
--   npx wrangler r2 bucket create battery-snapshots

CREATE TABLE IF NOT EXISTS snapshots (
  snap_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  r2_key TEXT NOT NULL,
  content_type TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_user ON snapshots(user_id);
