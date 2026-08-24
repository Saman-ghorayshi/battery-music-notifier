-- One-shot migration from the pre-2.0.0 schema to v2.0.0.
-- Run: npx wrangler d1 execute DB --file=migration_v2.sql --remote
-- Idempotence notes:
--   * RENAME COLUMN fails if already renamed -> ignore "duplicate column name" errors.
--   * pairing_codes is ephemeral (5-min TTL), so dropping it is always safe.

ALTER TABLE users RENAME COLUMN banned TO is_banned;
ALTER TABLE users ADD COLUMN total_alerts INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN linked_token TEXT;

DROP TABLE IF EXISTS pairing_codes;
CREATE TABLE IF NOT EXISTS pairing_codes (
  code TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_linked_token ON users(linked_token);
CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);
