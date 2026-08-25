-- Battery Notifier Cloud Relay schema (v2.0.0)
-- Aligned 1:1 with worker.js queries. See "MIGRATION" at the bottom for
-- upgrading an existing D1 database deployed from the old schema.

-- Users table (Stores device state and shared tokens)
CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY AUTOINCREMENT,
  token TEXT UNIQUE NOT NULL,            -- sha256 hex; plaintext never stored
  linked_token TEXT,                     -- sha256 hex of paired phone's token
  device_name TEXT,
  platform TEXT,
  battery_pct INTEGER DEFAULT -1,
  is_charging INTEGER DEFAULT 0,
  alert_active INTEGER DEFAULT 0,
  alert_type TEXT,
  alert_ts INTEGER DEFAULT 0,
  last_seen INTEGER DEFAULT 0,
  total_alerts INTEGER DEFAULT 0,
  is_banned INTEGER DEFAULT 0,
  is_pro INTEGER DEFAULT 0,
  is_founding INTEGER DEFAULT 0,
  created_at INTEGER DEFAULT (strftime('%s', 'now'))
);

-- Temporary 6-digit pairing codes for linking devices.
-- Holds the owning user_id only -- no tokens at rest.
CREATE TABLE IF NOT EXISTS pairing_codes (
  code TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);

-- Admin login sessions
CREATE TABLE IF NOT EXISTS admin_sessions (
  session_key TEXT PRIMARY KEY,
  created_at INTEGER DEFAULT 0,
  expires_at INTEGER NOT NULL
);

-- Bounded per-user event log (trimmed to MAX_EVENTS_PER_USER in worker.js)
CREATE TABLE IF NOT EXISTS events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  event_type TEXT,
  payload TEXT,
  ts INTEGER DEFAULT 0
);

-- Aggregate usage counters. Events about events -- never about people.
-- No IPs, no identifiers, no sessions. A day's row is computed while young
-- and then frozen (computed=1), so event trimming can never rewrite history.
CREATE TABLE IF NOT EXISTS daily_stats (
  day TEXT PRIMARY KEY,
  registrations INTEGER DEFAULT -1,
  alerts INTEGER DEFAULT -1,
  thief_alerts INTEGER DEFAULT -1,
  pairings INTEGER DEFAULT 0,
  active_devices INTEGER DEFAULT -1,
  computed INTEGER DEFAULT 0
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_users_token ON users(token);
CREATE INDEX IF NOT EXISTS idx_users_linked_token ON users(linked_token);
CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen);
CREATE INDEX IF NOT EXISTS idx_pairing_expires ON pairing_codes(expires_at);
CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);

-- ---------------------------------------------------------------------------
-- MIGRATION (old schema -> v2.0.0): run once with
--   npx wrangler d1 execute DB --file=migration_v2.sql --remote
-- or paste these statements into `wrangler d1 execute` ad hoc:
--
--   ALTER TABLE users RENAME COLUMN banned TO is_banned;
--   ALTER TABLE users ADD COLUMN total_alerts INTEGER DEFAULT 0;
--   ALTER TABLE users ADD COLUMN linked_token TEXT;
--   DROP TABLE IF EXISTS pairing_codes;            -- codes are ephemeral
--   CREATE TABLE pairing_codes (
--     code TEXT PRIMARY KEY,
--     user_id INTEGER NOT NULL,
--     expires_at INTEGER NOT NULL
--   );
--
-- Old deployments whose users table used `id` instead of `user_id`:
--   ALTER TABLE users RENAME COLUMN id TO user_id;
--
-- NOTE on hashed tokens: existing rows keep working ONLY if their stored
-- value is already a sha256 hex. Plaintext-token rows become invalid after
-- this deploy; clients auto-re-register on 401 (verified behavior), so the
-- safe cutover is simply to let stale devices re-register.
-- If the old DB has plaintext tokens and you want to preserve devices,
-- force re-registration instead of migrating hashes.
-- ---------------------------------------------------------------------------
