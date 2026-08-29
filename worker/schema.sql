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
  -- v2.3: account-level armed state + disarm pass (sha256, never plaintext)
  armed INTEGER DEFAULT 0,
  armed_by TEXT,
  disarm_hash TEXT,
  -- v2.4: device disarm key (base64 SPKI EC P-256 public key)
  disarm_pubkey TEXT,
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

-- v2.4: one live disarm-key challenge per account (120s TTL)
CREATE TABLE IF NOT EXISTS arm_challenges (
  user_id INTEGER PRIMARY KEY,
  challenge TEXT NOT NULL,
  expires_at INTEGER NOT NULL
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_users_token ON users(token);
CREATE INDEX IF NOT EXISTS idx_users_linked_token ON users(linked_token);
CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen);
CREATE INDEX IF NOT EXISTS idx_pairing_expires ON pairing_codes(expires_at);
CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);

-- v2.1: intruder snapshots. Bodies live in R2 (SNAPSHOTS binding); D1 keeps
-- only the metadata row. Worker prunes to the newest MAX_SNAPSHOTS_PER_USER.
CREATE TABLE IF NOT EXISTS snapshots (
  snap_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  r2_key TEXT NOT NULL,
  content_type TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_user ON snapshots(user_id);

-- v2.2: per-account opt-in Telegram delivery. The bot token + chat id are
-- the account owner's OWN bot; the worker only ever messages that one chat
-- on THIEF_ALERT. Never exposed through the admin dashboard.
CREATE TABLE IF NOT EXISTS user_notify (
  user_id INTEGER PRIMARY KEY,
  bot_token TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  created_at INTEGER NOT NULL
);

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
