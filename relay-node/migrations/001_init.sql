-- v2.0.0 initial schema. Mirrors worker/schema.sql exactly, so the same
-- clients (Python app / Termux / future Kotlin) work against either backend.

CREATE TABLE IF NOT EXISTS users (
  user_id BIGSERIAL PRIMARY KEY,
  token TEXT UNIQUE NOT NULL,            -- sha256 hex; plaintext never stored
  linked_token TEXT,                     -- sha256 hex of paired phone's token
  device_name TEXT,
  platform TEXT,
  battery_pct INTEGER DEFAULT -1,
  is_charging INTEGER DEFAULT 0,
  alert_active INTEGER DEFAULT 0,
  alert_type TEXT,
  alert_ts BIGINT DEFAULT 0,
  last_seen BIGINT DEFAULT 0,
  total_alerts INTEGER DEFAULT 0,
  is_banned INTEGER DEFAULT 0,
  is_pro INTEGER DEFAULT 0,
  is_founding INTEGER DEFAULT 0,
  created_at BIGINT DEFAULT (EXTRACT(EPOCH FROM now()))::bigint
);

CREATE TABLE IF NOT EXISTS pairing_codes (
  code TEXT PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  expires_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_sessions (
  session_key TEXT PRIMARY KEY,
  created_at BIGINT DEFAULT 0,
  expires_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  event_id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  event_type TEXT,
  payload TEXT,
  ts BIGINT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_users_token ON users(token);
CREATE INDEX IF NOT EXISTS idx_users_linked_token ON users(linked_token);
CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen);
CREATE INDEX IF NOT EXISTS idx_pairing_expires ON pairing_codes(expires_at);
CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);

-- Prune helpers run lazily from request paths (same policy as worker.js):
-- expired pairing codes and admin sessions are deleted opportunistically.
