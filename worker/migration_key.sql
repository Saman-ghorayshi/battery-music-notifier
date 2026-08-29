-- v2.4 migration: device disarm key (WebAuthn-style) + challenges.
-- Run once per environment:
--   npx wrangler d1 execute DB --file=migration_key.sql --remote

ALTER TABLE users ADD COLUMN disarm_pubkey TEXT;

CREATE TABLE IF NOT EXISTS arm_challenges (
  user_id INTEGER PRIMARY KEY,
  challenge TEXT NOT NULL,
  expires_at INTEGER NOT NULL
);
