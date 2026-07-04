-- Users table (Stores device state and shared tokens)
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  token TEXT UNIQUE NOT NULL,
  device_name TEXT,
  platform TEXT,
  battery_pct INTEGER DEFAULT -1,
  is_charging INTEGER DEFAULT 0,
  alert_active INTEGER DEFAULT 0,
  alert_type TEXT,
  alert_ts INTEGER DEFAULT 0,
  last_seen INTEGER DEFAULT 0,
  banned INTEGER DEFAULT 0,
  is_pro INTEGER DEFAULT 0,
  is_founding INTEGER DEFAULT 0,
  created_at INTEGER DEFAULT (strftime('%s', 'now'))
);

-- Temporary 6-digit pairing codes for linking devices
CREATE TABLE IF NOT EXISTS pairing_codes (
  code TEXT PRIMARY KEY,
  token TEXT NOT NULL,
  expires_at INTEGER NOT NULL
);

-- Admin login sessions
CREATE TABLE IF NOT EXISTS admin_sessions (
  session_key TEXT PRIMARY KEY,
  expires_at INTEGER NOT NULL
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_users_token ON users(token);
CREATE INDEX IF NOT EXISTS idx_users_last_seen ON users(last_seen);
CREATE INDEX IF NOT EXISTS idx_pairing_expires ON pairing_codes(expires_at);